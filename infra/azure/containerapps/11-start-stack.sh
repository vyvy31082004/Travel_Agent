#!/usr/bin/env bash
# Start PostgreSQL, web app, then restore the memory-worker schedule.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

trim_cr() {
  printf '%s' "${1:-}" | tr -d '\r'
}

postgres_server_name() {
  if [[ -n "${AZURE_POSTGRES_SERVER_NAME:-}" ]]; then
    trim_cr "${AZURE_POSTGRES_SERVER_NAME}"
    return
  fi
  local host_part host
  host_part="${DATABASE_URL##*@}"
  host="${host_part%%[:/]*}"
  trim_cr "${host%%.*}"
}

wait_for_postgres() {
  local server="$1"
  local state=""
  local attempt
  for attempt in $(seq 1 60); do
    state="$(trim_cr "$(az postgres flexible-server show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${server}" --query state -o tsv)")"
    echo "PostgreSQL state=${state} (${attempt}/60)"
    if [[ "${state}" == "Ready" ]]; then
      return 0
    fi
    sleep 10
  done
  echo "PostgreSQL ${server} did not become Ready." >&2
  return 1
}

wait_for_web() {
  local status=""
  local health=""
  local attempt
  for attempt in $(seq 1 36); do
    status="$(trim_cr "$(az containerapp show --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.runningStatus -o tsv)")"
    health="$(trim_cr "$(az containerapp revision list --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --query "[?properties.latestRevision==\`true\` || properties.active].properties.healthState | [0]" -o tsv)")"
    echo "Web runningStatus=${status} health=${health} (${attempt}/36)"
    if [[ "${status}" == "Running" ]]; then
      return 0
    fi
    sleep 10
  done
  echo "Web app ${WEB_APP_NAME} did not reach Running." >&2
  return 1
}

echo "Starting VietTrip runtime in ${AZURE_RESOURCE_GROUP}"

PG_SERVER="$(postgres_server_name)"
if [[ -z "${PG_SERVER}" ]]; then
  echo "Could not resolve PostgreSQL server name from AZURE_POSTGRES_SERVER_NAME or DATABASE_URL." >&2
  exit 1
fi

PG_STATE="$(trim_cr "$(az postgres flexible-server show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${PG_SERVER}" --query state -o tsv)")"
if [[ "${PG_STATE}" == "Ready" ]]; then
  echo "PostgreSQL ${PG_SERVER} already Ready"
else
  echo "Starting PostgreSQL ${PG_SERVER} (state=${PG_STATE})"
  az postgres flexible-server start \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${PG_SERVER}" \
    --only-show-errors
  wait_for_postgres "${PG_SERVER}"
fi

if ! az containerapp show --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  echo "Web app ${WEB_APP_NAME} not found. Run 03-deploy-web.sh first." >&2
  exit 1
fi

SUBSCRIPTION_ID="$(trim_cr "$(az account show --query id -o tsv)")"
echo "Starting container app ${WEB_APP_NAME}"
az rest \
  --method post \
  --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${WEB_APP_NAME}/start?api-version=2024-03-01" \
  --only-show-errors >/dev/null || {
    echo "REST start failed; ensuring ${WEB_APP_NAME} can scale." >&2
    az containerapp update \
      --name "${WEB_APP_NAME}" \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --min-replicas "${WEB_MIN_REPLICAS}" \
      --max-replicas "${WEB_MAX_REPLICAS}" \
      --only-show-errors >/dev/null
  }
wait_for_web

if az containerapp job show --name "${MEMORY_WORKER_JOB_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  echo "Restoring ${MEMORY_WORKER_JOB_NAME} schedule ${WORKER_CRON_EXPRESSION}"
  az containerapp job update \
    --name "${MEMORY_WORKER_JOB_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --cron-expression "${WORKER_CRON_EXPRESSION}" \
    --only-show-errors >/dev/null
else
  echo "Memory worker job not found; skipping schedule restore."
fi

FQDN="$(trim_cr "$(az containerapp show --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.configuration.ingress.fqdn -o tsv)")"
echo "Waiting for https://${FQDN}/healthz"
for attempt in $(seq 1 18); do
  if curl --max-time 20 --fail --silent "https://${FQDN}/healthz" >/dev/null; then
    echo "https://${FQDN}/healthz ok"
    echo "Stack started. Open https://${FQDN}/"
    exit 0
  fi
  echo "healthz not ready (${attempt}/18)"
  sleep 10
done

echo "Web started but /healthz did not succeed within the wait window." >&2
echo "Open https://${FQDN}/healthz after the first replica finishes cold start."
exit 1
