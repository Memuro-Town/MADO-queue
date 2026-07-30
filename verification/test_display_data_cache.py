"""
/display_data キャッシュ機構の検証スクリプト (issue #5 対応)

検証対象: /display_data のみ。他の4ルート(500化)は別ブランチ
(fix/db-error-http-500-only, PR済み)で対応済みのため対象外。

Phase 1: 起動直後(キャッシュ未取得)にDBエラーが起きた場合、空の初期値を返すこと
Phase 2: 正常取得後にDBエラーが起きた場合、直前の正常値をHTTP 200で返し続けること
Phase 3: 「エラー時にキャッシュを返す」→「直後に本当に新しい呼出しが発生する」という
         連続ポーリングのシナリオで、フロント側の差分検出(チャイム用 prevCallingKeys)
         が誤動作しないことを、サーバー側レスポンスの一貫性で保証できているか検証する。
         (エラー応答時に calling が空にリセットされないことを直接確認する)

本番の numbers.db を汚さないよう、一時ファイルを DB_PATH に設定してから
init_db.py でスキーマを作成し、その後 app を import する。
"""
import json
import os
import runpy
import sqlite3
import sys
import tempfile
from contextlib import contextmanager

_tmp_fd, _tmp_path = tempfile.mkstemp(suffix='.db')
os.close(_tmp_fd)
os.environ['DB_PATH'] = _tmp_path
os.environ['CORS_ORIGINS'] = '*'

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
runpy.run_path(os.path.join(BASE_DIR, 'init_db.py'))

import app as app_module  # noqa: E402
from app import app  # noqa: E402

# テスト中に実機プリンターへ印刷しないよう無効化
app_module.print_ticket = lambda *args, **kwargs: True


@contextmanager
def _failing_get_db():
    """DB障害を模擬する get_db の差し替え版。with文に入った時点で例外を送出する。"""
    raise sqlite3.OperationalError("simulated transient DB failure")
    yield  # pragma: no cover (到達しない)


def _start_processing(client, ticket_number, category='A'):
    return client.post(
        '/start_processing',
        data=json.dumps({'ticket_number': ticket_number, 'category': category}),
        content_type='application/json',
    )


def _get_display_data(client):
    resp = client.get('/display_data')
    return resp.status_code, json.loads(resp.data)


def main():
    client = app.test_client()
    results = []

    def record(name, condition, detail=''):
        results.append({'name': name, 'passed': bool(condition), 'detail': detail})

    # --- Phase 1: 起動直後(キャッシュ未取得)にDBエラー ---------------------
    real_get_db = app_module.get_db
    app_module.get_db = _failing_get_db
    try:
        status, body = _get_display_data(client)
    finally:
        app_module.get_db = real_get_db

    record(
        'Phase1: 起動直後DBエラー → 200 + 空の初期値',
        status == 200 and body == {'calling': [], 'waiting_count': 0},
        f'status={status}, body={body}',
    )

    # --- Phase 2: 正常取得 → DBエラー時にキャッシュを返す -------------------
    resp = _start_processing(client, ticket_number=1, category='A')
    assert resp.status_code == 200, f'setup failed: {resp.get_data(as_text=True)}'

    status_ok, state_a = _get_display_data(client)
    record(
        'Phase2-a: 正常時は200 + 実データ',
        status_ok == 200 and len(state_a['calling']) == 1 and state_a['calling'][0]['number'] == 1,
        f'status={status_ok}, body={state_a}',
    )

    app_module.get_db = _failing_get_db
    try:
        status_err, state_after_error = _get_display_data(client)
    finally:
        app_module.get_db = real_get_db

    record(
        'Phase2-b: DBエラー時は200 + 直前の正常値をそのまま返す',
        status_err == 200 and state_after_error == state_a,
        f'status={status_err}, body={state_after_error}, expected={state_a}',
    )

    # --- Phase 3: エラー直後に本当の新規呼出しが発生するシナリオ -------------
    # ここまでの流れ: state_a(呼出中: [1]) → エラー時も state_a のまま(上で確認済み)
    # → この直後に ticket 2 が新たに呼び出された場合、次のポーリングで
    #   「[1] → [1, 2]」という正しい差分が見える必要がある(誤って「[] → [1,2]」に
    #   ならないこと = フロントのチャイム用 prevCallingKeys が誤リセットされていないこと)
    resp = _start_processing(client, ticket_number=2, category='A')
    assert resp.status_code == 200, f'setup failed: {resp.get_data(as_text=True)}'

    status_b, state_b = _get_display_data(client)
    calling_numbers_b = sorted(c['number'] for c in state_b['calling'])

    record(
        'Phase3: エラー直後の新規呼出しが正しく反映される(=チャイムが鳴る条件を満たす)',
        status_b == 200 and calling_numbers_b == [1, 2],
        f'status={status_b}, calling_numbers={calling_numbers_b} (期待値: [1, 2])',
    )

    # 補足チェック: state_a → state_b の差分が「1件追加」のみであること
    # (エラー応答を挟んでも [] を経由していないため、差分計算上は単純な追加になる)
    added = set(calling_numbers_b) - {c['number'] for c in state_a['calling']}
    record(
        'Phase3-補足: 差分が新規追加(ticket 2)のみで、既存分の消失がない',
        added == {2} and 1 in calling_numbers_b,
        f'added={added}, calling_numbers_b={calling_numbers_b}',
    )

    print('=' * 70)
    print('/display_data cache verification (issue #5)')
    print('=' * 70)
    all_pass = True
    for r in results:
        mark = 'PASS' if r['passed'] else 'FAIL'
        if not r['passed']:
            all_pass = False
        print(f"  [{mark}] {r['name']}")
        if not r['passed']:
            print(f"         {r['detail']}")
    print('-' * 70)
    print(f"Result: {'ALL PASSED' if all_pass else 'SOME FAILED'} ({len(results)} tests)")
    print('=' * 70)

    try:
        os.remove(_tmp_path)
    except OSError:
        pass

    return all_pass


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
