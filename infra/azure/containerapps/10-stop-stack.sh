#!/usr/bin/env bash
# Stop billable runtime: memory worker schedule, web app, then PostgreSQL.
# Leaves ACR, Log Analytics, and the Container Apps Environment in place.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

# Cron that never matches, used to pause a scheduled job without deleting it.
DISABLED_CRON="0 0 31 2 *"

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

pause_scheduled_job() {
  local job_name="$1"
  local trigger=""
  if ! az containerapp job show --name "${job_name}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
    echo "Job ${job_name} not found; skipping."
    return
  fi

  trigger="$(trim_cr "$(az containerapp job show --name "${job_name}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.configuration.triggerType -o tsv)")"
  echo "Stopping running executions for ${job_name}"
  az containerapp job stop \
    --name "${job_name}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --only-show-errors >/dev/null || true

  if [[ "${trigger}" == "Schedule" ]]; then
    echo "Pausing schedule for ${job_name} (${DISABLED_CRON})"
    az containerapp job update \
      --name "${job_name}" \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --cron-expression "${DISABLED_CRON}" \
      --only-show-errors >/dev/null
  fi
}

echo "Stopping VietTrip runtime in ${AZURE_RESOURCE_GROUP}"

pause_scheduled_job "${MEMORY_WORKER_JOB_NAME}"
pause_scheduled_job "${BACKFILL_JOB_NAME}"

if az containerapp show --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  SUBSCRIPTION_ID="$(trim_cr "$(az account show --query id -o tsv)")"
  WEB_STATUS="$(trim_cr "$(az containerapp show --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.runningStatus -o tsv)")"
  if [[ "${WEB_STATUS}" == "Stopped" ]]; then
    echo "Web app ${WEB_APP_NAME} already Stopped"
  else
    echo "Stopping container app ${WEB_APP_NAME} (status=${WEB_STATUS})"
    az rest \
      --method post \
      --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${WEB_APP_NAME}/stop?api-version=2024-03-01" \
      --only-show-errors >/dev/null || {
        echo "REST stop failed; scaling ${WEB_APP_NAME} to zero replicas instead." >&2
        az containerapp update \
          --name "${WEB_APP_NAME}" \
          --resource-group "${AZURE_RESOURCE_GROUP}" \
          --min-replicas 0 \
          --max-replicas 1 \
          --only-show-errors >/dev/null
      }
  fi
else
  echo "Web app ${WEB_APP_NAME} not found; skipping."
fi

PG_SERVER="$(postgres_server_name)"
if [[ -n "${PG_SERVER}" ]] && az postgres flexible-server show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${PG_SERVER}" >/dev/null 2>&1; then
  PG_STATE="$(trim_cr "$(az postgres flexible-server show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${PG_SERVER}" --query state -o tsv)")"
  if [[ "${PG_STATE}" == "Stopped" || "${PG_STATE}" == "Stopping" ]]; then
    echo "PostgreSQL ${PG_SERVER} already ${PG_STATE}"
  else
    echo "Stopping PostgreSQL ${PG_SERVER} (state=${PG_STATE})"
    az postgres flexible-server stop \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${PG_SERVER}" \
      --only-show-errors
  fi
else
  echo "PostgreSQL server not found; skipping."
fi

cat <<MSG
Runtime stopped.
Still billed at a low rate: ACR, Log Analytics, Container Apps Environment, and PostgreSQL storage.
Azure may auto-start a stopped Flexible Server after 7 days; run this script again if that happens.
MSG
