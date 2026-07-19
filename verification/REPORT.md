# DB エラー時 HTTP 500 化修正レポート

**日付**: 2026-07-20
**ブランチ**: `fix/db-error-http-500-only`
**対象PR**: #5
**修正対象**: `app.py` (4ルート)

---

## 1. 概要

DB エラー発生時に HTTP 200 でレスポンスを返していた4ルートを、HTTP 500 を返すよう修正した。

**修正対象外**: `/display_data` は別ブランチ (`fix/db-error-http-status`) でキャッシュ機構を導入する方針。

## 2. 修正内容

各ルートの `except` ブロックの `return jsonify({...})` に第二引数 `500` を追加。

| ルート | 修正箇所 |
|--------|---------|
| `/start_processing` | L329 |
| `/end_processing` | L378 |
| `/cancel_processing` | L410 |
| `/delete_ticket` | L449 |

`/get_next_number` は既に HTTP 500 を返していたため修正不要。

## 3. 動作確認結果

**テスト手法**: Flask テストクライアント使用。`DB_PATH` を存在しないディレクトリに設定し `sqlite3.OperationalError` を発火。

| テストケース | 期待値 | 実測値 | 結果 |
|-------------|--------|--------|------|
| `/get_next_number` (入力エラー) | 400 | 400 | PASS |
| `/get_next_number` (DB エラー) | 500 | 500 | PASS |
| `/start_processing` (DB エラー) | 500 | 500 | PASS |
| `/end_processing` (DB エラー) | 500 | 500 | PASS |
| `/cancel_processing` (DB エラー) | 500 | 500 | PASS |
| `/delete_ticket` (DB エラー) | 500 | 500 | PASS |
| `/display_data` (DB エラー, 変更なし) | 200 | 200 | PASS |

**全7テスト通過**

## 4. ファイル一覧

| ファイル | 変更種別 |
|---------|---------|
| `app.py` | 修正 (4箇所) |
| `verification/test_db_error_status.py` | 修正 (500化ルートのみテスト) |
