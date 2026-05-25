FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/pyproject.toml backend/README.md ./backend/
COPY backend/src ./backend/src
COPY backend/examples ./backend/examples

RUN pip install --upgrade pip \
    && pip install -r backend/requirements.txt yt-dlp \
    && pip install ./backend \
    && mkdir -p backend/artifacts

EXPOSE 8000

CMD ["ada-api", "--host", "0.0.0.0", "--port", "8000"]
