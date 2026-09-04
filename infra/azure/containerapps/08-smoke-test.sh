#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

FQDN="$(az containerapp show --name "${WEB_APP_NAME}" --resource-group "${AZURE_RESOURCE_GROUP}" --query properties.configuration.ingress.fqdn -o tsv)"
BASE_URL="https://${FQDN}"

echo "Smoke testing ${BASE_URL}"
health_ready=false
for attempt in $(seq 1 36); do
  if curl --max-time 20 --fail --show-error --silent "${BASE_URL}/healthz"; then
    echo
    health_ready=true
    break
  fi
  echo "healthz not ready (${attempt}/36); waiting for the web and MCP sidecars" >&2
  sleep 10
done
if [[ "${health_ready}" != "true" ]]; then
  echo "healthz did not become ready." >&2
  exit 1
fi

# FastAPI GET routes may return 405 to HEAD unless HEAD is declared explicitly,
# so verify the real browser method instead.
curl --max-time 20 --fail --show-error --silent "${BASE_URL}/" >/dev/null
echo "Root page GET succeeded"

for port in 8001 8002 8003 8004 8005; do
  echo "Checking that MCP port ${port} is not public"
  if curl --max-time 5 --silent --fail "https://${FQDN}:${port}/sse" >/dev/null 2>&1; then
    echo "MCP port ${port} is publicly reachable; this is not allowed." >&2
    exit 1
  fi
done

echo "Smoke test passed. Verify a representative MCP-backed chat flow manually before shifting production traffic."
