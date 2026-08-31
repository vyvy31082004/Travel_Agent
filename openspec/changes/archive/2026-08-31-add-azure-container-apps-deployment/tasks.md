## 1. Container Image

- [x] 1.1 Add production `Dockerfile` for FastAPI runtime on port `5000`.
- [x] 1.2 Include Chromium/ChromeDriver and required Selenium/Chrome runtime libraries in the image to preserve current car search behavior.
- [x] 1.3 Add `.dockerignore` excluding local environments, git data, caches, local env files, logs, and other non-runtime artifacts.
- [x] 1.4 Build the image locally or with `az acr build` and verify the web command starts FastAPI after MCP readiness checks.
- [x] 1.5 Verify the same image can run all five MCP server commands, `alembic upgrade head`, `python src/memory_worker.py --once`, and `python src/memory_worker.py --backfill-embeddings`.
- [x] 1.6 Verify Chromium/ChromeDriver binaries are present in the built image.

## 2. Health, MCP Readiness, and Runtime Configuration

- [x] 2.1 Add `GET /healthz` endpoint returning HTTP 200 with a simple status payload.
- [x] 2.2 Add a bounded startup wait/check so the web process does not build/use MCP-backed graphs before sidecars are reachable at `127.0.0.1:8001-8005`.
- [x] 2.3 Add `env.production.example` covering required secrets: `DATABASE_URL`, `COOKIE_SECRET`, `GOOGLE_API_KEY`, `RAPIDAPI_KEY`, `WEATHER_API_KEY`, and optional `LANGSMITH_API_KEY`.
- [x] 2.4 Add `env.production.example` entries for non-secret host/language/currency/country overrides: `BOOKING_RAPIDAPI_HOST`, `GOOGLE_FLIGHT_RAPIDAPI_HOST`, `GEOCODING_RAPIDAPI_HOST`, `BOOKING_LANGUAGE_CODE`, `BOOKING_CURRENCY_CODE`, and `COUNTRY_CODE`.
- [x] 2.5 Add `env.production.example` entries for cookie/debug settings, database pool/retention settings, and memory/LangMem/TrustMem/pgvector rollout flags and thresholds used by current settings.
- [x] 2.6 Document safe production defaults: `COOKIE_SECURE=true`, debug off, vector recall off until pgvector is verified and embeddings are backfilled, and conservative memory rollout.

## 3. Azure Container Apps Infrastructure Artifacts

- [x] 3.1 Add `infra/azure/containerapps/00-vars.example.sh` with placeholder-only operator variables, secret names, non-secret env defaults, image tags, app/job names, revision controls, and no real secrets.
- [x] 3.2 Add `infra/azure/containerapps/01-create-foundation.sh` for creating/updating the resource group, Azure Container Registry, Log Analytics workspace, and Container Apps Environment.
- [x] 3.3 Add `infra/azure/containerapps/02-build-image.sh` for building and pushing the single image to ACR.
- [x] 3.4 Add `infra/azure/containerapps/03-deploy-web.sh` for creating/updating `viettrip-web` as one multi-container Container App revision with the web container plus five MCP sidecar containers.
- [x] 3.5 Ensure `03-deploy-web.sh` enables external ingress only on FastAPI port `5000`, does not expose MCP sidecar ports `8001-8005` publicly, uses the same image revision for all six containers, preserves localhost MCP URLs/ports, sets revision traffic controls, and configures the bounded MCP startup wait before FastAPI starts.
- [x] 3.6 Add `infra/azure/containerapps/04-create-migration-job.sh` for creating/updating the manual `viettrip-migrate` job, including `COOKIE_SECRET` and `DATABASE_URL` secret references and any additional settings required by current settings validation.
- [x] 3.7 Add `infra/azure/containerapps/05-run-migration-job.sh` for running the migration job only after pgvector preflight succeeds and inspecting execution status/logs.
- [x] 3.8 Add `infra/azure/containerapps/06-create-memory-worker-job.sh` for creating/updating the scheduled `viettrip-memory-worker` job with `python src/memory_worker.py --once`, no ingress, parallelism `1`, replica completion count `1`, and secret references.
- [x] 3.9 Add `infra/azure/containerapps/07-create-backfill-job.sh` for creating/running the manual `viettrip-backfill-embeddings` job with no ingress, parallelism `1`, and secret references.
- [x] 3.10 Add `infra/azure/containerapps/08-smoke-test.sh` for smoke checking public `/healthz`, public FastAPI ingress, active revision/traffic, and representative MCP-backed behavior while confirming MCP ports are not public.
- [x] 3.11 Add `infra/azure/containerapps/09-rollback-web.sh` for shifting revision traffic back to a previous revision and documenting worker-disable rollback guidance.
- [x] 3.12 Ensure every shell script uses strict shell mode (`set -euo pipefail`), placeholders/variables, and Container Apps `secretref:` references instead of hard-coded real secrets.

## 4. PostgreSQL and pgvector Deployment Guidance

- [x] 4.1 Document Azure PostgreSQL Flexible Server creation and `DATABASE_URL` format with SSL.
- [x] 4.2 Document pgvector hard preflight SQL: `CREATE EXTENSION IF NOT EXISTS vector;` and `SELECT extname FROM pg_extension WHERE extname = 'vector';`.
- [x] 4.3 Document that the current Alembic head requires pgvector; if pgvector is unavailable, operators must stop before migration and choose a supported Azure PostgreSQL version/region/tier or self-managed PostgreSQL with pgvector.
- [x] 4.4 Document that `LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED=false` does not bypass the current migration requirement, although it remains the safe runtime default until verification/backfill are complete.
- [x] 4.5 Document migration order and why migrations are run through a manual job rather than web startup.
- [x] 4.6 Document embedding dimension verification and backfill workflow before enabling vector recall.

## 5. Domain, HTTPS, and Operations Documentation

- [x] 5.1 Add `docs/azure-container-apps-deployment.md` with end-to-end deployment steps for manual Azure CLI deployment.
- [x] 5.2 Document Container Apps custom domain setup for a subdomain and managed certificate binding.
- [x] 5.3 Document logs, job execution inspection, rollback through revisions, traffic shift, smoke checks, and disabling worker jobs.
- [x] 5.4 Document staged rollout order: web smoke test, deterministic memory write, TrustMem dry-run, TrustMem gated, LangMem, pgvector recall.
- [x] 5.5 Document that MCP servers are deployed as sidecars inside the `viettrip-web` revision and that separate internal MCP Container Apps are deferred.

## 6. CI/CD

- [x] 6.1 Add required CI/CD-ready sample artifact `.github/workflows/azure-container-apps-deploy.sample.yml` for building the image to ACR.
- [x] 6.2 Include deployment steps in the workflow sample for updating/creating jobs, running migration before traffic shift, updating the multi-container web revision and worker/backfill job images, smoke testing, shifting traffic, and rollback.
- [x] 6.3 Document required GitHub secrets, Azure federated login or service principal setup, environment protection, and manual approval considerations for production.
- [x] 6.4 Document that CI/CD use is optional because the Azure CLI scripts provide an equivalent manual path, but the GitHub Actions sample artifact is required by this change.

## 7. Validation

- [x] 7.1 Run OpenSpec validation for `add-azure-container-apps-deployment`.
- [x] 7.2 Run Python compile checks after adding health endpoint and MCP readiness wiring.
- [x] 7.3 Run targeted tests for app routes including `/healthz`.
- [x] 7.4 Run shell syntax validation for scripts under `infra/azure/containerapps/` and verify each shell script uses strict shell mode.
- [x] 7.5 Run static checks that `Dockerfile` includes Chromium/ChromeDriver/runtime libraries, exposes port `5000`, and starts FastAPI only after the MCP readiness wait/check.
- [x] 7.6 Run static checks that `.dockerignore` excludes local-only files, caches, logs, and sensitive env files.
- [x] 7.7 Run static checks that `env.production.example` enumerates required secrets (`DATABASE_URL`, `COOKIE_SECRET`, `GOOGLE_API_KEY`, `RAPIDAPI_KEY`, `WEATHER_API_KEY`), optional `LANGSMITH_API_KEY`, non-secret host/language/currency/country overrides, and memory/LangMem/TrustMem/pgvector flags.
- [x] 7.8 Run static checks that deployment scripts/examples do not contain hard-coded real secrets and use Container Apps `secretref:` settings for required secrets, including `COOKIE_SECRET` in the migration job.
- [x] 7.9 Run static checks that the Container Apps web artifact defines one web container and five MCP sidecar containers, preserves `127.0.0.1:8001-8005`, and exposes only port `5000` through ingress.
- [x] 7.10 Run static checks that `docs/azure-container-apps-deployment.md` covers pgvector hard preflight before migration, migration order, custom domain/HTTPS, smoke checks, revision traffic, rollback, and staged memory rollout.
- [x] 7.11 Run static checks that `.github/workflows/azure-container-apps-deploy.sample.yml` covers build/push, migration, multi-container web update, worker/backfill job updates, smoke test, traffic shift, and rollback.
- [x] 7.12 Build or ACR-build the image and verify web, MCP sidecar, migration, worker, and backfill commands can start in the expected environment.
- [x] 7.13 Verify Chromium/ChromeDriver presence in the built image.
- [x] 7.14 Record any environment-specific blockers such as missing Azure credentials, Docker daemon, or pgvector support as deployment notes rather than code blockers.
