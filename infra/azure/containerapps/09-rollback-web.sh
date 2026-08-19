#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

: "${ROLLBACK_REVISION:?Set ROLLBACK_REVISION to the revision name that should receive 100 percent traffic}"

az containerapp ingress traffic set \
  --name "${WEB_APP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --revision-weight "${ROLLBACK_REVISION}=100"

cat <<MSG
Rollback traffic shifted to ${ROLLBACK_REVISION}.
If memory writes caused issues, disable or pause the worker job:
  az containerapp job stop --name ${MEMORY_WORKER_JOB_NAME} --resource-group ${AZURE_RESOURCE_GROUP}
  az containerapp update --name ${WEB_APP_NAME} --resource-group ${AZURE_RESOURCE_GROUP} --set-env-vars LONG_TERM_MEMORY_WRITE_ENABLED=false LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED=false
Do not downgrade database schema unless a dedicated rollback migration exists.
MSG
