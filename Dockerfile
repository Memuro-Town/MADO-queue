# Python公式イメージの更新時はバージョンとdigestを一緒に更新する。
ARG PYTHON_IMAGE=python:3.14.10-slim-trixie@sha256:3cabfd7d7aaf394e6040e79fa1eec6ca1c52b74ed9188650472695d9a9326999
FROM ${PYTHON_IMAGE} AS builder
WORKDIR /build
COPY requirements-docker.lock .
RUN python -m pip install --require-hashes --only-binary=:all: \
    --no-cache-dir --no-compile --target=/install -r requirements-docker.lock

FROM ${PYTHON_IMAGE} AS runtime
RUN apt-get update -o APT::Update::Error-Mode=any \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes pip
COPY --from=builder /install /usr/local/lib/python3.14/site-packages
RUN groupadd --gid 10001 queue \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin queue \
    && mkdir -p /data \
    && chown 10001:10001 /data \
    && chmod 0750 /data
# 実行時に必要のないSUID/SGIDを除去する。失敗はビルド失敗として扱う。
RUN find /usr/bin /usr/sbin /usr/local/bin /usr/local/sbin -xdev -type f \
    \( -perm -4000 -o -perm -2000 \) -exec chmod a-s {} +
WORKDIR /app
COPY --chown=0:0 app.py config.py init_db.py printer.py safe_migrate_db.py entrypoint.sh ./
COPY --chown=0:0 templates/ ./templates/
COPY --chown=0:0 static/ ./static/
RUN chmod 0755 /app/entrypoint.sh
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/numbers.db \
    TZ=Asia/Tokyo
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
