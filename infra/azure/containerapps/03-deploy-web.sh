#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

TMP_YAML="$(mktemp)"
trap 'rm -f "${TMP_YAML}"' EXIT

ACR_LOGIN_SERVER="$(az acr show --name "${AZURE_ACR_NAME}" --query loginServer -o tsv)"
ACR_USERNAME="$(az acr credential show --name "${AZURE_ACR_NAME}" --query username -o tsv)"
ACR_PASSWORD="$(az acr credential show --name "${AZURE_ACR_NAME}" --query 'passwords[0].value' -o tsv)"

cat >"${TMP_YAML}" <<YAML
properties:
  configuration:
    activeRevisionsMode: Multiple
    ingress:
      external: true
      targetPort: 5000
      transport: auto
      allowInsecure: false
    registries:
      - server: ${ACR_LOGIN_SERVER}
        username: ${ACR_USERNAME}
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: "${ACR_PASSWORD}"
      - name: database-url
        value: "${DATABASE_URL}"
      - name: cookie-secret
        value: "${COOKIE_SECRET}"
      - name: google-api-key
        value: "${GOOGLE_API_KEY}"
      - name: rapidapi-key
        value: "${RAPIDAPI_KEY}"
      - name: weather-api-key
        value: "${WEATHER_API_KEY}"
      - name: langsmith-api-key
        value: "${LANGSMITH_API_KEY}"
  template:
    scale:
      minReplicas: ${WEB_MIN_REPLICAS}
      maxReplicas: ${WEB_MAX_REPLICAS}
    containers:
      - name: web
        image: ${IMAGE}
        command: ["/app/scripts/start-web-with-mcp-wait.sh"]
        resources:
          cpu: ${WEB_CPU}
          memory: ${WEB_MEMORY}
        env: &common_env
          - name: DATABASE_URL
            secretRef: database-url
          - name: COOKIE_SECRET
            secretRef: cookie-secret
          - name: GOOGLE_API_KEY
            secretRef: google-api-key
          - name: RAPIDAPI_KEY
            secretRef: rapidapi-key
          - name: WEATHER_API_KEY
            secretRef: weather-api-key
          - name: LANGSMITH_API_KEY
            secretRef: langsmith-api-key
          - name: COOKIE_SECURE
            value: "${COOKIE_SECURE}"
          - name: BOOKING_RAPIDAPI_HOST
            value: "${BOOKING_RAPIDAPI_HOST}"
          - name: GEOCODING_RAPIDAPI_HOST
            value: "${GEOCODING_RAPIDAPI_HOST}"
          - name: GOOGLE_FLIGHT_RAPIDAPI_HOST
            value: "${GOOGLE_FLIGHT_RAPIDAPI_HOST}"
          - name: BOOKING_LANGUAGE_CODE
            value: "${BOOKING_LANGUAGE_CODE}"
          - name: BOOKING_CURRENCY_CODE
            value: "${BOOKING_CURRENCY_CODE}"
          - name: COUNTRY_CODE
            value: "${COUNTRY_CODE}"
          - name: LONG_TERM_MEMORY_RECALL_ENABLED
            value: "${LONG_TERM_MEMORY_RECALL_ENABLED}"
          - name: LONG_TERM_MEMORY_WRITE_ENABLED
            value: "${LONG_TERM_MEMORY_WRITE_ENABLED}"
          - name: LONG_TERM_MEMORY_SYNC_FINALIZE
            value: "${LONG_TERM_MEMORY_SYNC_FINALIZE:-false}"
          - name: LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED
            value: "${LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED}"
          - name: LONG_TERM_MEMORY_VECTOR_FALLBACK_ENABLED
            value: "${LONG_TERM_MEMORY_VECTOR_FALLBACK_ENABLED}"
          - name: LONG_TERM_MEMORY_EMBEDDING_MODEL
            value: "${LONG_TERM_MEMORY_EMBEDDING_MODEL:-models/gemini-embedding-001}"
          - name: LONG_TERM_MEMORY_VECTOR_DIMS
            value: "${LONG_TERM_MEMORY_VECTOR_DIMS:-3072}"
          - name: LONG_TERM_MEMORY_EXTRACTOR
            value: "${LONG_TERM_MEMORY_EXTRACTOR}"
          - name: LONG_TERM_MEMORY_LANGMEM_MODEL
            value: "${LONG_TERM_MEMORY_LANGMEM_MODEL:-gemini-3.6-flash}"
          - name: LONG_TERM_MEMORY_VERIFIER
            value: "${LONG_TERM_MEMORY_VERIFIER}"
          - name: LONG_TERM_MEMORY_TRUSTMEM_MODEL
            value: "${LONG_TERM_MEMORY_TRUSTMEM_MODEL:-gemini-2.5-flash}"
          - name: LONG_TERM_MEMORY_TRUSTMEM_PROMPT_VERSION
            value: "${LONG_TERM_MEMORY_TRUSTMEM_PROMPT_VERSION:-trustmem-verifier-v2}"
          - name: LONG_TERM_MEMORY_TRUSTMEM_TIMEOUT_SECONDS
            value: "${LONG_TERM_MEMORY_TRUSTMEM_TIMEOUT_SECONDS:-30}"
          - name: LONG_TERM_MEMORY_TRUSTMEM_COVERAGE_THRESHOLD
            value: "${LONG_TERM_MEMORY_TRUSTMEM_COVERAGE_THRESHOLD:-0.80}"
          - name: LONG_TERM_MEMORY_TRUSTMEM_PRESERVATION_THRESHOLD
            value: "${LONG_TERM_MEMORY_TRUSTMEM_PRESERVATION_THRESHOLD:-0.90}"
          - name: LONG_TERM_MEMORY_TRUSTMEM_FAITHFULNESS_THRESHOLD
            value: "${LONG_TERM_MEMORY_TRUSTMEM_FAITHFULNESS_THRESHOLD:-0.95}"
          - name: LONG_TERM_MEMORY_TRANSITION_PATH
            value: "${LONG_TERM_MEMORY_TRANSITION_PATH:-llm}"
          - name: LONG_TERM_MEMORY_TRANSITION_MODEL
            value: "${LONG_TERM_MEMORY_TRANSITION_MODEL:-gemini-2.5-flash}"
          - name: LONG_TERM_MEMORY_TRANSITION_CONFIDENCE_THRESHOLD
            value: "${LONG_TERM_MEMORY_TRANSITION_CONFIDENCE_THRESHOLD:-0.85}"
          - name: LONG_TERM_MEMORY_TRANSITION_BATCH_SIZE
            value: "${LONG_TERM_MEMORY_TRANSITION_BATCH_SIZE:-10}"
          - name: LONG_TERM_MEMORY_DOMAIN_CANDIDATE_LIMIT
            value: "${LONG_TERM_MEMORY_DOMAIN_CANDIDATE_LIMIT:-50}"
          - name: LONG_TERM_MEMORY_ACTION_INFERENCE_ENABLED
            value: "${LONG_TERM_MEMORY_ACTION_INFERENCE_ENABLED:-false}"
          - name: LONG_TERM_MEMORY_APPLICABILITY_JUDGE_ENABLED
            value: "${LONG_TERM_MEMORY_APPLICABILITY_JUDGE_ENABLED:-true}"
          - name: LONG_TERM_MEMORY_APPLICABILITY_BATCH_SIZE
            value: "${LONG_TERM_MEMORY_APPLICABILITY_BATCH_SIZE:-10}"
          - name: RAPIDAPI_LOCK_FILE
            value: "/tmp/viettrip-rapidapi.lock"
      - name: mcp-car
        image: ${IMAGE}
        command: ["python", "src/mcp_servers/car/server.py"]
        env: *common_env
      - name: mcp-excursion
        image: ${IMAGE}
        command: ["python", "src/mcp_servers/excursion/server.py"]
        env: *common_env
      - name: mcp-flight
        image: ${IMAGE}
        command: ["python", "src/mcp_servers/flight/server.py"]
        env: *common_env
      - name: mcp-hotel
        image: ${IMAGE}
        command: ["python", "src/mcp_servers/hotel/server.py"]
        env: *common_env
      - name: mcp-travel-planner
        image: ${IMAGE}
        command: ["python", "src/mcp_servers/travel_planner/server.py"]
        env: *common_env
YAML

if az containerapp show --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  az containerapp update --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --yaml "${TMP_YAML}"
else
  az containerapp create \
    --name "${WEB_APP_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --environment "${AZURE_CONTAINERAPPS_ENV}" \
    --yaml "${TMP_YAML}"
fi

# Updating a Container App that was explicitly stopped does not start it. A
# production deploy must make the new revision reachable before smoke tests.
SUBSCRIPTION_ID="$(az account show --query id -o tsv | tr -d '\r')"
az rest \
  --method post \
  --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${WEB_APP_NAME}/start?api-version=2024-03-01" \
  --only-show-errors >/dev/null

for attempt in $(seq 1 60); do
  running_status="$(az containerapp show \
    --name "${WEB_APP_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --query properties.runningStatus \
    --output tsv | tr -d '\r')"
  echo "Web runningStatus=${running_status} (${attempt}/60)"
  if [[ "${running_status}" == "Running" ]]; then
    exit 0
  fi
  sleep 10
done

echo "Container App ${WEB_APP_NAME} did not reach Running after deployment." >&2
exit 1
