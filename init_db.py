"""
DB 初期化スクリプト。初回セットアップ時に一度だけ実行する。
既存テーブル・データには影響しない (CREATE TABLE IF NOT EXISTS / INSERT OR IGNORE)。
"""

import os
import sqlite3

from config import CATEGORY_START

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path  = os.environ.get('DB_PATH', os.path.join(BASE_DIR, 'numbers.db'))

conn   = sqlite3.connect(db_path)
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
    ticket_number   INTEGER  NOT NULL,
    category        CHAR(1),
    button_text     TEXT,
    start_time      TEXT,
    end_time        TEXT,
    wait_time       INTEGER,
    status          TEXT     NOT NULL,
    processing_time INTEGER,
    created_at      TEXT     NOT NULL,
    staff_count     INTEGER,
    event_log_id    INTEGER
)
''')

# 各カテゴリの初期行を挿入（既存行はスキップ）
cursor.executemany(
    'INSERT OR IGNORE INTO numbers (category, current_number) VALUES (?, ?)',
    list(CATEGORY_START.items())
)

conn.commit()
conn.close()
print(f"DB initialized: {db_path}")
