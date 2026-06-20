"""
既存DBを新スキーマ（安定キー中心）へ移行するスクリプト。

旧スキーマでは processing_logs.event_log_id が NULL 可で、ランタイムが
「ticket_number + category + 当日」で event_logs と OR 照合していた。
本移行ではその照合を **一度だけ** 実行して event_log_id をバックフィルし、
event_log_id を NOT NULL + 外部キーに、status を CHECK 制約に作り替える。

冪等: 既に新スキーマ（event_logs への FK あり）なら何もしない。
"""

import os
import sqlite3

# app.py / init_db.py と同じく DB_PATH 環境変数を優先する（Docker では /data/numbers.db）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path  = os.environ.get('DB_PATH', os.path.join(BASE_DIR, 'numbers.db'))

# 旧スキーマに欠けていることがある列（後続の照合・コピーを成立させるため先に補う）
_BACKFILL_COLUMNS = {
    'category': 'TEXT', 'button_text': 'TEXT', 'start_time': 'TEXT', 'end_time': 'TEXT',
    'status': 'TEXT', 'processing_time': 'INTEGER', 'staff_count': 'INTEGER',
    'event_log_id': 'INTEGER',
}

_NEW_PROCESSING_LOGS = """
CREATE TABLE processing_logs__new (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    event_log_id    INTEGER  NOT NULL REFERENCES event_logs(id),
    ticket_number   INTEGER  NOT NULL,
    category        CHAR(1),
    button_text     TEXT,
    start_time      TEXT,
    end_time        TEXT,
    wait_time       INTEGER,
    status          TEXT     NOT NULL
                    CHECK (status IN ('processing', 'completed', 'deleted')),
    processing_time INTEGER,
    created_at      TEXT     NOT NULL,
    staff_count     INTEGER
)
"""


def safe_migrate():
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA foreign_keys = OFF')   # 作り替え中は一旦無効化
    cur = conn.cursor()

    try:
        # --- 冪等チェック: 既に event_logs への FK があれば移行済み ---
        fks = cur.execute("PRAGMA foreign_key_list(processing_logs)").fetchall()
        if any(fk[2] == 'event_logs' for fk in fks):
            print("Already migrated (FK to event_logs present). Nothing to do.")
            return

        # --- event_logs 側の不足列（staff_count）を補う ---
        ev_cols = [c[1] for c in cur.execute("PRAGMA table_info(event_logs)").fetchall()]
        if 'staff_count' not in ev_cols:
            print("Adding event_logs.staff_count")
            cur.execute("ALTER TABLE event_logs ADD COLUMN staff_count INTEGER")

        # --- processing_logs 側の不足列を補う ---
        pl_cols = [c[1] for c in cur.execute("PRAGMA table_info(processing_logs)").fetchall()]
        for name, typ in _BACKFILL_COLUMNS.items():
            if name not in pl_cols:
                print(f"Adding processing_logs.{name} ({typ})")
                cur.execute(f"ALTER TABLE processing_logs ADD COLUMN {name} {typ}")

        # --- 1) event_log_id のバックフィル（旧ランタイムの OR 照合を一度だけ実行）---
        cur.execute("""
            UPDATE processing_logs
               SET event_log_id = (
                   SELECT e.id FROM event_logs e
                    WHERE e.current_number = processing_logs.ticket_number
                      AND e.category       = processing_logs.category
                      AND DATE(e.timestamp,  'localtime')
                        = DATE(processing_logs.created_at, 'localtime')
                    ORDER BY e.id DESC LIMIT 1
               )
             WHERE event_log_id IS NULL
        """)
        backfilled = cur.rowcount
        print(f"Backfilled event_log_id on up to {backfilled} rows")

        # --- 2) 参照先(event_logs)のない行があれば中止（NOT NULL/FK 違反になるため）---
        orphans = cur.execute(
            "SELECT COUNT(*) FROM processing_logs WHERE event_log_id IS NULL").fetchone()[0]
        if orphans:
            print(f"ABORT: {orphans} rows have no matching event_log. "
                  "Resolve these manually before migrating (no data was changed).")
            conn.rollback()
            return

        # --- 3) status の想定外値チェック（CHECK 制約に通らないため事前に検出）---
        bad = cur.execute(
            "SELECT COUNT(*) FROM processing_logs"
            " WHERE status IS NULL OR status NOT IN ('processing','completed','deleted')"
        ).fetchone()[0]
        if bad:
            print(f"ABORT: {bad} rows have NULL/unexpected status. "
                  "Resolve these manually before migrating (no data was changed).")
            conn.rollback()
            return

        # --- 4) 新制約付きテーブルへ作り替え（FK / CHECK / NOT NULL）---
        cur.executescript(_NEW_PROCESSING_LOGS + """;
            INSERT INTO processing_logs__new
                (id, event_log_id, ticket_number, category, button_text, start_time,
                 end_time, wait_time, status, processing_time, created_at, staff_count)
            SELECT id, event_log_id, ticket_number, category, button_text, start_time,
                   end_time, wait_time, status, processing_time, created_at, staff_count
              FROM processing_logs;
            DROP TABLE processing_logs;
            ALTER TABLE processing_logs__new RENAME TO processing_logs;
            CREATE INDEX IF NOT EXISTS idx_pl_event_log_id ON processing_logs(event_log_id);
            CREATE INDEX IF NOT EXISTS idx_pl_status       ON processing_logs(status);
        """)

        # --- 5) FK 整合性の最終確認 ---
        violations = cur.execute("PRAGMA foreign_key_check(processing_logs)").fetchall()
        if violations:
            print(f"ABORT: foreign key violations after rebuild: {violations}")
            conn.rollback()
            return

        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Migration error: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    safe_migrate()
