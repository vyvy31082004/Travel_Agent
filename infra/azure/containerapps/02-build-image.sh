#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/00-vars.local.sh"

if az acr build \
  --registry "${AZURE_ACR_NAME}" \
  --image "${IMAGE_NAME}:${IMAGE_TAG}" \
  .; then
  exit 0
fi

echo "ACR Tasks build was unavailable; falling back to local Docker build and push." >&2
command -v docker >/dev/null 2>&1 || {
  echo "Docker CLI is required for the local build fallback." >&2
  exit 1
}
docker info >/dev/null

ACR_LOGIN_SERVER="$(az acr show --name "${AZURE_ACR_NAME}" --query loginServer -o tsv)"
LOCAL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
REMOTE_IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${IMAGE_TAG}"

docker build --pull --tag "${LOCAL_IMAGE}" .
az acr login --name "${AZURE_ACR_NAME}"
docker tag "${LOCAL_IMAGE}" "${REMOTE_IMAGE}"
docker push "${REMOTE_IMAGE}"
