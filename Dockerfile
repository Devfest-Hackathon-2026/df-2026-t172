# Cloud Run 用。API と画面（frontend/）を1つのコンテナで配信する。
# 最大1インスタンスの前提（1日の呼び出し回数をメモリで数えるため）。デプロイ時に --max-instances=1 を付ける。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    MODE=live \
    FRONTEND_DIR=/srv/frontend

# 受け取った音声（webm/opus・mp4/AAC・m4a）を FLAC に直して認識にかけるため（app/live/audio_flac.py）
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/mock ./mock
COPY backend/seed ./seed
COPY frontend /srv/frontend

# root で動かさない
RUN useradd --create-home appuser
USER appuser

# PASSCODE は Secret Manager から環境変数で渡す（イメージに入れない）。PORT は Cloud Run が渡す
CMD exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port ${PORT:-8080}
