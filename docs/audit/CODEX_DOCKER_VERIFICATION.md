# Codex Cloud Docker 検証

日付: 2026-06-21 (UTC)
リポジトリ: `to4kawa/MADO-queue`
範囲: Codex Cloud 環境での実行可否確認のみ。Docker 実行可否の調査中に、リポジトリ内のファイルは変更していません。

## 概要

現時点では、このリポジトリの `docker build` や `docker compose up` の検証に Codex Cloud は使用できません。

前回のベースライン監査では、`docker` 実行ファイルが存在しないため Docker 検証不可としていました。今回の追加確認では、Docker CLI と `dockerd` バイナリ自体はインストールできることを確認しました。ただし、Codex Cloud の実行環境では Docker デーモンが必要とする低レベル操作が許可されていないため、Docker デーモンの起動は失敗します。

## 結果

- OS: Ubuntu 24.04.4 LTS (Noble Numbat)
- User: `root`
- `apt-get update`: 成功
- `apt-get install -y docker.io`: 成功
- `docker --version`: 成功
- `dockerd --version`: 成功
- `docker info`: 失敗
- `/var/run/docker.sock`: 利用不可
- `docker compose version`: 確認した環境では利用不可
- 調査中のリポジトリファイル変更: なし
- `git status --short`: 空

## 失敗モード

手動での `dockerd` 起動は、bridge network / iptables の初期化中に失敗しました。

代表的なエラー:

```text
failed to start daemon: Error initializing network controller:
error obtaining controller instance:
failed to register "bridge" driver:
failed to create NAT chain DOCKER:
iptables ... Permission denied
```

プロセスは `root` で実行されていたため、これは通常のユーザー権限不足ではありません。コンテナ capabilities、cgroups、iptables、network namespace、または関連するカーネルレベルの制限を含む、実行環境側の制約として扱います。

また、この環境では `/sys` と `/sys/fs/cgroup` が読み取り専用として見えていました。この状態は、Docker デーモンを起動できない環境であることと整合します。

## 分類

- Docker CLI: インストール可能
- `dockerd` バイナリ: インストール可能
- Docker デーモン: 使用不可
- Docker socket: 使用不可
- Docker Compose: この環境ではリポジトリ検証に使用不可
- `docker build` / `docker compose up`: このリポジトリでは Codex Cloud 上で実行不可

## MADO-queue 検証への影響

Codex Cloud では、以下の確認は完了できません。

- `docker build`
- `docker compose build`
- `docker compose up`
- コンテナ化されたサービスに対する HTTP smoke test
- コンテナ内でのタイムゾーン確認。例: `date`、Python `datetime.now()`、SQLite `localtime`

## Codex Cloud で引き続き確認できること

Codex Cloud では、Docker を使わない以下の確認は引き続き実施できます。

- Python unit tests
- `Dockerfile` の静的レビュー
- `docker-compose.yml` の静的レビュー
- タイムゾーン依存のアプリケーションコードレビュー
- Docker 外での Python / SQLite タイムゾーン挙動確認

## 推奨される後続確認

Docker の起動確認は、Docker デーモンを使用できる環境で再実行してください。例:

- ローカル開発環境
- Docker デーモンが有効な CI runner
- Docker socket mount が有効な環境
- privileged Docker-in-Docker 環境

Codex Cloud から Docker 関連の変更を提案する場合は、Docker build/start の検証は未実施であることを明記し、検証内容は静的レビューのみとして記録してください。
