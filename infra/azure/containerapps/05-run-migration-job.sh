#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required for local pgvector preflight before running migrations." >&2
  exit 1
fi

run_vector_preflight() {
  psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extname FROM pg_extension WHERE extname = 'vector';
SQL
}

if [[ "${MIGRATION_START_ONLY:-false}" == "true" ]]; then
  # stdout is a machine-readable contract in CI: emit only the execution name.
  # Send psql's CREATE/SELECT output to stderr so command substitution cannot
  # accidentally pass multiline SQL output as --job-execution-name.
  run_vector_preflight >&2
  az containerapp job start \
    --name "${MIGRATION_JOB_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --query name \
    --output tsv
else
  run_vector_preflight
  az containerapp job start \
    --name "${MIGRATION_JOB_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}"

  az containerapp job execution list \
    --name "${MIGRATION_JOB_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --output table
fi
