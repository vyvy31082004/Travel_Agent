#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

az group create --name "${AZURE_RESOURCE_GROUP}" --location "${AZURE_LOCATION}"

if ! az acr show --name "${AZURE_ACR_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" >/dev/null 2>&1; then
  az acr create \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${AZURE_ACR_NAME}" \
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
  az containerapp env create \
    --name "${AZURE_CONTAINERAPPS_ENV}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --location "${AZURE_LOCATION}"
fi
