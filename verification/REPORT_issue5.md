# /display_data キャッシュ機構 修正レポート (issue #5)

**日付**: 2026-07-20
**ブランチ**: `fix/db-error-http-status`
**対象Issue**: #5(Memuro-Town/MADO-queue)
**修正対象**: `app.py`

---

## 1. 概要

`/display_data` がDBエラー時に空の待ち行列(`calling: [], waiting_count: 0`)をHTTP 200で返していた問題に対し、直前の正常値をキャッシュして返す方式に変更した。

あわせて、キャッシュ導入の副作用として、来庁者モニターの呼出しチャイムがDBの一時的な障害直後に鳴らなくなる懸念(memuro-oss さんご指摘)についても、同じ変更で解消されることを検証した。

## 2. 修正内容

`app.py` の `/display_data`:

- モジュールレベル変数 `_display_data_cache` を導入(初期値 `{'calling': [], 'waiting_count': 0}`)
- DB取得成功時: `_display_data_cache` を更新してから返す
- DB取得失敗時: `_display_data_cache`(直前の正常値)をそのままHTTP 200で返す

**設計判断**

- 来庁者向けモニターは表示継続性をステータスコードの正確さより優先する
- 障害は `except` 内の `print` ログに残す。職員・管理側の検知手段は今回のスコープ外(必要なら別issue)
- 単一プロセス(Flask開発サーバー)運用を前提。gunicorn等の複数ワーカー構成では別途対応が必要

**対象外**: `/start_processing`, `/end_processing`, `/cancel_processing`, `/delete_ticket` のHTTP 500化はissue #4として別ブランチ(`fix/db-error-http-500-only`)で対応済み・PR提出済み。

## 3. 動作確認結果

**検証スクリプト**: `verification/test_display_data_cache.py`
**テスト手法**: `init_db.py` でスキーマ作成した一時DBに対し、Flask テストクライアントを使用。`get_db` を一時的に例外送出版に差し替えることでDB障害を模擬(永続的な障害ではなく、任意のタイミングで発生・復旧を再現できる方式)。

| Phase | テストケース | 期待値 | 結果 |
|-------|-------------|--------|------|
| 1 | 起動直後(キャッシュ未取得)のDBエラー | 200 + 空の初期値 | PASS |
| 2-a | 正常時(呼出し番号1件) | 200 + 実データ | PASS |
| 2-b | 正常取得後のDBエラー | 200 + 直前の正常値と完全一致 | PASS |
| 3 | エラー直後に新規呼出し(番号2)が発生 | 200 + [1, 2] が正しく反映 | PASS |
| 3-補足 | 差分が新規追加のみ(既存分の消失なし) | 差分 = {2} のみ | PASS |

**全5テスト通過**(ローカル環境で実行確認済み)。あわせて `fix/db-error-http-500-only` ブランチの4ルート500化テスト(全7テスト)も再確認し、PASSを維持していることを確認。

**修正**: `test_display_data_cache.py` で `sys` をファイル先頭でimportし、`sys.path` にプロジェクトルートを追加(`init_db.py` が `config` をimportするため必要)。

## 4. ファイル一覧

| ファイル | 変更種別 |
|---------|---------|
| `app.py` | 修正(`/display_data` にキャッシュ機構追加) |
| `verification/test_display_data_cache.py` | 新規作成(検証スクリプト) |
| `verification/ISSUE5_REPLY_DRAFT.md` | 新規作成(issue #5への返信ドラフト) |
