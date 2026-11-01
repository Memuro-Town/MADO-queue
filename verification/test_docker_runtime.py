"""Docker版の権限・DB保持・バックアップ復元を隔離環境で検証する。

Linux/WSL: python3 verification/test_docker_runtime.py IMAGE
Dockerデーモンへのアクセスが必要。ホストの本番DB/USBは接続しない。
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

IMAGE = sys.argv[1]
ROOT = Path(__file__).resolve().parents[1]


def docker(*args, check=True, timeout=120):
    return subprocess.run(['docker', *map(str, args)], text=True,
                          capture_output=True, check=check, timeout=timeout)


def execute(container, code):
    return docker('exec', container, 'python', '-c', code).stdout.strip()


def ready(container):
    for _ in range(60):
        r = docker('exec', container, 'python', '-c',
                   'import urllib.request; assert urllib.request.urlopen('
                   '"http://127.0.0.1:8000/",timeout=2).status==200', check=False)
        if r.returncode == 0:
            return
        time.sleep(0.5)
    raise AssertionError(docker('logs', container).stdout)


def request(container, route, body=None):
    code = ('import json,urllib.request; '
            f'b={body!r}; '
            f'r=urllib.request.Request("http://127.0.0.1:8000{route}", '
            'data=None if b is None else json.dumps(b).encode(), '
            'headers={"Content-Type":"application/json"}); '
            'print(urllib.request.urlopen(r,timeout=10).read().decode())')
    return execute(container, code)


def main():
    meta = json.loads(docker('image', 'inspect', IMAGE).stdout)[0]
    assert meta['Config']['User'] == '10001:10001'
    options = ['--network', 'none', '--cap-drop', 'ALL', '--security-opt',
               'no-new-privileges:true']
    check = '''import os,sqlite3,ctypes,ctypes.util,importlib.util,json
assert os.getuid()==10001
assert importlib.util.find_spec('pip') is None
assert importlib.util.find_spec('setuptools') is None
assert importlib.util.find_spec('urllib3') is None
assert importlib.util.find_spec('msgpack') is None
libusb = ctypes.util.find_library('usb-1.0')
assert libusb, 'libusb-1.0 shared library was not found'
ctypes.CDLL(libusb)
assert not os.access('/app/app.py',os.W_OK)
print(json.dumps({'uid':os.getuid(),'sqlite':sqlite3.sqlite_version}))'''
    print(docker('run', '--rm', *options, '--entrypoint', 'python', IMAGE,
                 '-c', check).stdout.strip(), flush=True)
    result = docker('run', '--rm', *options, '--entrypoint', 'sh', IMAGE, '-c',
                    'find /usr/bin /usr/sbin /usr/local/bin /usr/local/sbin '
                    '-xdev -type f \\( -perm -4000 -o -perm -2000 \\) -print')
    assert not result.stdout.strip(), result.stdout
    # 既存API/移行テストを同じ実行用イメージで実行（実機印刷はテスト内で無効化）。
    result = docker('run', '--rm', *options, '--entrypoint', 'python',
                    '--mount', f'type=bind,src={ROOT / "test_app.py"},dst=/app/test_app.py,readonly',
                    IMAGE, '/app/test_app.py')
    print(result.stdout + result.stderr, flush=True)
    token = uuid.uuid4().hex[:12]
    volume = 'queue-security-test-' + token
    container = 'queue-security-test-' + token
    docker('volume', 'create', volume)
    try:
        docker('run', '-d', '--name', container, *options,
               '--mount', f'type=volume,src={volume},dst=/data', IMAGE)
        ready(container)
        for route in ['/processing', '/display', '/display_data']:
            request(container, route)
        issued = json.loads(request(container, '/get_next_number',
                                    {'category': 'A', 'buttonText': 'docker verification'}))
        assert issued['event_log_id'] > 0
        called = json.loads(request(container, '/start_processing',
                                    {'event_log_id': issued['event_log_id']}))
        assert called['success'], called
        pid = execute(container, 'import sqlite3; c=sqlite3.connect("/data/numbers.db"); '
                      'print(c.execute("SELECT id FROM processing_logs ORDER BY id DESC LIMIT 1").fetchone()[0])')
        assert json.loads(request(container, '/end_processing',
                                  {'processing_id': int(pid)}))['success']
        state = execute(container, 'print(open("/proc/1/status").read())')
        assert 'NoNewPrivs:\t1' in state and 'CapEff:\t0000000000000000' in state
        # SQLiteのオンラインbackup APIで独立したバックアップを取得する。
        execute(container, 'import sqlite3; c=sqlite3.connect("/data/numbers.db"); '
                'b=sqlite3.connect("/data/backup.db"); c.backup(b); b.close(); c.close()')
        docker('restart', container)
        ready(container)
        count = execute(container, 'import sqlite3; c=sqlite3.connect("/data/numbers.db"); '
                        'print(c.execute("SELECT count(*) FROM event_logs").fetchone()[0])')
        assert int(count) == 1
        with tempfile.TemporaryDirectory(prefix='queue-restore-') as tmp:
            snapshot = Path(tmp) / 'numbers.db'
            docker('cp', f'{container}:/data/backup.db', snapshot)
            # 実運用フォルダーには触れず、複製DBをホストUIDでbindして復元・再起動する。
            restored = container + '-restore'
            try:
                docker('run', '-d', '--name', restored, *options,
                       '--user', f'{os.getuid()}:{os.getgid()}',
                       '--mount', f'type=bind,src={tmp},dst=/data', IMAGE)
                ready(restored)
                check_db = execute(restored, 'import sqlite3,json; c=sqlite3.connect("/data/numbers.db"); '
                                   'print(json.dumps([c.execute("PRAGMA integrity_check").fetchone()[0],'
                                   'c.execute("SELECT count(*) FROM event_logs").fetchone()[0]]))')
                assert json.loads(check_db) == ['ok', 1]
                next_ticket = json.loads(request(restored, '/get_next_number', {'category': 'A'}))
                assert next_ticket['event_log_id'] > issued['event_log_id']
            finally:
                docker('rm', '-f', restored, check=False)
        # 誤った権限の保存先では初期化やchmodをせず明確に失敗する。
        with tempfile.TemporaryDirectory(prefix='queue-unwritable-') as tmp:
            os.chmod(tmp, 0o555)
            try:
                failure = docker('run', '--rm', *options, '--mount',
                                 f'type=bind,src={tmp},dst=/data', IMAGE, check=False)
                assert failure.returncode != 0 and 'DB directory' in failure.stderr
                assert not (Path(tmp) / 'numbers.db').exists()
            finally:
                os.chmod(tmp, 0o755)
        print('PASS: nonroot, no pip/SUID/caps, libusb, existing tests, fresh DB, '
              'HTTP ticket/call/complete/display, restart, cloned DB restore/write, permissions fail closed', flush=True)
        print('NOT TESTED: physical USB printing, Windows Docker Desktop', flush=True)
    finally:
        docker('rm', '-f', container, check=False)
        docker('volume', 'rm', volume, check=False)


if __name__ == '__main__':
    main()
