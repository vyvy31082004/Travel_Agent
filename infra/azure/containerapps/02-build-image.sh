#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

az acr build \
  --registry "${AZURE_ACR_NAME}" \
  --image "${IMAGE_NAME}:${IMAGE_TAG}" \
  .
