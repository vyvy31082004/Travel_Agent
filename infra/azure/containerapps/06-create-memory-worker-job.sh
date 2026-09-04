#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

ACR_LOGIN_SERVER="$(az acr show --name "${AZURE_ACR_NAME}" --query loginServer -o tsv)"
ACR_USERNAME="$(az acr credential show --name "${AZURE_ACR_NAME}" --query username -o tsv)"
ACR_PASSWORD="$(az acr credential show --name "${AZURE_ACR_NAME}" --query 'passwords[0].value' -o tsv)"

COMMON_ARGS=(
  --name "${MEMORY_WORKER_JOB_NAME}"
  --resource-group "${AZURE_RESOURCE_GROUP}"
  --environment "${AZURE_CONTAINERAPPS_ENV}"
  --image "${IMAGE}"
  --registry-server "${ACR_LOGIN_SERVER}"
  --registry-username "${ACR_USERNAME}"
  --registry-password "${ACR_PASSWORD}"
  --trigger-type Schedule
  --cron-expression "${WORKER_CRON_EXPRESSION}"
  --parallelism 1
  --replica-completion-count 1
  --replica-timeout 1800
  --replica-retry-limit 1
  --cpu 1.0
  --memory 2.0Gi
  --command "scripts/run-memory-worker-once.sh"
  --secrets
    database-url="${DATABASE_URL}"
    cookie-secret="${COOKIE_SECRET}"
    google-api-key="${GOOGLE_API_KEY}"
    rapidapi-key="${RAPIDAPI_KEY}"
    weather-api-key="${WEATHER_API_KEY}"
  --env-vars
    DATABASE_URL=secretref:database-url
    COOKIE_SECRET=secretref:cookie-secret
    GOOGLE_API_KEY=secretref:google-api-key
    RAPIDAPI_KEY=secretref:rapidapi-key
    WEATHER_API_KEY=secretref:weather-api-key
    LONG_TERM_MEMORY_EXTRACTOR="${LONG_TERM_MEMORY_EXTRACTOR}"
    LONG_TERM_MEMORY_LANGMEM_MODEL="${LONG_TERM_MEMORY_LANGMEM_MODEL:-gemini-3.6-flash}"
    LONG_TERM_MEMORY_VERIFIER="${LONG_TERM_MEMORY_VERIFIER}"
    LONG_TERM_MEMORY_TRUSTMEM_MODEL="${LONG_TERM_MEMORY_TRUSTMEM_MODEL:-gemini-2.5-flash}"
    LONG_TERM_MEMORY_TRUSTMEM_PROMPT_VERSION="${LONG_TERM_MEMORY_TRUSTMEM_PROMPT_VERSION:-trustmem-verifier-v2}"
    LONG_TERM_MEMORY_TRUSTMEM_TIMEOUT_SECONDS="${LONG_TERM_MEMORY_TRUSTMEM_TIMEOUT_SECONDS:-30}"
    LONG_TERM_MEMORY_TRUSTMEM_COVERAGE_THRESHOLD="${LONG_TERM_MEMORY_TRUSTMEM_COVERAGE_THRESHOLD:-0.80}"
    LONG_TERM_MEMORY_TRUSTMEM_PRESERVATION_THRESHOLD="${LONG_TERM_MEMORY_TRUSTMEM_PRESERVATION_THRESHOLD:-0.90}"
    LONG_TERM_MEMORY_TRUSTMEM_FAITHFULNESS_THRESHOLD="${LONG_TERM_MEMORY_TRUSTMEM_FAITHFULNESS_THRESHOLD:-0.95}"
    LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED="${LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED}"
    LONG_TERM_MEMORY_EMBEDDING_MODEL="${LONG_TERM_MEMORY_EMBEDDING_MODEL:-models/gemini-embedding-001}"
    LONG_TERM_MEMORY_VECTOR_DIMS="${LONG_TERM_MEMORY_VECTOR_DIMS:-3072}"
    LONG_TERM_MEMORY_TRANSITION_PATH="${LONG_TERM_MEMORY_TRANSITION_PATH:-llm}"
    LONG_TERM_MEMORY_TRANSITION_MODEL="${LONG_TERM_MEMORY_TRANSITION_MODEL:-gemini-2.5-flash}"
    LONG_TERM_MEMORY_TRANSITION_CONFIDENCE_THRESHOLD="${LONG_TERM_MEMORY_TRANSITION_CONFIDENCE_THRESHOLD:-0.85}"
    LONG_TERM_MEMORY_TRANSITION_BATCH_SIZE="${LONG_TERM_MEMORY_TRANSITION_BATCH_SIZE:-10}"
    LONG_TERM_MEMORY_DOMAIN_CANDIDATE_LIMIT="${LONG_TERM_MEMORY_DOMAIN_CANDIDATE_LIMIT:-50}"
    LONG_TERM_MEMORY_ACTION_INFERENCE_ENABLED="${LONG_TERM_MEMORY_ACTION_INFERENCE_ENABLED:-false}"
    LONG_TERM_MEMORY_APPLICABILITY_JUDGE_ENABLED="${LONG_TERM_MEMORY_APPLICABILITY_JUDGE_ENABLED:-true}"
    LONG_TERM_MEMORY_APPLICABILITY_BATCH_SIZE="${LONG_TERM_MEMORY_APPLICABILITY_BATCH_SIZE:-10}"
    RAPIDAPI_LOCK_FILE=/tmp/viettrip-rapidapi.lock
)

if az containerapp job show --name "${MEMORY_WORKER_JOB_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  # The preview CLI does not accept the full job definition on `job update`
  # (notably environment, registry credentials, secrets, and trigger options).
  # Recreate this scheduled job so its command and secret references are atomic.
  echo "Recreating ${MEMORY_WORKER_JOB_NAME} with the current definition"
  az containerapp job delete \
    --name "${MEMORY_WORKER_JOB_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --yes
fi

# Prevent Git Bash/MSYS from rewriting the Linux lock path in --env-vars.
MSYS_NO_PATHCONV=1 az containerapp job create "${COMMON_ARGS[@]}"
