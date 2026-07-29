"""
DB エラー時の HTTP ステータスコード検証スクリプト (500化対象ルートのみ)

修正対象: /start_processing, /end_processing, /cancel_processing, /delete_ticket
修正内容: DBエラー時に HTTP 200 → HTTP 500

検証対象外: /display_data (別ブランチで対応)
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['DB_PATH'] = os.path.join(tempfile.gettempdir(), '__nonexistent_mado_test__', 'no.db')
os.environ['CORS_ORIGINS'] = '*'

from app import app


TESTS = [
    {
        'name': '/get_next_number (missing category)',
        'method': 'post',
        'path': '/get_next_number',
        'json': {},
        'expect_status': 400,
    },
    {
        'name': '/get_next_number (valid input, DB error)',
        'method': 'post',
        'path': '/get_next_number',
        'json': {'category': 'A', 'buttonText': 'test'},
        'expect_status': 500,
    },
    {
        'name': '/start_processing (DB error)',
        'method': 'post',
        'path': '/start_processing',
        'json': {'ticket_number': 1, 'category': 'A'},
        'expect_status': 500,
    },
    {
        'name': '/end_processing (DB error)',
        'method': 'post',
        'path': '/end_processing',
        'json': {'ticket_number': 1},
        'expect_status': 500,
    },
    {
        'name': '/cancel_processing (DB error)',
        'method': 'post',
        'path': '/cancel_processing',
        'json': {'ticket_number': 1},
        'expect_status': 500,
    },
    {
        'name': '/delete_ticket (DB error)',
        'method': 'post',
        'path': '/delete_ticket',
        'json': {'ticket_number': 1, 'category': 'A'},
        'expect_status': 500,
    },
    {
        'name': '/display_data (DB error, unchanged)',
        'method': 'get',
        'path': '/display_data',
        'json': None,
        'expect_status': 200,
    },
]


def run_tests():
    client = app.test_client()
    results = []
    for t in TESTS:
        if t['method'] == 'post':
            resp = client.post(
                t['path'],
                data=json.dumps(t['json'] or {}),
                content_type='application/json',
            )
        else:
            resp = client.get(t['path'])

        actual = resp.status_code
        passed = actual == t['expect_status']
        body = ''
        if not passed:
            try:
                body = resp.get_data(as_text=True)[:200]
            except Exception:
                body = '<unreadable>'
        results.append({
            'name': t['name'],
            'expected': t['expect_status'],
            'actual': actual,
            'passed': passed,
            'body': body,
        })
    return results


def main():
    results = run_tests()

    all_pass = all(r['passed'] for r in results)
    print('=' * 70)
    print('DB Error HTTP Status Code Verification (500-only branch)')
    print('=' * 70)
    for r in results:
        mark = 'PASS' if r['passed'] else 'FAIL'
        print(f"  [{mark}] {r['name']}: expected={r['expected']}, actual={r['actual']}")
        if r['body']:
            print(f"         body: {r['body'][:150]}")
    print('-' * 70)
    print(f"Result: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    print('=' * 70)
    return all_pass, results


if __name__ == '__main__':
    ok, results = main()
    sys.exit(0 if ok else 1)
