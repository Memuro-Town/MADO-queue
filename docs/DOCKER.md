# Docker版の起動・更新

Docker版は一般ユーザー（既定UID/GID `10001:10001`）で動作する。
Docker Compose v2を使用し、`docker compose config --quiet`が通ることを確認する。
Docker Engine / Desktop本体は、各PCでサポート中の安定版へ更新する。

## 初回起動

保存先`data`を事前に作成する。Composeがroot所有で自動作成することはない。
Linux / WSLのLinuxファイルシステム上では次を実行する。

```sh
sudo install -d -m 0750 -o 10001 -g 10001 ./data
docker compose config --quiet
docker compose up -d --build
```

WindowsのDocker Desktopでは、PowerShellで
`New-Item -ItemType Directory -Force data`を実行する。
共有フォルダーの権限設定を使うため、Linuxの`chown`をそのまま適用しない。
Windows側の共有許可を確認し、下記の書き込み確認後に起動する。
Windows / Docker Desktopでの実機確認はリリース時の検証結果を参照する。

```sh
docker compose build --pull
docker compose run --rm --no-deps --entrypoint python queue -c 'import tempfile; f=tempfile.TemporaryFile(dir="/data"); f.write(b"check"); f.close(); print("data directory writable")'
docker compose up -d
```

シェルに合わせて引用符を調整する。失敗時はroot起動や`chmod 777`で回避せず、
共有フォルダーの権限を確認する。`QUEUE_UID`・`QUEUE_GID`で非0の実行ユーザーを
指定することもできる。保存先の所有者も合わせ、再起動後も同じ設定を使用する。

`http://localhost:8000`で画面を開く。同じ受付LANからはホストのIPで接続する。
待受アドレスは既定で`0.0.0.0`。`QUEUE_BIND_ADDRESS`で受付LANのIPに限定できる。
ホストのファイアウォールで接続元を受付LANに限定し、インターネットへ直接公開しない。

## 既存DBからの更新

1. 旧イメージを別タグで保存し、旧ソース・Compose・実行ユーザー設定を控える。
2. `docker compose stop queue`で停止する。停止中に`data`全体を別の場所へコピーし、DBとjournal等を一緒に保全する。稼働中のDBファイルだけをコピーしない。
3. Linuxでは`ls -ld data`、`ls -l data`で所有者と実体を確認する。絶対パスが対象の`data`であることを確認する。symlinkや外部保存先がある場合は個別に確認する。
4. `data`とDB・存在するsidecar（`numbers.db-wal` / `numbers.db-shm` / `numbers.db-journal`）だけを実行ユーザーの所有へ変更する。再帰的に変更しない。既定値のディレクトリとDBは次のとおり。

```sh
sudo chown --no-dereference 10001:10001 ./data ./data/numbers.db
sudo chmod 0750 ./data
sudo chmod 0600 ./data/numbers.db
```

5. 書き込み確認、`docker compose build --pull`、`docker compose up -d --force-recreate`を実行する。
6. 発券・呼出・完了・表示、再起動後のデータ保持を確認する。

Windows共有フォルダーでは手順4の代わりに共有権限を確認する。
SQLiteはDBだけでなく親ディレクトリへの書き込み・検索権限も必要。
起動時に所有権を自動変更する処理や、DBスキーマの変更は行わない。

切り戻しでは停止後、旧イメージと旧Compose・ユーザー設定へ戻す。
更新後のデータがあれば先に別途保存する。更新前バックアップへ戻す場合は、
別の復元先にディレクトリ全体を展開し、整合性と所有者を確認してから切り替える。
既存DBへ直接上書き復元したり、`docker compose down -v`で復旧したりしない。

## USBプリンター（Linuxホスト）

USBは通常のComposeに含めず、`docker-compose.usb.yml.example`を重ねて設定する。
Windowsで通常起動する場合の既存の印刷処理は変更しない。

1. プリンターの`/dev/bus/usb/BBB/DDD`と、読み書きできるホスト側グループの数値GIDを調べる。
2. 管理者がVID/PIDを限定したudevルールでグループに`0660`相当の権限を与える。全USBへの権限付与や`privileged`は使わない。
3. 次の設定で同じ`queue`サービスにデバイスと補助グループを追加する。

```sh
export QUEUE_USB_DEVICE=/dev/bus/usb/001/005  # 実機のパスに置換
export QUEUE_USB_GID=1234                    # 実際のグループGIDに置換
docker compose -f docker-compose.yml -f docker-compose.usb.yml.example config --quiet
docker compose -f docker-compose.yml -f docker-compose.usb.yml.example up -d
```

`PRINTER_VID`・`PRINTER_PID`も使用機種に合わせる。抜き差し後はパスが変わることがあるため、
再確認してコンテナを再作成する。設定の検証だけで印刷成功とはしない。
導入先で一般ユーザーのまま印刷できることを実機確認する。
WSL / Docker DesktopのUSB転送にはホスト側の準備も必要で、この設定だけでは接続されない。

## 依存関係の更新と検査

通常起動用`requirements.txt`とDocker専用`requirements-docker.lock`を分ける。
Docker側は推移的依存も固定し、wheelのSHA256を検証する。
pipはビルドにだけ使用し、実行用イメージには残さない。
SQLite・libusbを別環境の共有ライブラリで差し替えない。

ベースのバージョンとdigestを固定しているため、`--pull`だけでは次の修正版へ進まない。
定期更新時とセキュリティ通知時には次をセットで行う。

1. Python公式イメージの安定パッチ版とdigestを確認し、Dockerfileの`PYTHON_IMAGE`を更新する。
2. 対象PythonのLinux環境で`scripts/update_docker_lock.py`を実行し、配布元wheelのhashを含むDocker用lockを更新する。通常起動用の指定を無断で固定しない。
3. `docker compose build --pull --no-cache`でAPTの更新も取り込む。APT配信状態までは固定していないため、異なる日のバイナリ完全一致は保証しない。
4. Python、`sqlite3.sqlite_version`、libusb読み込みを確認し、OSとアプリ依存を検査する。Python本体の検査漏れを考慮し、公式修正情報も確認する。
5. 新規DBと既存DBの複製、APIと表示、データ保持、バックアップ復元を確認する。USBは実機で確認する。
6. イメージID・ソースcommit・検査DB日時・生JSONを保存する。比較には同じ検査DBを使用し、配布前は最新DBでも確認する。

修正版未配信のOS項目は、機能の存在・攻撃条件・緩和策・再確認条件を記録する。
「未使用らしい」だけで一律に無視したり、他イメージのVEXを流用したりしない。
報告・公開範囲は[SECURITY.md](../SECURITY.md)に従う。

依存固定ファイルの更新例（Linuxシェル、`BASE`はDockerfileの`PYTHON_IMAGE`と一致させる）。
このコマンドはホストユーザーでlockを更新し、本番DBにはアクセスしない。

```sh
BASE=python:3.14.10-slim-trixie@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  --mount "type=bind,src=$PWD,dst=/work" -w /work \
  "$BASE" python scripts/update_docker_lock.py
```

実行用イメージにはpipがないため、更新にはビルド用の公式Pythonイメージを使う。
hashは対応プラットフォームのwheelを含むが、別CPU/OSの動作確認を保証しない。
更新後は必ず再ビルドと回帰試験を行う。

## 検証の実行

イメージを作成してから、Linux / WSLで次を実行する。
本番DBやUSBを使わず、専用の一時コンテナ・ボリュームで検証する。

```sh
docker build --pull -t mado-queue:verify .
python3 verification/test_docker_runtime.py mado-queue:verify
node --test verification/test_display_chime.cjs
```

初期化・既存APIテスト・発券から完了・表示・再起動・SQLiteバックアップの復元・
書き込み権限の不足時に停止することを確認する。テスト用データは終了時に片付ける。
2026-11-01の実装検証はWSL2上のLinuxコンテナで実施した。
Windows Docker Desktopの共有フォルダー権限とUSB実機印刷は未検証。
他のCPUアーキテクチャや導入先の権限設定まで確認済みとは扱わない。
