#!/usr/bin/env bash
set -euo pipefail

python /app/scripts/wait_for_mcp.py
exec uvicorn app:app --app-dir src --host 0.0.0.0 --port "${PORT:-5000}"
