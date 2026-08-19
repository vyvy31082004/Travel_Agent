# Azure Container Apps deployment validation notes

Ngày ghi chú: 2026-08-18

## Kết quả đã xác minh trong môi trường local

- Python compile pass:

```text
python -m compileall -q src tests
COMPILE_EXIT=0
```

- Targeted tests pass:

```text
pytest -q tests/test_health_routes.py tests/test_azure_container_apps_artifacts.py
7 passed, 1 warning
PYTEST_EXIT=0
```

- OpenSpec validation pass:

```text
openspec validate "add-azure-container-apps-deployment" --type change --json
valid=true
issues=[]
OPENSPEC_EXIT=0
```

- Docker CLI exists:

```text
Docker version 29.6.1, build 8900f1d
DOCKER_EXIT=0
```

## Environment-specific blockers / notes

- Docker image build was attempted but Docker daemon/Desktop Linux engine was not running:

```text
ERROR: failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine;
open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
DOCKER_BUILD_EXIT=1
```

This is an environment blocker, not a Dockerfile validation failure. Start Docker Desktop/Linux engine and rerun:

```bash
docker build -t viettrip-ai:test-deploy .
```

- Azure CLI/account validation and real deployment were not completed in this local session. Before deployment, verify:

```bash
az login
az account show
az extension add --name containerapp --upgrade
```

- Azure PostgreSQL pgvector capability is environment-specific and must be verified before migration:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extname FROM pg_extension WHERE extname = 'vector';
```

- Real Container Apps deployment, custom domain binding, managed certificate provisioning, migration job execution, worker job execution, and embedding backfill require Azure credentials and live infrastructure.
