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

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY scripts ./scripts
COPY docs ./docs

RUN chmod +x /app/scripts/start-web-with-mcp-wait.sh

EXPOSE 5000

CMD ["/app/scripts/start-web-with-mcp-wait.sh"]
