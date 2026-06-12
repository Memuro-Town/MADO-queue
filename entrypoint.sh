#!/bin/sh
set -e

# DB が存在しない場合のみ初期化する
if [ ! -f /data/numbers.db ]; then
    echo "[entrypoint] Initializing database..."
    DB_PATH=/data/numbers.db python init_db.py
fi

echo "[entrypoint] Starting MADO-Queue on :8000"
exec waitress-serve --host=0.0.0.0 --port=8000 app:app
