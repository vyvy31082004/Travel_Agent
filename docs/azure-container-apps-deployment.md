# Deploy VietTrip AI lên Azure Container Apps

Tài liệu này mô tả cách deploy hệ thống Travel Agent/VietTrip AI hiện tại lên Azure Container Apps theo OpenSpec change `add-azure-container-apps-deployment`.

## Kiến trúc

```text
Domain / HTTPS
  ↓
Azure Container Apps ingress
  ↓
viettrip-web Container App revision
  ├─ web: FastAPI / uvicorn :5000
  ├─ mcp-car: 127.0.0.1:8001
  ├─ mcp-excursion: 127.0.0.1:8002
  ├─ mcp-flight: 127.0.0.1:8003
  ├─ mcp-hotel: 127.0.0.1:8004
  └─ mcp-travel-planner: 127.0.0.1:8005
  ↓
Azure Database for PostgreSQL Flexible Server + pgvector
  ↓
Container Apps Jobs
  ├─ viettrip-migrate: alembic upgrade head
  ├─ viettrip-memory-worker: python src/memory_worker.py --once
  └─ viettrip-backfill-embeddings: python src/memory_worker.py --backfill-embeddings
```

Chỉ FastAPI port `5000` có external ingress. Các MCP sidecar ports `8001-8005` chỉ dùng localhost trong cùng Container App revision.

## Vì sao dùng MCP sidecars?

Code hiện tại dùng MCP SSE URLs hard-coded trên localhost. FastAPI build graph trong lifespan startup, nên MCP servers phải chạy trước hoặc cùng lúc với web process. Sidecar topology là lựa chọn ít thay đổi code nhất cho deployment đầu tiên.

## Prerequisites

- Azure CLI đã login.
- Docker hoặc dùng `az acr build`.
- Azure subscription có quyền tạo Resource Group, ACR, Container Apps, Log Analytics, PostgreSQL.
- PostgreSQL target hỗ trợ pgvector.
- Domain hoặc subdomain, khuyến nghị `app.<domain>`.

## Required secrets

Lưu bằng Azure Container Apps secrets, không commit real values:

- `DATABASE_URL`
- `COOKIE_SECRET`
- `GOOGLE_API_KEY`
- `RAPIDAPI_KEY`
- `WEATHER_API_KEY`
- optional `LANGSMITH_API_KEY`

File mẫu trong repo:

```text
env.production.example
```

## Non-secret runtime env

Các giá trị có thể đưa vào Container Apps env vars:

- `COOKIE_SECURE=true`
- `BOOKING_RAPIDAPI_HOST`
- `GEOCODING_RAPIDAPI_HOST`
- `GOOGLE_FLIGHT_RAPIDAPI_HOST`
- `BOOKING_LANGUAGE_CODE`
- `BOOKING_CURRENCY_CODE`
- `COUNTRY_CODE`
- `LONG_TERM_MEMORY_*`, bao gồm transition/applicability settings như `LONG_TERM_MEMORY_TRANSITION_PATH`, `LONG_TERM_MEMORY_TRANSITION_MODEL`, `LONG_TERM_MEMORY_ACTION_INFERENCE_ENABLED` và `LONG_TERM_MEMORY_APPLICABILITY_JUDGE_ENABLED`
- `RAPIDAPI_LOCK_FILE` (mặc định `/tmp/viettrip-rapidapi.lock`)
- `MCP_SIDECAR_*`
- tracing/debug flags

## pgvector là hard preflight

Migration hiện tại tạo extension và column vector:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
embedding vector(3072)
```

Vì vậy `LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED=false` chỉ là runtime safety flag, **không** giúp migration chạy trên database không hỗ trợ pgvector.

Trước khi chạy migration:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extname FROM pg_extension WHERE extname = 'vector';
SQL
```

Nếu preflight fail:

1. đổi Azure PostgreSQL version/region/tier có pgvector;
2. hoặc dùng PostgreSQL tự quản lý có pgvector;
3. không chạy `alembic upgrade head` vào target đó.

## Deployment scripts

Các script nằm ở:

```text
infra/azure/containerapps/
```

Copy biến mẫu:

```bash
cp infra/azure/containerapps/00-vars.example.sh infra/azure/containerapps/00-vars.local.sh
```

Điền real values trong `00-vars.local.sh`; file này không nên commit.

Thứ tự chạy:

```bash
./infra/azure/containerapps/01-create-foundation.sh
./infra/azure/containerapps/02-build-image.sh
./infra/azure/containerapps/04-create-migration-job.sh
./infra/azure/containerapps/05-run-migration-job.sh
./infra/azure/containerapps/03-deploy-web.sh
./infra/azure/containerapps/06-create-memory-worker-job.sh
./infra/azure/containerapps/08-smoke-test.sh
```

Backfill embeddings chỉ chạy sau khi pgvector, migration, embedding dimension và initial data đã ổn:

```bash
./infra/azure/containerapps/07-create-backfill-job.sh
az containerapp job start --name viettrip-backfill-embeddings --resource-group <rg>
```

Rollback web traffic:

```bash
ROLLBACK_REVISION=<old-revision> ./infra/azure/containerapps/09-rollback-web.sh
```

## Image/runtime commands

Một image dùng nhiều command. Image production cài từ `requirements.production.txt`, là subset runtime của `requirements.txt`; các dependency đánh giá/dev như Qdrant, sentence-transformers, pandas, openpyxl và pytest không được đưa vào production image nếu không được runtime import.

Một image dùng nhiều command:

| Runtime | Command |
| --- | --- |
| web | `/app/scripts/start-web-with-mcp-wait.sh` |
| mcp-car | `python src/mcp_servers/car/server.py` |
| mcp-excursion | `python src/mcp_servers/excursion/server.py` |
| mcp-flight | `python src/mcp_servers/flight/server.py` |
| mcp-hotel | `python src/mcp_servers/hotel/server.py` |
| mcp-travel-planner | `python src/mcp_servers/travel_planner/server.py` |
| migration | `alembic upgrade head` |
| memory worker | `python src/memory_worker.py --once` |
| backfill | `python src/memory_worker.py --backfill-embeddings` |

Dockerfile set `PYTHONPATH=/app/src` để các server/import hoạt động trong container.

Dockerfile cũng cài `Chromium`, `ChromeDriver`, và runtime libraries để giữ behavior hiện tại của Selenium car search. Nếu các dependencies này bị thiếu, các tool liên quan đến car search có thể fail dù web app vẫn start.

## Health and smoke tests

Liveness endpoint:

```text
GET /healthz
```

Expected:

```json
{"status":"ok"}
```

Smoke test tối thiểu:

1. `GET /healthz` public FQDN trả HTTP 200.
2. Trang `/` trả HTTP 200.
3. MCP ports `8001-8005` không public.
4. Chạy một representative chat/tool flow để xác nhận MCP-backed behavior.
5. Kiểm tra revision/traffic trước khi chuyển production traffic.

## Domain và HTTPS

Khuyến nghị dùng subdomain:

```text
app.example.com CNAME <container-app-fqdn>
```

Trong Azure Portal:

1. Vào Container App `viettrip-web`.
2. Settings → Custom domains.
3. Add custom domain.
4. Làm DNS verification.
5. Bind managed certificate.

## Rollout memory features

Ban đầu:

```env
LONG_TERM_MEMORY_RECALL_ENABLED=false
LONG_TERM_MEMORY_WRITE_ENABLED=false
LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED=false
LONG_TERM_MEMORY_EXTRACTOR=deterministic
LONG_TERM_MEMORY_VERIFIER=deterministic
```

Sau smoke test:

1. Bật recall.
2. Bật deterministic write + worker job.
3. Bật `LONG_TERM_MEMORY_VERIFIER=trustmem-dry-run`.
4. Sau khi audit ổn, bật `LONG_TERM_MEMORY_VERIFIER=trustmem`.
5. Dùng `LONG_TERM_MEMORY_EXTRACTOR=compare` trước khi chuyển `langmem`.
6. Verify pgvector + backfill embeddings rồi mới bật vector recall.

## Logs và vận hành

Web logs:

```bash
az containerapp logs show --name viettrip-web --resource-group <rg> --follow
```

Job executions:

```bash
az containerapp job execution list --name viettrip-memory-worker --resource-group <rg> -o table
```

Migration job logs/status cần kiểm tra sau mỗi deploy trước khi shift traffic.

## CI/CD production

Production hiện tại đã được deploy thủ công và không phụ thuộc GitHub Actions để tiếp tục chạy. Workflow dưới đây chỉ tự động hóa các lần deploy sau; việc cấu hình GitHub Environment `production` và merge vào `main` vẫn là bước vận hành chưa thực hiện.

Workflow thực tế nằm ở:

```text
.github/workflows/ci-cd.yml
```

Workflow sample cũ vẫn được giữ làm tài liệu tham khảo. Workflow production chạy CI trên pull request vào `main`, và CI + deployment khi push vào `main`. Job deploy dùng GitHub Environment `production`; hiện workflow được thiết kế tự động deploy sau CI theo quyết định vận hành, không yêu cầu approval thủ công.

Pipeline thực hiện:

1. pytest không dùng external database/live APIs (hai integration suites PostgreSQL cần được chạy riêng khi có database test);
2. compile và Docker build gate;
3. Azure login bằng GitHub OIDC;
4. build/push immutable image `viettrip-ai:ci-<commit-sha>`;
5. recreate và chờ đúng migration execution thành công;
6. deploy web + 5 MCP sidecars, memory worker và backfill job definition;
7. smoke test `/healthz`, `/`, `/login`, `/register`, private MCP ports;
8. xác minh revision ready mới nhận 100% traffic.

### GitHub Environment secrets

Tạo environment `production` và đặt các secret sau, không đặt trong repository files:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `DATABASE_URL`
- `COOKIE_SECRET`
- `GOOGLE_API_KEY`
- `RAPIDAPI_KEY`
- `WEATHER_API_KEY`
- `LANGSMITH_API_KEY` (có thể để rỗng nếu tracing tắt)

### GitHub Environment variables

Các biến resource dưới đây là cấu hình mục tiêu cho Environment `production`; chúng chưa được tạo tự động trong GitHub:

- `AZURE_RESOURCE_GROUP=viettrip-rg`
- `AZURE_ACR_NAME=viettripacr20260831`
- `AZURE_CONTAINERAPPS_ENV=viettrip-aca-env`
- `AZURE_LOG_ANALYTICS=viettrip-logs-jpe`
- `WEB_APP_NAME=viettrip-web`
- `MIGRATION_JOB_NAME=viettrip-migrate`
- `MEMORY_WORKER_JOB_NAME=viettrip-memory-worker`
- `BACKFILL_JOB_NAME=viettrip-backfill-embeddings`

### Azure OIDC federated identity

Tạo một Microsoft Entra application/service principal dành riêng cho GitHub Actions, cấp quyền tối thiểu cần thiết trên resource group production, rồi thêm federated credential với subject:

```text
repo:vyvy31082004/Travel_Agent:environment:production
```

Audience:

```text
api://AzureADTokenExchange
```

OIDC tránh lưu client secret dài hạn trong GitHub. Workflow cần `permissions: id-token: write` và chỉ deploy từ environment `production`.

### Branch protection

Khuyến nghị bảo vệ `main`:

- require pull request;
- require status check `Test and validate`;
- require branch up to date;
- không cho force push;
- chỉ cho deploy sau environment approval.

Do Azure for Students không cho ACR Tasks trong subscription hiện tại, workflow dùng Docker trên GitHub-hosted runner rồi `docker push` vào ACR.

Hai bước còn để sau:

1. tạo GitHub Environment `production` và nhập variables/secrets;
2. merge `ft/deploy` vào `main` để bật trigger production.

Trước khi hai bước này hoàn tất, tiếp tục dùng quy trình deploy thủ công trong phần `Deployment scripts`.
- optional `LANGSMITH_API_KEY`

Khuyến nghị dùng GitHub Environments với required reviewers/manual approval cho production trước khi chạy migration job và shift traffic.

## Rollback

Rollback ưu tiên:

1. Shift traffic về revision cũ.
2. Disable/pause worker nếu memory write có vấn đề.
3. Tắt flags:

```env
LONG_TERM_MEMORY_WRITE_ENABLED=false
LONG_TERM_MEMORY_VECTOR_SEARCH_ENABLED=false
```

Không downgrade schema nếu chưa có rollback migration riêng.

## Ghi chú bảo mật

- Không commit `00-vars.local.sh` hoặc real secrets.
- Dùng Container Apps `secretref:` cho secrets.
- Chỉ web app có public ingress.
- `COOKIE_SECURE=true` khi dùng HTTPS.
- `LONG_TERM_MEMORY_DEBUG_ENABLED=false` trong production.
- Azure Key Vault/private endpoint có thể làm ở phase hardening sau.
