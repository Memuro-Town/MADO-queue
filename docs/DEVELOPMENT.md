# MADO queue — Development & Testing

> ローカルでビルド・起動・テストするための手順。実装の詳細は [ARCHITECTURE.md](ARCHITECTURE.md)、業務要件は [REQUIREMENTS.md](REQUIREMENTS.md) を参照。

---

## 1. 前提

- **Docker**（Docker Desktop もしくは WSL/Linux 上のネイティブ Docker Engine）
- もしくは Python 3.14 + 依存パッケージ（Docker を使わない場合）

プリンターは**接続していなくてもテスト可能**。印刷は失敗するが例外を握りつぶす設計のため、発券・採番・DB記録は成功する（ログに `[print_ticket] error: ...` が出るのは想定内）。

---

## 2. Docker で起動（推奨）

```bash
docker compose up          # フォアグラウンド起動（ログが流れる）
```

起動後、ブラウザで **http://localhost:8000** を開く。

> **WSL（Windows）の場合:** 必ず上記のように `-d` を付けずフォアグラウンドで起動し、ターミナルを開いたままにすること。`localhost` で繋がらない場合は本書末尾の **「7. WSL（Windows）でハマりやすい点」** を参照。

- 初回起動時に `entrypoint.sh` が DB を自動初期化し、`data/numbers.db` を生成する
- 止めるときは起動中のターミナルで **Ctrl+C**
- コード変更を反映して再ビルド：`docker compose up --build`

### 画面

| URL | 画面 | 利用者 |
|-----|------|--------|
| http://localhost:8000/ | 発券画面 | 来庁者（タブレット） |
| http://localhost:8000/processing | 処理管理画面 | 窓口職員（PC） |
| http://localhost:8000/display | 公開表示画面 | 待合エリア（大型モニター） |

### 動作確認（HTTP）

```bash
# トップページ
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/      # → 200

# 番号を発券
curl -s -X POST http://localhost:8000/get_next_number \
  -H "Content-Type: application/json" \
  -d '{"category":"A","buttonText":"住民票","timestamp":"2026-06-11T09:00:00+09:00"}'
# → {"category":"A","next_number":1}

# 表示画面用データ
curl -s http://localhost:8000/display_data
# → {"calling":[...],"waiting_count":N}
```

---

## 3. ローカルで起動（Docker を使わない場合）

```bash
pip install -r requirements.txt
python init_db.py                                                   # 初回のみ（DB初期化）
TZ=Asia/Tokyo python app.py                                         # 開発サーバー
TZ=Asia/Tokyo waitress-serve --host=0.0.0.0 --port=8000 app:app     # 本番相当（Waitress）
```

> Windows でレシートプリンターを使う場合は `pip install pywin32` も必要（`requirements.txt` には含まない）。

---

## 4. テスト

```bash
python -m unittest test_app -v
```

テストは `print_ticket` をスタブ化しているため、プリンター・印刷の有無に依存しない。

---

## 5. DB のリセット

`data/numbers.db` をまっさらに戻したいとき：

```bash
docker compose down
rm data/numbers.db        # Windows の場合は data\numbers.db を削除
docker compose up         # 次回起動時に再初期化される
```

`data/` はホスト側にマウントされ永続化されるので、バックアップはこのファイルをコピーするだけ。

---

## 6. プリンター設定（任意）

USB 接続の ESC/POS レシートプリンターを使う場合、機種に応じて環境変数で指定する。

| 環境変数 | 既定値 | 説明 |
|---------|-------|------|
| `PRINTER_NAME` | `POS-80C (copy 1)` | Windows で使うプリンター名 |
| `PRINTER_VID` | `0x04b8` | USBベンダーID（Linux/pyusb で使用） |
| `PRINTER_PID` | `0x0e20` | USBプロダクトID（Linux/pyusb で使用） |

Docker（Linux）で実機プリンターに印刷するには、`docker-compose.yml` の `devices: /dev/bus/usb:/dev/bus/usb` のコメントを外す。WSL の場合は別途 `usbipd-win` で USB を WSL にアタッチする必要がある（UI・採番のテストだけなら不要）。

---

## 7. WSL（Windows）でハマりやすい点

Windows 上で **WSL 内のネイティブ Docker**（Docker Desktop ではない構成）を使う場合の注意。

### 7.1 `-d`（デタッチ）で起動すると、放置でコンテナごと止まる

WSL ディストロは、開いているセッションやプロセスが無くなるとアイドルで自動停止する。`docker compose up -d` はコマンドが即終了してセッションが閉じるため、しばらくするとディストロごと落ち、ブラウザから `ERR_CONNECTION_TIMED_OUT` になる。

**対策:** テスト中は `-d` を付けず、**フォアグラウンドで `docker compose up` を実行し、そのターミナルを開いたままにする**。

### 7.2 `localhost:8000` に繋がらないとき

ディストロが生きていれば WSL2 のポート転送が効き、Windows のブラウザから `localhost:8000` で到達できる。繋がらない場合は：

1. まず 7.1 のとおりフォアグラウンド起動でディストロを生かす
2. それでもダメなら WSL の IP で直接開く：
   ```bash
   wsl hostname -I        # 先頭のIP。例: 172.27.70.54 → http://172.27.70.54:8000
   ```
   ※ WSL の IP は再起動で変わる
3. 恒久的に `localhost` を使いたいなら **Docker Desktop（WSL2インテグレーション有効）** に切り替えるのが最も確実（公開ポートが自動で Windows の localhost に転送される）

> Windows 11 なら `.wslconfig` の `networkingMode=mirrored` で `localhost` を完全に共有できるが、**Windows 10 では非対応**。

### 7.3 改行コード（CRLF）

`entrypoint.sh` などのシェルスクリプトが CRLF 改行だと、コンテナ起動時に `not found` 等で失敗する。**LF を維持**すること（リポジトリの `.gitattributes` / エディタ設定で `*.sh` を LF に固定するのが安全）。
