"""
/get_next_number の基本動作テスト。

本番の numbers.db を汚さないよう、一時ファイルを DB_PATH に設定してから
app を import する（app.py は import 時に DB_PATH を読むため順序が重要）。
"""

import json
import os
import runpy
import tempfile
import unittest

_tmp_fd, _tmp_path = tempfile.mkstemp(suffix='.db')
os.close(_tmp_fd)
os.environ['DB_PATH'] = _tmp_path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
runpy.run_path(os.path.join(BASE_DIR, 'init_db.py'))

import app as app_module
from app import app

# テスト中に実機プリンターへ印刷しないよう無効化する
app_module.print_ticket = lambda *args, **kwargs: True


def tearDownModule():
    try:
        os.remove(_tmp_path)
    except OSError:
        pass


class FlaskTest(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_get_next_number(self):
        request_data = {'category': 'A'}
        response = self.app.post(
            '/get_next_number',
            data=json.dumps(request_data),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

        response_data = json.loads(response.data)
        self.assertEqual(response_data['category'], 'A')
        self.assertIn('next_number', response_data)
        self.assertTrue(response_data['print_ok'])

    def test_get_next_number_returns_print_status_when_print_fails(self):
        original_print_ticket = app_module.print_ticket
        app_module.print_ticket = lambda *args, **kwargs: False
        try:
            response = self.app.post(
                '/get_next_number',
                data=json.dumps({'category': 'A'}),
                content_type='application/json',
            )
        finally:
            app_module.print_ticket = original_print_ticket

        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.data)
        self.assertEqual(response_data['category'], 'A')
        self.assertIn('next_number', response_data)
        self.assertFalse(response_data['print_ok'])

    def test_get_next_number_increments(self):
        first = json.loads(self.app.post(
            '/get_next_number',
            data=json.dumps({'category': 'B'}),
            content_type='application/json',
        ).data)
        second = json.loads(self.app.post(
            '/get_next_number',
            data=json.dumps({'category': 'B'}),
            content_type='application/json',
        ).data)
        self.assertEqual(second['next_number'], first['next_number'] + 1)

    def test_missing_category(self):
        response = self.app.post(
            '/get_next_number',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_start_processing_rejects_non_numeric_ticket(self):
        """ticket_number に文字列（XSSペイロード等）を渡すと 400 になること"""
        response = self.app.post(
            '/start_processing',
            data=json.dumps({
                'ticket_number': '<img src=x onerror=alert(1)>',
                'category': 'A',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_start_processing_rejects_unknown_category(self):
        response = self.app.post(
            '/start_processing',
            data=json.dumps({'ticket_number': 1, 'category': '<script>'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_start_processing_accepts_numeric_string(self):
        """既存クライアントは ticket_number を文字列で送るため '5' は通ること"""
        response = self.app.post(
            '/start_processing',
            data=json.dumps({'ticket_number': '5', 'category': 'A'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.data)['success'])


if __name__ == '__main__':
    unittest.main()
