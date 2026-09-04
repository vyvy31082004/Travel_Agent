from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dockerfile_contains_runtime_contract():
    dockerfile = read("Dockerfile")
    assert "python:3.12-slim" in dockerfile
    assert "chromium" in dockerfile
    assert "chromium-driver" in dockerfile
    assert "PYTHONPATH=/app/src" in dockerfile
    assert "requirements.production.txt" in dockerfile
    assert "COPY src ./src" in dockerfile
    assert "COPY alembic ./alembic" in dockerfile
    assert "EXPOSE 5000" in dockerfile
    assert "start-web-with-mcp-wait.sh" in dockerfile
    assert "run-memory-worker-once.sh" in dockerfile
    assert "run-memory-embedding-backfill.sh" in dockerfile
    production_requirements = read("requirements.production.txt")
    assert "selenium" in production_requirements
    assert "pgvector" in production_requirements
    assert "qdrant-client" not in production_requirements
    assert "sentence-transformers" not in production_requirements


def test_dockerignore_excludes_local_and_sensitive_artifacts():
    dockerignore = read(".dockerignore")
    for pattern in [".git", ".venv", "__pycache__", ".pytest_cache", ".env", "*.pem", "*.key", "*.log"]:
        assert pattern in dockerignore


def test_production_env_example_documents_required_variables():
    env = read("env.production.example")
    for name in [
        "DATABASE_URL",
        "COOKIE_SECRET",
        "GOOGLE_API_KEY",
        "RAPIDAPI_KEY",
        "WEATHER_API_KEY",
        "COOKIE_SECURE=true",
        "BOOKING_RAPIDAPI_HOST",
        "GEOCODING_RAPIDAPI_HOST",
        "GOOGLE_FLIGHT_RAPIDAPI_HOST",
        "BOOKING_LANGUAGE_CODE",
        "BOOKING_CURRENCY_CODE",
        "COUNTRY_CODE",
        "LONG_TERM_MEMORY_RECALL_ENABLED",
        "LONG_TERM_MEMORY_WRITE_ENABLED",
        "LONG_TERM_MEMORY_VERIFIER",
        "LONG_TERM_MEMORY_TRANSITION_PATH",
        "LONG_TERM_MEMORY_TRANSITION_MODEL",
        "LONG_TERM_MEMORY_ACTION_INFERENCE_ENABLED",
        "LONG_TERM_MEMORY_APPLICABILITY_JUDGE_ENABLED",
        "RAPIDAPI_LOCK_FILE",
        "LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED",
    ]:
        assert name in env
    assert "replace-with" in env


def test_mcp_wait_scripts_cover_all_sidecar_ports():
    wait_py = read("scripts/wait_for_mcp.py")
    start_sh = read("scripts/start-web-with-mcp-wait.sh")
    assert "8001,8002,8003,8004,8005" in wait_py
    assert "socket.create_connection" in wait_py
    assert "MCP_STARTUP_TIMEOUT_SECONDS" in wait_py
    assert "set -euo pipefail" in start_sh
    assert "wait_for_mcp.py" in start_sh
    assert "uvicorn app:app" in start_sh


def test_azure_scripts_are_concrete_and_secret_safe():
    script_dir = ROOT / "infra" / "azure" / "containerapps"
    expected = [
        "00-vars.example.sh",
        "01-create-foundation.sh",
        "02-build-image.sh",
        "03-deploy-web.sh",
        "04-create-migration-job.sh",
        "05-run-migration-job.sh",
        "06-create-memory-worker-job.sh",
        "07-create-backfill-job.sh",
        "08-smoke-test.sh",
        "09-rollback-web.sh",
        "10-stop-stack.sh",
        "11-start-stack.sh",
    ]
    for name in expected:
        path = script_dir / name
        assert path.exists(), name
        content = path.read_text(encoding="utf-8")
        assert "set -euo pipefail" in content
        assert "secretref" in content.lower() or name in {
            "00-vars.example.sh",
            "01-create-foundation.sh",
            "02-build-image.sh",
            "05-run-migration-job.sh",
            "08-smoke-test.sh",
            "09-rollback-web.sh",
            "10-stop-stack.sh",
            "11-start-stack.sh",
        }
        assert "real-secret" not in content.lower()

    build_image = read("infra/azure/containerapps/02-build-image.sh")
    assert "az acr build" in build_image
    assert "docker build" in build_image
    assert "docker push" in build_image
    assert "ACR Tasks build was unavailable" in build_image

    deploy_web = read("infra/azure/containerapps/03-deploy-web.sh")
    for container_name in ["mcp-car", "mcp-excursion", "mcp-flight", "mcp-hotel", "mcp-travel-planner"]:
        assert container_name in deploy_web
    assert "targetPort: 5000" in deploy_web
    assert "start-web-with-mcp-wait.sh" in deploy_web
    assert 'value: "/tmp/viettrip-rapidapi.lock"' in deploy_web
    assert '/start?api-version=2024-03-01' in deploy_web
    assert 'did not reach Running after deployment' in deploy_web
    worker = read("infra/azure/containerapps/06-create-memory-worker-job.sh")
    backfill = read("infra/azure/containerapps/07-create-backfill-job.sh")
    assert '--command "scripts/run-memory-worker-once.sh"' in worker
    assert '--command "scripts/run-memory-embedding-backfill.sh"' in backfill
    assert 'RAPIDAPI_LOCK_FILE=/tmp/viettrip-rapidapi.lock' in worker
    assert 'RAPIDAPI_LOCK_FILE=/tmp/viettrip-rapidapi.lock' in backfill
    assert 'az containerapp job delete' in worker
    assert 'az containerapp job delete' in backfill
    migration = read("infra/azure/containerapps/04-create-migration-job.sh")
    migration_runner = read("infra/azure/containerapps/05-run-migration-job.sh")
    assert 'az containerapp job delete' in migration
    assert 'run_vector_preflight >&2' in migration_runner
    assert '--query name' in migration_runner


def test_docs_and_workflow_cover_deployment_lifecycle():
    docs = read("docs/azure-container-apps-deployment.md")
    workflow = read(".github/workflows/azure-container-apps-deploy.sample.yml")
    production_workflow = read(".github/workflows/ci-cd.yml")
    smoke = read("infra/azure/containerapps/08-smoke-test.sh")
    assert 'curl --max-time 20 --fail' in smoke
    assert 'for attempt in $(seq 1 36)' in smoke
    assert 'healthz did not become ready' in smoke
    assert 'Root page GET succeeded' in smoke
    assert '--head' not in smoke
    for term in [
        "MCP sidecar",
        "pgvector",
        "CREATE EXTENSION IF NOT EXISTS vector",
        "RAPIDAPI_KEY",
        "WEATHER_API_KEY",
        "Chromium",
        "ChromeDriver",
        "ROLLBACK_REVISION",
        "LONG_TERM_MEMORY_VERIFIER=trustmem-dry-run",
    ]:
        assert term in docs
    for term in ["az acr build", "viettrip-migrate", "viettrip-memory-worker", "smoke", "rollback"]:
        assert term in workflow
    for term in ["azure/login@v2", "id-token: write", "docker push", "04-create-migration-job.sh", "05-run-migration-job.sh", "03-deploy-web.sh", "08-smoke-test.sh", "/login", "/register", "japanwest"]:
        assert term in production_workflow
    assert "japaneast" not in production_workflow
