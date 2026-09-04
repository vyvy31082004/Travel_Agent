#!/usr/bin/env bash
set -euo pipefail

exec python /app/src/memory_worker.py --backfill-embeddings
