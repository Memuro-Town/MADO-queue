"""
python src / python src.pyz 用の実行エントリーポイント。
"""

import os

import init_db
from app import app


def main() -> None:
    # DB 初期化は init_db の import 時副作用として実行する。
    _ = init_db

    from waitress import serve

    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '8000'))
    serve(app, host=host, port=port)


if __name__ == '__main__':
    main()
