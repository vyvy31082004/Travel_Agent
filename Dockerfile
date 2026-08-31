FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=5000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        chromium \
        chromium-driver \
        curl \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.production.txt ./
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.production.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY scripts ./scripts

RUN chmod +x /app/scripts/start-web-with-mcp-wait.sh \
        /app/scripts/run-memory-worker-once.sh \
        /app/scripts/run-memory-embedding-backfill.sh

EXPOSE 5000

CMD ["/app/scripts/start-web-with-mcp-wait.sh"]
