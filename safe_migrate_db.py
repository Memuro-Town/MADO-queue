"""
既存DBを新スキーマ（安定キー中心）へ移行するスクリプト。

旧スキーマでは processing_logs.event_log_id が NULL 可で、ランタイムが
「ticket_number + category + 当日」で event_logs と OR 照合していた。
本移行ではその照合を **一度だけ** 実行して event_log_id をバックフィルし、
event_log_id を NOT NULL + 外部キーに、status を CHECK 制約に作り替える。

冪等: 既に新スキーマ（event_logs への FK あり）なら何もしない。

日付照合は DATE(created_at) のみを用いる（'localtime' 修飾子は付けない）。
created_at / timestamp は元々ローカル時刻で保存されているため、'localtime'
を付けるとUTC起点とみなされ二重に加算されてしまう（PR #38で修正済みの
「呼び出し済み番号が15時以降に当日一覧から消える」バグと同一の原因）。
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

# 2026-07-29、本番DBのコピーに対する事前検証で判明した過去の孤立データ（processing_logs.id）。
# 原因は2つの既知バグの複合（いずれも本移行時点で修正済み・2026-03-17以降は発生なし）：
#   - タイムゾーン二重変換バグ（PR #38で修正）
#   - 日次カウンタの499/500境界バグ（修正済み）
# event_logs 側に対応する記録がそもそも存在しないため自動照合では解決できず、
# 移行用ダミー event_log（1件）を作成してこの50件だけをそこに紐付ける。
# 想定外の孤立データ（この50件以外）が見つかった場合は、従来通り中断する。
_KNOWN_LEGACY_ORPHAN_IDS = frozenset({
    57, 129, 130, 131, 262, 263, 372, 428, 429, 488,
    489, 717, 718, 862, 863, 928, 994, 995, 1158, 1274,
    1344, 1345, 1346, 1464, 1465, 1596, 1597, 1675, 1676, 1677,
    1734, 1895, 1973, 2095, 2096, 2164, 2165, 2253, 2254, 2310,
    2389, 2390, 2487, 2488, 2604, 2650, 2716, 2717, 2718, 2719,
})

_DUMMY_EVENT_LOG_BUTTON_TEXT = (
    "移行用ダミー：TZ二重変換バグ+499/500境界バグ(2026-01〜03、既に修正済み)"
    "により対応するevent_logsが存在しない過去50件の暫定紐付け先"
)

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
                      AND DATE(e.timestamp) = DATE(processing_logs.created_at)
                    ORDER BY e.id DESC LIMIT 1
               )
             WHERE event_log_id IS NULL
        """)
        backfilled = cur.rowcount
        print(f"Backfilled event_log_id on up to {backfilled} rows")

        # --- 2) 参照先(event_logs)のない行があれば、既知のレガシー孤立データか確認 ---
        orphan_ids = [r[0] for r in cur.execute(
            "SELECT id FROM processing_logs WHERE event_log_id IS NULL").fetchall()]

        unexpected_orphans = [i for i in orphan_ids if i not in _KNOWN_LEGACY_ORPHAN_IDS]
        if unexpected_orphans:
            print(f"ABORT: {len(unexpected_orphans)} rows have no matching event_log "
                  f"and are not part of the known legacy set: {unexpected_orphans}. "
                  "Resolve these manually before migrating (no data was changed).")
            conn.rollback()
            return

        if orphan_ids:
            print(f"Found {len(orphan_ids)} known legacy orphan rows "
                  "(pre-2026-03-17 TZ/counter-boundary bugs, already fixed). "
                  "Linking to a single placeholder event_log.")
            placeholders = ','.join('?' * len(orphan_ids))
            earliest_created_at = cur.execute(
                f"SELECT MIN(created_at) FROM processing_logs WHERE id IN ({placeholders})",
                orphan_ids
            ).fetchone()[0]

            cur.execute(
                "INSERT INTO event_logs (category, button_text, timestamp, current_number, staff_count) "
                "VALUES (NULL, ?, ?, NULL, NULL)",
                (_DUMMY_EVENT_LOG_BUTTON_TEXT, earliest_created_at)
            )
            dummy_event_log_id = cur.lastrowid

            cur.execute(
                f"UPDATE processing_logs SET event_log_id = ? WHERE id IN ({placeholders})",
                [dummy_event_log_id] + orphan_ids
            )

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
