# カテゴリごとの番号開始値。
# 番号帯でカテゴリを視覚的に区別する: A=001-499, B=500-799, C=800-999
# 上限 CATEGORY_MAX を超えたら開始番号へラップする（Issue #9）。
# 開始値は帯の上限に対して余裕を取ること（日内で帯を使い切ると表示番号が重複しうる）。
# init_db.py と app.py の両方がここからインポートする（二重定義を防ぐ）。
CATEGORY_START = {
    'A': 1,
    'B': 500,
    'C': 800,
    'D': 0,   # D は印刷なし・窓口外来庁者カウント用
}

# カテゴリ別の上限。超過時は CATEGORY_START[category] へ戻す。
# フォークして利用する自治体は、窓口構成と想定発券数に合わせて開始値・上限を調整する。
# A/B/C の番号帯は重ねないこと。桁数を増やす場合は券面・各画面の表示も確認する。
CATEGORY_MAX = {'A': 499, 'B': 799, 'C': 999, 'D': 999}

# Issue #20 で合意した SQLite PRAGMA の標準値。
# cache_size は低スペック環境向けの初期値（実機テストで調整可能）。
_SQLITE_PRAGMAS = (
    'PRAGMA journal_mode = WAL',
    'PRAGMA synchronous = NORMAL',
    'PRAGMA cache_size = -8192',
    'PRAGMA temp_store = DEFAULT',
    'PRAGMA busy_timeout = 5000',
)


def configure_sqlite_connection(conn, *, foreign_keys=True):
    """SQLite 接続ごとに PRAGMA を設定する。app / init_db / safe_migrate_db で共有。"""
    for pragma in _SQLITE_PRAGMAS:
        conn.execute(pragma)
    if foreign_keys:
        conn.execute('PRAGMA foreign_keys = ON')
