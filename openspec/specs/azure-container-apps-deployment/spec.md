# azure-container-apps-deployment Specification

## Purpose
TBD - created by archiving change add-azure-container-apps-deployment. Update Purpose after archive.
## Requirements
### Requirement: Production container image
The system SHALL provide a production Docker image for the current Travel Agent application, MCP servers, migration job, memory worker job, and embedding backfill job.

#### Scenario: Web image starts FastAPI
- **WHEN** the image is run with the web command
- **THEN** it starts `uvicorn app:app --app-dir src --host 0.0.0.0 --port 5000`
- **AND** exposes port `5000`

#### Scenario: Image contains migration and runtime code
- **WHEN** the image is built
- **THEN** it includes `requirements.txt`, `src`, `alembic`, and `alembic.ini`
- **AND** it can run `alembic upgrade head` without requiring source files outside the image

#### Scenario: Image preserves Selenium car search runtime
- **WHEN** the image is built
- **THEN** Chromium or Chrome, ChromeDriver, and required browser runtime libraries are installed in the image
- **AND** the current Selenium/Chrome-based car search behavior can run without requiring operators to add browser packages at deployment time

### Requirement: Docker build context hygiene
The system SHALL exclude local-only and sensitive files from the Docker build context.

#### Scenario: Docker build excludes development artifacts
- **WHEN** Docker builds the image
- **THEN** `.git`, `.venv`, `__pycache__`, pytest cache, local `.env`, logs, and OpenSpec scratch artifacts are excluded from the build context

### Requirement: Azure Container Apps web deployment
The system SHALL document and script an Azure Container App for the FastAPI web service.

#### Scenario: Web app has external ingress
- **WHEN** `viettrip-web` is deployed
- **THEN** it has external ingress enabled
- **AND** routes traffic only to target port `5000`
- **AND** uses `min-replicas=1` by default for chat responsiveness

#### Scenario: Web app uses secrets and feature flags
- **WHEN** `viettrip-web` is deployed
- **THEN** `DATABASE_URL`, `COOKIE_SECRET`, `GOOGLE_API_KEY`, `RAPIDAPI_KEY`, `WEATHER_API_KEY`, and optional `LANGSMITH_API_KEY` are supplied from Container Apps secrets
- **AND** host, language, currency, and country overrides are supplied as non-secret environment variables when needed
- **AND** memory, LangMem, TrustMem verifier, and pgvector rollout flags are supplied as non-secret environment variables

### Requirement: MCP sidecars in the web Container App revision
The system SHALL deploy MCP servers as sidecar containers in the same Azure Container App revision as the FastAPI web container.

#### Scenario: Web revision contains all MCP sidecars
- **WHEN** `viettrip-web` is created or updated
- **THEN** the Container App revision contains one web container and five MCP sidecar containers
- **AND** the sidecars run the car, excursion, flight, hotel, and travel-planner MCP server commands from the same image revision as the web container

#### Scenario: Localhost MCP ports are preserved
- **WHEN** the web container connects to MCP servers
- **THEN** car MCP is reachable at `127.0.0.1:8001`
- **AND** excursion MCP is reachable at `127.0.0.1:8002`
- **AND** flight MCP is reachable at `127.0.0.1:8003`
- **AND** hotel MCP is reachable at `127.0.0.1:8004`
- **AND** travel-planner MCP is reachable at `127.0.0.1:8005`
- **AND** existing MCP SSE URLs using `http://127.0.0.1:<port>/sse` remain valid

#### Scenario: MCP sidecars are not publicly exposed
- **WHEN** `viettrip-web` ingress is configured
- **THEN** only FastAPI target port `5000` has public ingress
- **AND** ports `8001`, `8002`, `8003`, `8004`, and `8005` are not configured as external ingress targets

#### Scenario: Web startup waits for MCP readiness
- **WHEN** the web container starts in Azure Container Apps
- **THEN** it performs a bounded startup wait/check for all five MCP sidecar ports or SSE endpoints on `127.0.0.1:8001-8005`
- **AND** it does not start FastAPI graph construction or MCP client usage before those checks succeed
- **AND** it exits non-zero after the documented timeout if any MCP sidecar remains unreachable

#### Scenario: Multi-container web revision passes smoke validation
- **WHEN** a new `viettrip-web` revision is deployed
- **THEN** deployment validation checks public FastAPI ingress on port `5000` and `GET /healthz`
- **AND** validates a representative MCP-backed behavior after the startup wait succeeds
- **AND** verifies MCP sidecar ports `8001-8005` are not public ingress targets

### Requirement: Manual migration job
The system SHALL define Alembic migration as a manual Azure Container Apps Job.

#### Scenario: Migration job runs before web revision rollout
- **WHEN** a new application image is deployed
- **THEN** the migration job can be started manually or by CI/CD before web traffic is shifted to the new revision
- **AND** the web container does not run migrations automatically on startup

#### Scenario: Migration job receives required settings
- **WHEN** the migration job is created or run
- **THEN** it receives `DATABASE_URL` and `COOKIE_SECRET` through Container Apps secret references
- **AND** it receives any additional settings required by current application settings validation without hard-coded real secrets

#### Scenario: Migration job has no ingress
- **WHEN** `viettrip-migrate` is configured
- **THEN** it is a manual Container Apps Job
- **AND** it exposes no public ingress

### Requirement: Scheduled memory worker job
The system SHALL define a scheduled Azure Container Apps Job for long-term memory consolidation.

#### Scenario: Worker processes pending jobs periodically
- **WHEN** the scheduled job runs
- **THEN** it executes `python src/memory_worker.py --once`
- **AND** uses the same image revision and required environment/secrets as the web app
- **AND** has no external ingress

#### Scenario: Worker concurrency is conservative
- **WHEN** the worker job is configured
- **THEN** parallelism is `1` by default
- **AND** replica completion count is `1` by default
- **AND** the schedule is documented as configurable based on expected chat volume

### Requirement: Manual embedding backfill job
The system SHALL document a manual Azure Container Apps Job for pgvector embedding backfill.

#### Scenario: Backfill job is started after pgvector verification
- **WHEN** pgvector extension, migration, and embedding dimension verification are complete
- **THEN** the backfill job can run `python src/memory_worker.py --backfill-embeddings`
- **AND** failures are inspectable through Container Apps job logs

#### Scenario: Backfill job has conservative execution settings
- **WHEN** `viettrip-backfill-embeddings` is configured
- **THEN** it is a manual Container Apps Job
- **AND** parallelism is `1` by default
- **AND** it has no external ingress

### Requirement: PostgreSQL and pgvector readiness
The deployment SHALL require PostgreSQL connectivity and explicitly verify pgvector before migration and vector recall.

#### Scenario: pgvector preflight succeeds before migration
- **WHEN** an operator prepares the production database for the current Alembic head
- **THEN** deployment documentation or scripts instruct the operator to run `CREATE EXTENSION IF NOT EXISTS vector;`
- **AND** verify `SELECT extname FROM pg_extension WHERE extname = 'vector';` returns `vector`
- **AND** only then run `alembic upgrade head` through the migration job

#### Scenario: Database migration initializes schema
- **WHEN** the migration job runs against `DATABASE_URL` after pgvector preflight succeeds
- **THEN** Alembic applies all existing migrations for auth, sessions, checkpoints, result store, long-term memory, and pgvector embedding tables

#### Scenario: pgvector is unavailable
- **WHEN** `CREATE EXTENSION IF NOT EXISTS vector` fails or `pg_extension` does not contain `vector`
- **THEN** deployment documentation instructs operators to stop before running the current Alembic head
- **AND** choose a supported Azure PostgreSQL version/region/tier or use self-managed PostgreSQL with pgvector
- **AND** explains that setting `LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED=false` is not sufficient to bypass the current migration requirement

### Requirement: Production environment inventory
The deployment artifacts SHALL enumerate all required production secrets and relevant non-secret runtime settings.

#### Scenario: Required secrets are documented
- **WHEN** an operator reviews the production environment example or deployment documentation
- **THEN** it lists `DATABASE_URL`, `COOKIE_SECRET`, `GOOGLE_API_KEY`, `RAPIDAPI_KEY`, and `WEATHER_API_KEY` as required secrets
- **AND** lists `LANGSMITH_API_KEY` as optional
- **AND** scripts reference these values through Container Apps `secretref:` settings rather than hard-coded real secret values

#### Scenario: Non-secret overrides are documented
- **WHEN** an operator reviews the production environment example or deployment documentation
- **THEN** it lists non-secret host overrides `BOOKING_RAPIDAPI_HOST`, `GOOGLE_FLIGHT_RAPIDAPI_HOST`, and `GEOCODING_RAPIDAPI_HOST`
- **AND** non-secret locale overrides `BOOKING_LANGUAGE_CODE`, `BOOKING_CURRENCY_CODE`, and `COUNTRY_CODE`
- **AND** cookie/debug, database pool, retention, memory, LangMem, TrustMem, and pgvector feature flags and thresholds used by the application settings

### Requirement: Health endpoint for container probes
The system SHALL expose a lightweight health endpoint for Azure Container Apps probes.

#### Scenario: Health probe succeeds
- **WHEN** Azure Container Apps or an operator calls `GET /healthz`
- **THEN** the app returns an HTTP 200 response with a simple status payload

### Requirement: Domain and HTTPS guidance
The deployment documentation SHALL include custom domain and HTTPS setup for Azure Container Apps.

#### Scenario: Subdomain is configured
- **WHEN** the operator chooses a subdomain such as `app.example.com`
- **THEN** the documentation describes adding a CNAME to the Container App FQDN
- **AND** binding the custom hostname and managed certificate in Azure Container Apps

### Requirement: Concrete Azure deployment scripts
The system SHALL provide concrete, reviewable Azure CLI helper scripts under `infra/azure/containerapps/` for manual deployment operations.

#### Scenario: Scripts use safe shell conventions
- **WHEN** deployment scripts are added under `infra/azure/containerapps/`
- **THEN** each shell script uses strict shell mode with `set -euo pipefail`
- **AND** reads operator-specific names, locations, images, and secrets from variables or placeholders
- **AND** does not contain hard-coded real secret values

#### Scenario: Scripts cover deployment lifecycle
- **WHEN** an operator follows the scripts
- **THEN** `infra/azure/containerapps/00-vars.example.sh` defines placeholder-only variables and secret names with no real secrets
- **AND** `infra/azure/containerapps/01-create-foundation.sh` creates or updates the resource group, Azure Container Registry, Log Analytics workspace, and Container Apps Environment
- **AND** `infra/azure/containerapps/02-build-image.sh` builds and pushes the single image to ACR
- **AND** `infra/azure/containerapps/03-deploy-web.sh` creates or updates the multi-container `viettrip-web` app with one web container, five MCP sidecars, external ingress only on port `5000`, startup wait, secret references, revision traffic controls, and localhost MCP URLs/ports
- **AND** `infra/azure/containerapps/04-create-migration-job.sh` creates or updates the manual migration job with `DATABASE_URL` and `COOKIE_SECRET` secret references
- **AND** `infra/azure/containerapps/05-run-migration-job.sh` runs the migration job only after pgvector preflight and shows how to inspect status/logs
- **AND** `infra/azure/containerapps/06-create-memory-worker-job.sh` creates or updates the scheduled worker job with parallelism `1`, replica completion count `1`, no ingress, and secret references
- **AND** `infra/azure/containerapps/07-create-backfill-job.sh` creates or updates the manual backfill job with parallelism `1`, no ingress, and secret references
- **AND** `infra/azure/containerapps/08-smoke-test.sh` smoke checks the public web revision, `/healthz`, revision identity/traffic, and representative MCP-backed behavior without exposing MCP ports
- **AND** `infra/azure/containerapps/09-rollback-web.sh` shifts revision traffic back to a previous revision and documents worker-disable rollback guidance

### Requirement: CI/CD deployment path
The system SHALL provide a CI/CD-ready GitHub Actions workflow sample for building, migrating, and updating Container Apps while keeping CI/CD adoption optional for operators.

#### Scenario: GitHub Actions deployment sample is present
- **WHEN** deployment artifacts are implemented
- **THEN** `.github/workflows/azure-container-apps-deploy.sample.yml` exists as a CI/CD-ready sample artifact
- **AND** documents required GitHub secrets, Azure federated login or service principal authentication, environment protection, and manual approval considerations for production

#### Scenario: GitHub Actions deployment is used
- **WHEN** code is pushed to the deployment branch and the optional workflow is enabled
- **THEN** the workflow can build and push an image to Azure Container Registry
- **AND** create or update Container Apps jobs and the multi-container web app using the same image revision
- **AND** run or trigger the migration job before traffic shift
- **AND** update the multi-container web Container App and worker jobs to the new image
- **AND** smoke test the new web revision
- **AND** shift traffic or roll back using Azure Container Apps revisions

#### Scenario: Manual deployment remains supported
- **WHEN** operators choose not to use CI/CD
- **THEN** the Azure CLI scripts and deployment documentation provide an equivalent manual path
- **AND** there is no unresolved open question about whether a CI/CD-ready sample exists

### Requirement: Staged memory feature rollout
The deployment documentation SHALL define a safe rollout order for long-term memory features.

#### Scenario: Initial production deployment
- **WHEN** the web app is first deployed
- **THEN** memory write, vector recall, LangMem, and TrustMem gated mode are disabled or conservative by default

#### Scenario: Memory features are enabled progressively
- **WHEN** initial smoke tests pass
- **THEN** operators can enable deterministic memory write, TrustMem dry-run, TrustMem gated mode, LangMem, and pgvector recall in documented stages

### Requirement: Deployment artifact validation
The change SHALL define static and runtime validation expectations for the deployment artifacts.

#### Scenario: Static artifact validation is run
- **WHEN** deployment artifacts are implemented
- **THEN** OpenSpec validation passes for `add-azure-container-apps-deployment`
- **AND** `Dockerfile` is checked for Chromium or Chrome, ChromeDriver, runtime libraries, port `5000`, and the startup wait command before FastAPI starts
- **AND** `.dockerignore` is checked for local-only, cache, log, and sensitive file exclusions
- **AND** `env.production.example` is checked for all required secrets, optional `LANGSMITH_API_KEY`, non-secret host/language/currency/country overrides, and memory/LangMem/TrustMem/pgvector flags
- **AND** shell scripts under `infra/azure/containerapps/` are checked for syntax and strict shell mode
- **AND** deployment artifacts are checked to confirm real secret values are not committed and required secrets use `secretref:` references
- **AND** deployment documentation is checked for pgvector hard preflight, migration order, custom domain/HTTPS, smoke checks, traffic shift, and rollback
- **AND** `.github/workflows/azure-container-apps-deploy.sample.yml` is checked for build, migration, multi-container web update, worker/backfill job update, smoke, traffic shift, and rollback steps
- **AND** the Azure Container Apps web artifact is checked to include one web container and five MCP sidecar containers

#### Scenario: Runtime deployment validation is documented
- **WHEN** operators validate a staging deployment
- **THEN** they can verify the container image starts the web command, all five MCP sidecar commands, `alembic upgrade head`, `python src/memory_worker.py --once`, and `python src/memory_worker.py --backfill-embeddings`
- **AND** they can verify Chromium/ChromeDriver binaries are present in the image
- **AND** they can verify `/healthz`, revision traffic, smoke checks, job logs, and rollback commands
