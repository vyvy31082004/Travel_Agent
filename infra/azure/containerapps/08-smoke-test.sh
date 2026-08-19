#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

FQDN="$(az containerapp show --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.configuration.ingress.fqdn -o tsv)"
BASE_URL="https://${FQDN}"

echo "Smoke testing ${BASE_URL}"
curl --fail --show-error --silent "${BASE_URL}/healthz"
echo
curl --fail --show-error --silent --head "${BASE_URL}/" >/dev/null

for port in 8001 8002 8003 8004 8005; do
  if curl --max-time 5 --silent --fail "https://${FQDN}:${port}/sse" >/dev/null 2>&1; then
    echo "MCP port ${port} is publicly reachable; this is not allowed." >&2
    exit 1
  fi
done

echo "Smoke test passed. Verify a representative MCP-backed chat flow manually before shifting production traffic."
