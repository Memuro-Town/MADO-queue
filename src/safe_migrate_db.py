import sqlite3
import os

# app.py / init_db.py と同じく DB_PATH 環境変数を優先する（Docker では /data/numbers.db）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
db_path  = os.environ.get('DB_PATH', os.path.join(PROJECT_ROOT, 'numbers.db'))

def safe_migrate():
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # processing_logs のカラム追加
        cursor.execute("PRAGMA table_info(processing_logs)")
        columns_info = cursor.fetchall()
        existing_columns = [info[1] for info in columns_info]
        print(f"processing_logs existing columns: {existing_columns}")

        new_columns = {
            'category': 'TEXT',
            'button_text': 'TEXT',
            'start_time': 'TEXT',
            'end_time': 'TEXT',
            'status': 'TEXT'
        }

        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                print(f"Adding column: {col_name} ({col_type})")
                cursor.execute(f"ALTER TABLE processing_logs ADD COLUMN {col_name} {col_type}")
            else:
                print(f"Column {col_name} already exists.")

        # event_logs のカラム追加
        cursor.execute("PRAGMA table_info(event_logs)")
        event_columns = [info[1] for info in cursor.fetchall()]
        print(f"event_logs existing columns: {event_columns}")

        if 'staff_count' not in event_columns:
            print("Adding column: staff_count (INTEGER) to event_logs")
            cursor.execute("ALTER TABLE event_logs ADD COLUMN staff_count INTEGER")
        else:
            print("Column staff_count already exists in event_logs.")

        # processing_logs に staff_count 追加
        cursor.execute("PRAGMA table_info(processing_logs)")
        pl_columns = [info[1] for info in cursor.fetchall()]
        print(f"processing_logs columns after earlier migration: {pl_columns}")

        if 'staff_count' not in pl_columns:
            print("Adding column: staff_count (INTEGER) to processing_logs")
            cursor.execute("ALTER TABLE processing_logs ADD COLUMN staff_count INTEGER")
        else:
            print("Column staff_count already exists in processing_logs.")

        # event_log_id チェック前に最新のカラム一覧を再取得
        cursor.execute("PRAGMA table_info(processing_logs)")
        pl_columns = [info[1] for info in cursor.fetchall()]

        if 'event_log_id' not in pl_columns:
            print("Adding column: event_log_id (INTEGER) to processing_logs")
            cursor.execute("ALTER TABLE processing_logs ADD COLUMN event_log_id INTEGER")
        else:
            print("Column event_log_id already exists in processing_logs.")

        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Migration error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    safe_migrate()
