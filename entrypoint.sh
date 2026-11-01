#!/bin/sh
set -eu

: "${DB_PATH:=/data/numbers.db}"
export DB_PATH
db_dir=$(dirname "$DB_PATH")
if [ ! -d "$db_dir" ] || [ ! -w "$db_dir" ] || [ ! -x "$db_dir" ]; then
    echo "[entrypoint] DB directory must exist and be writable: $db_dir (see docs/DOCKER.md)" >&2
    exit 1
fi
if [ -e "$DB_PATH" ] && { [ ! -f "$DB_PATH" ] || [ ! -r "$DB_PATH" ] || [ ! -w "$DB_PATH" ]; }; then
    echo "[entrypoint] DB_PATH must be a readable, writable file: $DB_PATH" >&2
    exit 1
fi

# DB が存在しない場合のみ初期化する
if [ ! -f "$DB_PATH" ]; then
    echo "[entrypoint] Initializing database..."
    python init_db.py
fi

echo "[entrypoint] Starting MADO-Queue on :8000"
exec python -m waitress --host=0.0.0.0 --port=8000 app:app
