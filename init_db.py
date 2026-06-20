"""
DB 初期化スクリプト。初回セットアップ時に一度だけ実行する。
既存テーブル・データには影響しない (CREATE TABLE IF NOT EXISTS / INSERT OR IGNORE)。

設計方針:
  - チケットの安定キーは event_logs.id（発券）と processing_logs.id（処理）。
    呼び出し・完了・キャンセルはこれらの id で操作し、表示番号（毎日リセット）に依存しない。
  - processing_logs.event_log_id は event_logs.id への外部キー（NOT NULL）。
  - status は CHECK 制約で processing / completed / deleted に限定する。
既存DBを新スキーマへ移行する場合は safe_migrate_db.py を使う。
"""

import os
import sqlite3

from config import CATEGORY_START

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path  = os.environ.get('DB_PATH', os.path.join(BASE_DIR, 'numbers.db'))

conn   = sqlite3.connect(db_path)
conn.execute('PRAGMA foreign_keys = ON')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS numbers (
    category       CHAR(1)  PRIMARY KEY,
    current_number INTEGER  NOT NULL,
    timestamp      DATE
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS event_logs (
    id             INTEGER  PRIMARY KEY AUTOINCREMENT,
    category       CHAR(1)  NOT NULL,
    button_text    TEXT,
    timestamp      TEXT     NOT NULL,
    current_number INTEGER  NOT NULL,
    staff_count    INTEGER
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS processing_logs (
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
''')

# 頻出クエリ（event_log_id での結合・status での絞り込み）用のインデックス
cursor.execute('CREATE INDEX IF NOT EXISTS idx_pl_event_log_id ON processing_logs(event_log_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_pl_status       ON processing_logs(status)')

# 各カテゴリの初期行を挿入（既存行はスキップ）
cursor.executemany(
    'INSERT OR IGNORE INTO numbers (category, current_number) VALUES (?, ?)',
    list(CATEGORY_START.items())
)

conn.commit()
conn.close()
print(f"DB initialized: {db_path}")
