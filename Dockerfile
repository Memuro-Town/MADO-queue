FROM python:3.14-slim

WORKDIR /app

# pyusb が必要とする libusb をインストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    libusb-1.0-0 \
 && rm -rf /var/lib/apt/lists/*

# 依存ライブラリをインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションをコピー
COPY . .

RUN chmod +x entrypoint.sh

# DB 永続化ボリューム
VOLUME ["/data"]

# DB パスを環境変数で渡す（entrypoint.sh でも参照）
ENV DB_PATH=/data/numbers.db
ENV TZ=Asia/Tokyo

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
