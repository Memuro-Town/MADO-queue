"""Dockerと同じLinux/Python環境で、推移的依存とwheel hashを更新する。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import quote
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument('--output', type=Path, default=root / 'requirements-docker.lock')
    args = parser.parse_args()
    if sys.platform != 'linux' or sys.version_info[:2] != (3, 14):
        parser.error('Run with the Dockerfile Python 3.14 Linux base image')
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / 'report.json'
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--dry-run',
                        '--ignore-installed', '--only-binary=:all:', '--upgrade',
                        '--report', str(report), '-r', str(root / 'requirements.txt')], check=True)
        items = json.loads(report.read_text())['install']

    def hashes(item):
        name = item['metadata']['name']
        version = item['metadata']['version']
        url = f'https://pypi.org/pypi/{quote(name, safe="")}/{quote(version, safe="")}/json'
        with urlopen(url, timeout=90) as response:
            release = json.load(response)
        values = sorted({f['digests']['sha256'] for f in release['urls']
                         if f['packagetype'] == 'bdist_wheel' and not f.get('yanked')})
        if not values:
            raise RuntimeError(f'No non-yanked wheels: {name}=={version}')
        return name, version, values

    with ThreadPoolExecutor(max_workers=4) as pool:
        packages = list(pool.map(hashes, items))
    lines = ['# Docker runtime only. Python 3.14; resolved application dependencies.',
             '# Each release includes wheel hashes for supported platforms.',
             '# Refresh procedure: docs/DOCKER.md. Native requirements.txt is separate.', '']
    for name, version, values in sorted(packages, key=lambda row: row[0].lower()):
        lines.append(f'{name}=={version} \\')
        for i, value in enumerate(values):
            lines.append('    --hash=sha256:' + value + (' \\' if i < len(values) - 1 else ''))
        lines.append('')
    # エラー時に既存lockを途中まで書き換えない。
    pending = args.output.with_suffix(args.output.suffix + '.tmp')
    pending.write_text('\n'.join(lines), encoding='utf-8')
    pending.replace(args.output)
    print(f'Wrote {len(packages)} packages to {args.output}')


if __name__ == '__main__':
    main()
