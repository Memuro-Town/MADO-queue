"""
MADO-queue のエンドポイント・整合性・移行テスト。

本番の numbers.db を汚さないよう、一時ファイルを DB_PATH に設定してから
app を import する（app.py は import 時に DB_PATH を読むため順序が重要）。
各テストは setUp で DB を初期状態に戻すため、実行順に依存しない。
"""

import json
import os
import runpy
import sqlite3
import tempfile
import unittest

_tmp_fd, _tmp_path = tempfile.mkstemp(suffix='.db')
os.close(_tmp_fd)
os.environ['DB_PATH'] = _tmp_path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
runpy.run_path(os.path.join(BASE_DIR, 'init_db.py'))

import app as app_module
from app import app
from config import CATEGORY_START

# テスト中に実機プリンターへ印刷しないよう無効化する
app_module.print_ticket = lambda *args, **kwargs: None


def tearDownModule():
    try:
        os.remove(_tmp_path)
    except OSError:
        pass


class MadoTestBase(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        self._reset_db()

    # --- ヘルパー -----------------------------------------------------------

    def _reset_db(self):
        """全テーブルを空にし、numbers を初期値で再シードする。"""
        conn = sqlite3.connect(app_module.DB_PATH)
        cur = conn.cursor()
        cur.execute('DELETE FROM processing_logs')   # 子から先に消す
        cur.execute('DELETE FROM event_logs')
        cur.execute('DELETE FROM numbers')
        cur.executemany(
            'INSERT INTO numbers (category, current_number) VALUES (?, ?)',
            list(CATEGORY_START.items()),
        )
        conn.commit()
        conn.close()

    def _query(self, sql, params=()):
        conn = sqlite3.connect(app_module.DB_PATH)
        conn.execute('PRAGMA foreign_keys = ON')
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return rows

    def _issue(self, category='A', staff=1, button='住民票'):
        body = {'category': category, 'buttonText': button}
        if staff is not None:
            body['staffCount'] = staff
        return json.loads(self.app.post('/get_next_number', json=body).data)

    def _start(self, event_log_id):
        return self.app.post('/start_processing', json={'event_log_id': event_log_id})

    def _processing_id(self, event_log_id):
        rows = self._query(
            "SELECT id FROM processing_logs"
            " WHERE event_log_id = ? AND status = 'processing'"
            " ORDER BY id DESC LIMIT 1",
            (event_log_id,))
        return rows[0][0] if rows else None

    def _waiting_count(self):
        return json.loads(self.app.get('/display_data').data)['waiting_count']


class IssueTest(MadoTestBase):

    def test_issue_returns_start_number_and_event_log_id(self):
        data = self._issue('A')
        self.assertEqual(data['category'], 'A')
        self.assertEqual(data['next_number'], CATEGORY_START['A'])
        self.assertIsInstance(data['event_log_id'], int)

    def test_issue_increments(self):
        first = self._issue('B')['next_number']
        second = self._issue('B')['next_number']
        self.assertEqual(second, first + 1)

    def test_missing_category_rejected(self):
        resp = self.app.post('/get_next_number', json={'staffCount': 1})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_category_rejected(self):
        resp = self.app.post('/get_next_number', json={'category': 'Z', 'staffCount': 1})
        self.assertEqual(resp.status_code, 404)

    def test_staff_count_optional_per_spec(self):
        # 仕様では staffCount は任意。無指定でも 200 で発行でき、staff_count は NULL。
        data = self._issue('A', staff=None)
        self.assertEqual(data['next_number'], CATEGORY_START['A'])
        rows = self._query('SELECT staff_count FROM event_logs WHERE id = ?',
                           (data['event_log_id'],))
        self.assertIsNone(rows[0][0])

    def test_staff_count_persisted_when_given(self):
        data = self._issue('A', staff=3)
        rows = self._query('SELECT staff_count FROM event_logs WHERE id = ?',
                           (data['event_log_id'],))
        self.assertEqual(rows[0][0], 3)


class StartProcessingTest(MadoTestBase):

    def test_requires_event_log_id(self):
        resp = self.app.post('/start_processing', json={})
        self.assertEqual(resp.status_code, 400)

    def test_non_numeric_event_log_id_rejected(self):
        resp = self.app.post('/start_processing',
                             json={'event_log_id': '<script>'})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_event_log_id_returns_404(self):
        resp = self._start(999999)
        self.assertEqual(resp.status_code, 404)

    def test_start_creates_processing_row(self):
        eid = self._issue('A')['event_log_id']
        resp = self._start(eid)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(json.loads(resp.data)['success'])
        rows = self._query(
            "SELECT event_log_id, ticket_number, status FROM processing_logs"
            " WHERE event_log_id = ?", (eid,))
        self.assertEqual(rows, [(eid, CATEGORY_START['A'], 'processing')])

    def test_double_start_is_idempotent(self):
        eid = self._issue('A')['event_log_id']
        self._start(eid)
        r2 = self._start(eid)
        self.assertTrue(json.loads(r2.data).get('already_processing'))
        rows = self._query(
            "SELECT id FROM processing_logs WHERE event_log_id = ? AND status = 'processing'",
            (eid,))
        self.assertEqual(len(rows), 1)


class LifecycleTest(MadoTestBase):

    def test_start_moves_ticket_out_of_waiting(self):
        eid = self._issue('A')['event_log_id']
        self.assertEqual(self._waiting_count(), 1)
        self._start(eid)
        self.assertEqual(self._waiting_count(), 0)

    def test_end_processing_completes(self):
        eid = self._issue('A')['event_log_id']
        self._start(eid)
        pid = self._processing_id(eid)
        resp = self.app.post('/end_processing', json={'processing_id': pid})
        self.assertTrue(json.loads(resp.data)['success'])
        rows = self._query(
            "SELECT status, processing_time FROM processing_logs WHERE id = ?", (pid,))
        self.assertEqual(rows[0][0], 'completed')
        self.assertIsNotNone(rows[0][1])

    def test_end_requires_processing_id(self):
        resp = self.app.post('/end_processing', json={})
        self.assertEqual(resp.status_code, 400)

    def test_end_unknown_id_returns_404(self):
        resp = self.app.post('/end_processing', json={'processing_id': 999999})
        self.assertEqual(resp.status_code, 404)

    def test_cancel_returns_ticket_to_waiting(self):
        eid = self._issue('A')['event_log_id']
        self._start(eid)
        pid = self._processing_id(eid)
        self.assertEqual(self._waiting_count(), 0)
        resp = self.app.post('/cancel_processing', json={'processing_id': pid})
        self.assertTrue(json.loads(resp.data)['success'])
        self.assertEqual(self._waiting_count(), 1)
        self.assertEqual(
            self._query("SELECT COUNT(*) FROM processing_logs WHERE id = ?", (pid,))[0][0], 0)

    def test_cancel_unknown_id_returns_404(self):
        resp = self.app.post('/cancel_processing', json={'processing_id': 999999})
        self.assertEqual(resp.status_code, 404)

    def test_delete_records_deleted_row_and_removes_from_waiting(self):
        eid = self._issue('A')['event_log_id']
        self.assertEqual(self._waiting_count(), 1)
        resp = self.app.post('/delete_ticket', json={'event_log_id': eid})
        self.assertTrue(json.loads(resp.data)['success'])
        rows = self._query(
            "SELECT status FROM processing_logs WHERE event_log_id = ?", (eid,))
        self.assertEqual(rows, [('deleted',)])
        self.assertEqual(self._waiting_count(), 0)

    def test_delete_unknown_event_log_returns_404(self):
        resp = self.app.post('/delete_ticket', json={'event_log_id': 999999})
        self.assertEqual(resp.status_code, 404)


class IntegrityTest(MadoTestBase):
    """設計準拠の DB 制約（FK / CHECK）が効いていること"""

    def _insert_processing(self, **cols):
        conn = sqlite3.connect(app_module.DB_PATH)
        conn.execute('PRAGMA foreign_keys = ON')
        try:
            keys = ', '.join(cols)
            ph = ', '.join('?' * len(cols))
            conn.execute(f'INSERT INTO processing_logs ({keys}) VALUES ({ph})',
                        tuple(cols.values()))
            conn.commit()
        finally:
            conn.close()

    def test_foreign_key_rejects_orphan_event_log_id(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_processing(
                event_log_id=999999, ticket_number=1,
                status='processing', created_at='2026-06-21T09:00:00+09:00')

    def test_check_rejects_unknown_status(self):
        eid = self._issue('A')['event_log_id']
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_processing(
                event_log_id=eid, ticket_number=1,
                status='bogus', created_at='2026-06-21T09:00:00+09:00')

    def test_indexes_exist(self):
        idx = [r[0] for r in self._query(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND tbl_name='processing_logs'")]
        self.assertIn('idx_pl_event_log_id', idx)
        self.assertIn('idx_pl_status', idx)


class WaitingListTest(MadoTestBase):

    def test_category_d_excluded(self):
        self._issue('A')
        self._issue('D')
        self.assertEqual(self._waiting_count(), 1)

    def test_multiple_tickets_counted(self):
        self._issue('A'); self._issue('A'); self._issue('B')
        self.assertEqual(self._waiting_count(), 3)

    def test_processing_page_renders(self):
        eid = self._issue('A')['event_log_id']
        self._start(eid)
        self.assertEqual(self.app.get('/processing').status_code, 200)


class DailyResetTest(MadoTestBase):

    def test_resets_on_new_day(self):
        conn = sqlite3.connect(app_module.DB_PATH)
        conn.execute(
            "UPDATE numbers SET current_number = 42, timestamp = '2000-01-01' WHERE category = 'A'")
        conn.commit()
        conn.close()
        self.assertEqual(self._issue('A')['next_number'], CATEGORY_START['A'])

    def test_no_reset_within_same_day(self):
        self.assertEqual(self._issue('A')['next_number'], CATEGORY_START['A'])
        self.assertEqual(self._issue('A')['next_number'], CATEGORY_START['A'] + 1)


class MigrationTest(unittest.TestCase):
    """旧スキーマ→新スキーマ移行（event_log_id バックフィル＋制約付与）"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        import safe_migrate_db
        self.smd = safe_migrate_db
        self.smd.db_path = self.db   # モジュールのグローバルを差し替え

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _build_legacy(self, with_orphan=False):
        """event_log_id も FK も無い旧スキーマの DB を作る。"""
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute("""CREATE TABLE event_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category CHAR(1) NOT NULL,
            button_text TEXT, timestamp TEXT NOT NULL, current_number INTEGER NOT NULL,
            staff_count INTEGER)""")
        c.execute("""CREATE TABLE processing_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_number INTEGER NOT NULL,
            category TEXT, status TEXT, wait_time INTEGER, processing_time INTEGER,
            created_at TEXT NOT NULL)""")
        ts = '2026-06-21T09:00:00+09:00'
        c.execute("INSERT INTO event_logs (category, button_text, timestamp, current_number)"
                  " VALUES ('A', '住民票', ?, 5)", (ts,))
        # 旧処理ログ: event_log_id を持たず、番号+カテゴリ+当日でしか辿れない
        c.execute("INSERT INTO processing_logs (ticket_number, category, status, created_at)"
                  " VALUES (5, 'A', 'completed', ?)", (ts,))
        if with_orphan:
            c.execute("INSERT INTO processing_logs (ticket_number, category, status, created_at)"
                      " VALUES (777, 'A', 'completed', ?)", (ts,))
        conn.commit()
        conn.close()

    def _fk_to_event_logs(self):
        conn = sqlite3.connect(self.db)
        fks = conn.execute("PRAGMA foreign_key_list(processing_logs)").fetchall()
        conn.close()
        return any(fk[2] == 'event_logs' for fk in fks)

    def test_backfills_and_adds_constraints(self):
        self._build_legacy()
        self.smd.safe_migrate()
        self.assertTrue(self._fk_to_event_logs())
        conn = sqlite3.connect(self.db)
        # 旧 OR 照合がバックフィルされ、event_log_id が親 (=1) を指す
        row = conn.execute(
            "SELECT event_log_id FROM processing_logs WHERE ticket_number = 5").fetchone()
        conn.close()
        self.assertEqual(row[0], 1)

    def test_idempotent(self):
        self._build_legacy()
        self.smd.safe_migrate()
        self.smd.safe_migrate()  # 2回目は "Already migrated" で何もしない
        self.assertTrue(self._fk_to_event_logs())

    def test_aborts_on_orphan_without_changing_data(self):
        self._build_legacy(with_orphan=True)
        self.smd.safe_migrate()
        # 孤児行があるので移行は中止され、旧スキーマ（FK 無し）のまま
        self.assertFalse(self._fk_to_event_logs())


if __name__ == '__main__':
    unittest.main()
