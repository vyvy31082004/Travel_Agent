#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

# Resource groups have their own metadata location. An existing resource group may
# legitimately be in a different region from the resources deployed into it, so do
# not call `az group create` with the target resource location on every rerun.
if az group show --name "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  echo "Using existing resource group ${AZURE_RESOURCE_GROUP}"
else
  az group create --name "${AZURE_RESOURCE_GROUP}" --location "${AZURE_LOCATION}"
fi

if ! az acr show --name "${AZURE_ACR_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  az acr create \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${AZURE_ACR_NAME}" \
    --location "${AZURE_LOCATION}" \
    --sku Basic \
    --admin-enabled true
fi

if ! az monitor log-analytics workspace show --resource-group "${AZURE_RESOURCE_GROUP}" --workspace-name "${AZURE_LOG_ANALYTICS}" >/dev/null 2>&1; then
  az monitor log-analytics workspace create \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --workspace-name "${AZURE_LOG_ANALYTICS}" \
    --location "${AZURE_LOCATION}"
fi

if ! az containerapp env show --name "${AZURE_CONTAINERAPPS_ENV}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  # Reuse the named workspace when it already exists. This avoids creating an
  # additional auto-generated workspace (and its extra cost) on reruns/migration.
  LOGS_WORKSPACE_ID="$(az monitor log-analytics workspace show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --workspace-name "${AZURE_LOG_ANALYTICS}" \
    --query customerId \
    --output tsv)"
  LOGS_WORKSPACE_KEY="$(az monitor log-analytics workspace get-shared-keys \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --workspace-name "${AZURE_LOG_ANALYTICS}" \
    --query primarySharedKey \
    --output tsv)"
  az containerapp env create \
    --name "${AZURE_CONTAINERAPPS_ENV}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --location "${AZURE_LOCATION}" \
    --logs-destination log-analytics \
    --logs-workspace-id "${LOGS_WORKSPACE_ID}" \
    --logs-workspace-key "${LOGS_WORKSPACE_KEY}"
fi
