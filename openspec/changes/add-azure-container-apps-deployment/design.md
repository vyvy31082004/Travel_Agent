## Context

Travel Agent is now a FastAPI application with Jinja UI, authenticated user/session persistence, LangGraph checkpointing, PostgreSQL result storage, long-term memory consolidation, LangMem candidate extraction, TrustMem-inspired verification, optional pgvector semantic recall, and five MCP servers consumed through localhost SSE URLs. The repository currently documents local startup with `alembic upgrade head` and `uvicorn app:app --app-dir src --host 0.0.0.0 --port 5000`, but lacks container deployment artifacts.

Azure Container Apps is a good target because it can run a multi-container web revision, scheduled/manual jobs, managed secrets, HTTPS ingress, and revisions without requiring AKS. The system should be packaged as one Docker image and run with different commands for the public web container, five MCP sidecar containers, migration job, worker job, and backfill job.

## Goals / Non-Goals

**Goals:**

- Containerize the current application without changing business behavior.
- Include Chromium/ChromeDriver and required runtime libraries in the image so existing Selenium-based car search behavior is preserved.
- Deploy one image to Azure Container Registry and reuse it for all Container App containers and jobs.
- Run FastAPI as the only externally exposed Azure Container App ingress on port `5000`.
- Run car, excursion, flight, hotel, and travel-planner MCP servers as sidecar containers in the same `viettrip-web` Container App revision and preserve existing `127.0.0.1:8001-8005` MCP URLs/ports.
- Ensure the web container waits/checks for all MCP sidecars before application graph construction can use MCP clients.
- Run Alembic migrations as a manual Container Apps Job.
- Run the long-term memory worker as a scheduled Container Apps Job using `python src/memory_worker.py --once` with parallelism `1`.
- Support a manual embedding backfill job using `python src/memory_worker.py --backfill-embeddings` with parallelism `1`.
- Document Azure PostgreSQL Flexible Server setup and require pgvector verification before running the current Alembic head.
- Provide clear environment/secrets examples and rollout order for memory, LangMem, TrustMem verifier, and pgvector.
- Add a lightweight health endpoint for Container Apps probes if one does not exist.
- Provide a CI/CD-ready GitHub Actions workflow sample at `.github/workflows/azure-container-apps-deploy.sample.yml` for image build, migration job execution, app/job updates, smoke checks, traffic shift, and rollback; implementing the artifact is required by this change, while enabling/using the workflow remains optional for operators.

**Non-Goals:**

- Do not migrate to AKS/Kubernetes.
- Do not split MCP servers into separate internal Container Apps in this change.
- Do not replace PostgreSQL or pgvector with another vector database.
- Do not change `/chat`, auth routes, templates, memory extraction, verifier, MCP tool contracts, Selenium car search behavior, or repository semantics.
- Do not run database migrations automatically in every web container startup.
- Do not expose MCP sidecar ports or Container Apps Jobs through public ingress.
- Do not require Azure Key Vault integration in the first implementation, although docs can mention it as an upgrade path.

## Decisions

### Use one Docker image with multiple commands

Build one image containing `requirements.txt`, `src`, `alembic`, and `alembic.ini`, plus Chromium/ChromeDriver and the OS libraries required by Selenium/Chrome. Reuse this image for:

- `viettrip-web` web container: a startup command that waits for MCP sidecars on `127.0.0.1:8001-8005`, then runs `uvicorn app:app --app-dir src --host 0.0.0.0 --port 5000`
- `viettrip-mcp-car` sidecar: `python src/mcp_servers/car/server.py`
- `viettrip-mcp-excursion` sidecar: `python src/mcp_servers/excursion/server.py`
- `viettrip-mcp-flight` sidecar: `python src/mcp_servers/flight/server.py`
- `viettrip-mcp-hotel` sidecar: `python src/mcp_servers/hotel/server.py`
- `viettrip-mcp-travel-planner` sidecar: `python src/mcp_servers/travel_planner/server.py`
- `viettrip-migrate` job: `alembic upgrade head`
- `viettrip-memory-worker` job: `python src/memory_worker.py --once`
- `viettrip-backfill-embeddings` job: `python src/memory_worker.py --backfill-embeddings`

Rationale: one artifact simplifies CI/CD and guarantees web, MCP sidecars, workers, and migrations use the same code revision.

### Use Option A MCP sidecars in one web Container App revision

The web deployment must be one Azure Container App named `viettrip-web` with a multi-container revision: one web container and five MCP sidecar containers. Container Apps containers in the same revision share the same network namespace, so the existing MCP URLs remain localhost URLs:

- `http://127.0.0.1:8001/sse` car MCP
- `http://127.0.0.1:8002/sse` excursion MCP
- `http://127.0.0.1:8003/sse` flight MCP
- `http://127.0.0.1:8004/sse` hotel MCP
- `http://127.0.0.1:8005/sse` travel-planner MCP

Only the web container target port `5000` receives external ingress. Sidecar ports are not exposed through Container Apps ingress. Separate internal MCP Container Apps are explicitly deferred.

The deployment artifacts must include a deterministic startup wait/check for the web container. The check should retry all five localhost MCP ports or `/sse` endpoints and fail fast after a bounded timeout so the revision does not start graph/MCP client usage against unavailable sidecars. Smoke validation must then verify the public FastAPI ingress, `/healthz`, and a representative MCP-backed path after deployment while confirming MCP sidecar ports remain private.

### Use Azure Container Apps Jobs for migrations and worker

Migrations should run as a manual job, not during web startup. Memory consolidation should run as a scheduled job because the current worker has a `--once` command and the database claim logic already uses pending jobs/retry semantics.

Initial worker and backfill job settings:

- worker schedule: every minute or every few minutes, documented as configurable
- parallelism: `1`
- replica completion count: `1`
- retry limit: conservative, because job retries plus database retry state can otherwise duplicate noise
- ingress: none, because Container Apps Jobs do not serve public HTTP for this deployment

The migration job must receive the same required settings validation inputs as the app, including `COOKIE_SECRET`, because current settings require it even when running migration-oriented commands.

### Treat pgvector as a hard preflight for current Alembic head

Primary database target should be Azure Database for PostgreSQL Flexible Server with SSL-required connection string. The current Alembic head requires the `vector` extension, so deployment docs/scripts must verify pgvector before migrations are run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extname FROM pg_extension WHERE extname = 'vector';
```

If the selected Azure PostgreSQL version/region/tier cannot enable pgvector, operators must stop before `alembic upgrade head` and choose a supported PostgreSQL version/region/tier or use a self-managed PostgreSQL + pgvector instance. Disabling vector recall is still useful at runtime, but it is not sufficient to complete migrations when the extension is unavailable.

### Use Container Apps secrets for first implementation

Store required secret values as Container Apps secrets and reference them from containers/jobs with `secretref:` values:

- `DATABASE_URL`
- `COOKIE_SECRET`
- `GOOGLE_API_KEY`
- `RAPIDAPI_KEY`
- `WEATHER_API_KEY`
- optional `LANGSMITH_API_KEY`

The migration job must inject `DATABASE_URL` and `COOKIE_SECRET` via secret references, plus any additional settings required by current settings validation, even though it only runs `alembic upgrade head`.

Non-secret environment variables include host/language/currency/country overrides (`BOOKING_RAPIDAPI_HOST`, `GOOGLE_FLIGHT_RAPIDAPI_HOST`, `GEOCODING_RAPIDAPI_HOST`, `BOOKING_LANGUAGE_CODE`, `BOOKING_CURRENCY_CODE`, `COUNTRY_CODE`), cookie/debug settings, DB pool/retention settings, and memory/LangMem/TrustMem/pgvector rollout flags and thresholds. Azure Key Vault can be documented as a later hardening step.

### Use external ingress only for the web app

Only `viettrip-web` should have external ingress on target port `5000`. Migration, worker, and backfill jobs have no ingress, and MCP sidecars are only reachable inside the web revision through localhost.

### Health endpoint is safe and minimal

Add `GET /healthz` returning a static OK response. Optionally add `GET /readyz` that checks database connectivity and MCP sidecar reachability, but readiness DB checks can be deferred if they risk pool lifecycle complexity.

### Make scripts concrete and testable without real secrets

Deployment scripts must live under `infra/azure/containerapps/`, use strict shell mode (`set -euo pipefail`), require explicit environment variables/placeholders, avoid hard-coded real secret values, use Container Apps `secretref:` settings for secrets, and be safe to review statically. The required script set is:

- `00-vars.example.sh`: placeholder-only operator variables and secret names; no real secrets
- `01-create-foundation.sh`: resource group, ACR, Log Analytics/Container Apps Environment, managed identity or registry auth foundation
- `02-build-image.sh`: build and push one image to ACR
- `03-deploy-web.sh`: create/update `viettrip-web` as one web container plus five MCP sidecars, external ingress only on port `5000`, localhost MCP URLs, secret references, revision mode/traffic controls, probes, and startup wait command
- `04-create-migration-job.sh`: create/update manual `viettrip-migrate` job with `DATABASE_URL` and `COOKIE_SECRET` secret references
- `05-run-migration-job.sh`: run migration job only after pgvector preflight succeeds and inspect execution status/logs
- `06-create-memory-worker-job.sh`: create/update scheduled `viettrip-memory-worker` job with parallelism `1`, completion count `1`, no ingress, and secret references
- `07-create-backfill-job.sh`: create/update and optionally run manual `viettrip-backfill-embeddings` job with parallelism `1`, no ingress, and secret references
- `08-smoke-test.sh`: validate public `/healthz`, app FQDN/custom domain, revision identity/traffic, and representative MCP-backed behavior without exposing MCP ports
- `09-rollback-web.sh`: shift traffic back to a previous revision and provide worker-disable guidance

Static validation must check each shell script for syntax, strict shell mode, placeholder-only secrets, `secretref:` usage for required secrets, revision traffic/smoke/rollback coverage, and the web artifact's one-web-plus-five-sidecars topology.

### Provide a CI/CD-ready path without requiring CI/CD adoption

The change must include a CI/CD-ready GitHub Actions sample at `.github/workflows/azure-container-apps-deploy.sample.yml` that can build/push the image, update/create jobs, run migration, update the multi-container web revision and worker job images, smoke test the new revision, shift traffic, and roll back. Operators may still perform the same flow manually with Azure CLI scripts, so CI/CD adoption is optional rather than an open decision; the presence of the workflow sample is not optional for this change.

## Risks / Trade-offs

- **Risk: Azure PostgreSQL does not support pgvector in chosen environment** → Mitigation: verify extension before migrations; stop and choose a supported PostgreSQL version/region/tier or self-managed PostgreSQL + pgvector if unavailable.
- **Risk: MCP sidecars are not ready when web graph clients initialize** → Mitigation: web startup waits/checks `127.0.0.1:8001-8005` with bounded retries before starting FastAPI graph usage.
- **Risk: migrations race with web revisions** → Mitigation: deploy pipeline runs migration job before shifting web revision traffic.
- **Risk: worker job overlaps with previous execution** → Mitigation: set job parallelism to `1` and rely on `FOR UPDATE SKIP LOCKED`; keep schedule interval conservative.
- **Risk: secrets leak through generated scripts** → Mitigation: scripts use variables/placeholders and Container Apps secret references; never commit real secrets.
- **Risk: Selenium car search breaks in container** → Mitigation: Dockerfile installs Chromium/ChromeDriver and runtime libraries and validation includes a static/runtime check for browser binaries.
- **Risk: cold starts affect chat UX** → Mitigation: configure `min-replicas=1` for web app.
- **Risk: Log Analytics cost grows** → Mitigation: document retention and log-level considerations.

## Migration Plan

1. Add Dockerfile and `.dockerignore`.
2. Add `env.production.example` with all required deployment variables, secrets, MCP localhost URLs if externalized later, and safe defaults.
3. Add health endpoint if absent.
4. Add startup wait/check for MCP sidecar readiness before the web process constructs/uses MCP-backed graphs or serves traffic.
5. Add Azure Container Apps deployment documentation.
6. Add helper scripts for ACR build/push, Container Apps Environment setup, multi-container web app creation/update, migration job, worker job, backfill job, smoke checks, revision traffic, and rollback.
7. Add `.github/workflows/azure-container-apps-deploy.sample.yml` as the required CI/CD-ready sample for image build, migration, app/job updates, smoke tests, revision traffic shift, and rollback.
8. Validate image builds locally or with `az acr build` and verify Chromium/ChromeDriver presence.
9. Run pgvector preflight against staging/production database; do not run Alembic if `vector` cannot be installed and selected.
10. Run migration job against staging database with required secrets including `COOKIE_SECRET`.
11. Deploy web Container App multi-container revision with memory write/vector flags initially conservative.
12. Smoke test `/healthz`, the public FastAPI port, and representative MCP-backed travel search behavior.
13. Enable worker job after web smoke tests pass.
14. Roll out long-term memory, TrustMem verifier, LangMem, and pgvector in staged order.

Rollback strategy:

- Use Azure Container Apps revisions to shift traffic back to the previous web image.
- Disable scheduled worker job if memory writes misbehave.
- Turn off feature flags (`LONG_TERM_MEMORY_WRITE_ENABLED=false`, `LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED=false`, verifier/extractor flags) without rebuilding image.
- Do not downgrade database schema unless a dedicated rollback migration exists.

## Open Questions

- Which Azure region and PostgreSQL version/tier will be used, and does it support pgvector? This is an operator deployment input, not a spec blocker, because the deployment flow requires pgvector preflight before migrations.
- Should custom domain be root domain or subdomain such as `app.<domain>`? The first documented path uses a subdomain, and operators may adapt it.
