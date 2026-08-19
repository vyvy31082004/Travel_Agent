#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

ACR_LOGIN_SERVER="$(az acr show --name "${AZURE_ACR_NAME}" --query loginServer -o tsv)"
ACR_USERNAME="$(az acr credential show --name "${AZURE_ACR_NAME}" --query username -o tsv)"
ACR_PASSWORD="$(az acr credential show --name "${AZURE_ACR_NAME}" --query 'passwords[0].value' -o tsv)"

COMMON_ARGS=(
  --name "${BACKFILL_JOB_NAME}"
  --resource-group "${AZURE_RESOURCE_GROUP}"
  --environment "${AZURE_CONTAINERAPPS_ENV}"
  --image "${IMAGE}"
  --registry-server "${ACR_LOGIN_SERVER}"
  --registry-username "${ACR_USERNAME}"
  --registry-password "${ACR_PASSWORD}"
  --trigger-type Manual
  --parallelism 1
  --replica-completion-count 1
  --replica-timeout 3600
  --replica-retry-limit 1
  --cpu 1.0
  --memory 2.0Gi
  --command "python"
  --args "src/memory_worker.py" "--backfill-embeddings"
  --secrets
    database-url="${DATABASE_URL}"
    cookie-secret="${COOKIE_SECRET}"
    google-api-key="${GOOGLE_API_KEY}"
  --env-vars
    DATABASE_URL=secretref:database-url
    COOKIE_SECRET=secretref:cookie-secret
    GOOGLE_API_KEY=secretref:google-api-key
    LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED=true
)

if az containerapp job show --name "${BACKFILL_JOB_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  az containerapp job update "${COMMON_ARGS[@]}"
else
  az containerapp job create "${COMMON_ARGS[@]}"
fi
