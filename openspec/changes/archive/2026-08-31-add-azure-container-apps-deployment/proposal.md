## Why

Hệ thống Travel Agent hiện đã có FastAPI web app, PostgreSQL/Alembic, auth/session persistence, long-term memory worker, LangMem/TrustMem verifier, pgvector semantic memory, và năm MCP server cục bộ cho car/excursion/flight/hotel/travel-planner. Repo chưa có artifact triển khai chuẩn container. Cần một kế hoạch triển khai Azure Container Apps để production hóa hệ thống với domain, HTTPS, web container, MCP sidecars, worker job, migration job, secrets, pgvector preflight, Chromium/Selenium runtime, và rollout memory an toàn.

## What Changes

- Add deployment artifacts for Azure Container Apps:
  - production `Dockerfile` with Chromium/ChromeDriver/runtime libraries needed by current Selenium car search behavior
  - `.dockerignore`
  - production env example
  - Azure Container Apps deployment documentation
  - concrete Azure CLI scripts under `infra/azure/containerapps/`: `00-vars.example.sh`, `01-create-foundation.sh`, `02-build-image.sh`, `03-deploy-web.sh`, `04-create-migration-job.sh`, `05-run-migration-job.sh`, `06-create-memory-worker-job.sh`, `07-create-backfill-job.sh`, `08-smoke-test.sh`, and `09-rollback-web.sh`
  - CI/CD-ready GitHub Actions workflow sample at `.github/workflows/azure-container-apps-deploy.sample.yml` as a required artifact, while operator adoption of CI/CD remains optional
- Define a one-image runtime model deployed with different commands:
  - one public FastAPI web Container App revision containing the web container plus five MCP sidecar containers
  - Alembic migration manual Container Apps Job
  - scheduled memory worker Container Apps Job
  - manual embedding backfill Container Apps Job
- Preserve MCP topology inside the web Container App revision:
  - car MCP at `127.0.0.1:8001`
  - excursion MCP at `127.0.0.1:8002`
  - flight MCP at `127.0.0.1:8003`
  - hotel MCP at `127.0.0.1:8004`
  - travel planner MCP at `127.0.0.1:8005`
  - only FastAPI port `5000` has public ingress
- Include web startup waiting/readiness checks so graph construction does not occur until all MCP sidecars are reachable, plus smoke validation for the public FastAPI ingress after revision deployment.
- Document Azure PostgreSQL Flexible Server requirements, including `pgvector` as a hard preflight before running the current Alembic head.
- Document complete secret/env management for required secrets (`DATABASE_URL`, `COOKIE_SECRET`, `GOOGLE_API_KEY`, `RAPIDAPI_KEY`, `WEATHER_API_KEY`, optional `LANGSMITH_API_KEY`) and non-secret host/language/currency/country, memory, LangMem, TrustMem, and pgvector flags.
- Add a lightweight health endpoint if missing so Container Apps can probe the web service.
- Define static validation for deployment artifacts: Dockerfile, `.dockerignore`, production env example, Azure scripts, deployment docs, and the GitHub Actions sample.
- Preserve existing application API contracts and runtime behavior; deployment artifacts must not change `/chat`, auth, memory, MCP tool, Selenium car search, or worker semantics.

## Capabilities

### New Capabilities
- `azure-container-apps-deployment`: Containerized deployment plan and artifacts for running the current Travel Agent system on Azure Container Apps with one public multi-container web app revision, five localhost MCP sidecars, migration job, memory worker job, pgvector-ready PostgreSQL, secrets, DNS/HTTPS, CI/CD-ready sample path, and rollout guidance.

### Modified Capabilities

## Impact

- Adds deployment-only files such as `Dockerfile`, `.dockerignore`, `env.production.example`, `docs/azure-container-apps-deployment.md`, Azure CLI helper scripts under `infra/azure/containerapps/`, and a required CI/CD-ready GitHub Actions workflow sample.
- May add non-invasive health/readiness endpoints and startup wait/check wiring needed for Azure probes and MCP sidecar readiness.
- Requires Azure Container Registry, Azure Container Apps Environment, Azure PostgreSQL Flexible Server or equivalent PostgreSQL with `pgvector`, and configured domain/DNS.
- Requires image runtime packages for Chromium/ChromeDriver/Selenium dependencies.
- Does not introduce a new application database model beyond existing Alembic migrations.
- Does not require Kubernetes/AKS.
