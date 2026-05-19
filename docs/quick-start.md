# Quick Start

This guide expands on the shortest startup path from the root README.

```mermaid
flowchart LR
    Setup["Local setup"] --> Config[".focus_agent config"]
    Config --> Build["Build web bundle"]
    Build --> Start["make api / make serve-dev"]
    Start --> Postgres{"DATABASE_URI set?"}
    Postgres -- "No" --> Managed["Managed repo-local PostgreSQL"]
    Postgres -- "Yes" --> External["Use provided database"]
    Managed --> App["Open /app"]
    External --> App
    App --> Ready["Check /readyz"]
    Ready --> Observe["Open /metrics and observability pages"]
```

## 1. Local Setup

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[openai,dev]'
make setup-local
pnpm install --registry=https://registry.npmjs.org
```

`make setup-local` creates the default local config files under `.focus_agent/` if they are missing:

- `.focus_agent/local.env`
- `.focus_agent/models.toml`
- `.focus_agent/tools.toml`

Keep provider credentials in `.focus_agent/local.env` or another untracked local config file. The root `.env.example` is a reference for Docker Compose or manual shell exports; the local API startup path reads `.focus_agent/local.env` and process environment variables.

To add an OpenAI-compatible chat model for one deployment, add provider/model metadata to `.focus_agent/models.toml` and put only secret endpoint values in `.focus_agent/local.env`. Add entries to `src/focus_agent/defaults/models.toml` only when a model should become built-in for every fresh setup.

If `AUTH_ENABLED=true`, replace the sample `AUTH_JWT_SECRET` before startup.
The API refuses explicitly configured JWT secrets shorter than 32 characters or
containing placeholder text such as `change`, `example`, or `replace`, even for
local runs. Use a generated local secret, for example:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

## 2. Start The API

```bash
pnpm web:build
make api
```

Open:

- `http://127.0.0.1:8000/app`
- `http://127.0.0.1:8000/app/agent-team`
- `http://127.0.0.1:8000/app/agent/memory`
- `http://127.0.0.1:8000/app/admin/users`
- `http://127.0.0.1:8000/app/admin/audit-events`
- `http://127.0.0.1:8000/app/observability/overview`
- `http://127.0.0.1:8000/app/observability/trajectory`
- `http://127.0.0.1:8000/app/productivity/notes`
- `http://127.0.0.1:8000/app/productivity/tasks`
- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/readyz`
- `http://127.0.0.1:8000/metrics`

`/healthz` is a simple liveness check. `/readyz` reports runtime component readiness, including `memory_embedding_backend` and `memory_pgvector` when PostgreSQL memory embedding is configured. `/metrics` exposes Prometheus text metrics. The Web observability pages support request/trace correlation through trajectory data captured in Postgres.

## 3. Managed Local PostgreSQL

If `DATABASE_URI` is not already set, the local startup commands (`make api`, `make dev`, `make serve`, `make serve-dev`, and `make serve-prod`) manage a repo-local PostgreSQL for you and inject `DATABASE_URI` into the API process automatically.

That managed path:

- requires PostgreSQL CLI/server tools such as `initdb`, `pg_ctl`, `createdb`, and `psql`
- stops the managed database together with the service
- cleans up temporary runtime files
- keeps the repo-local Postgres data directory for reuse on the next run

If you explicitly export `DATABASE_URI` before startup, that value is preserved and the local-Postgres bootstrap is skipped.

If you prefer to launch `.venv/bin/focus-agent-api` directly, export `DATABASE_URI` yourself first. The raw binary does not start the managed local PostgreSQL helper for you.

The startup scripts also persist runtime settings to `.focus_agent/postgres/runtime.env` so ad-hoc commands can inspect the same database:

```bash
source .focus_agent/postgres/runtime.env
psql "$DATABASE_URI"
```

## 4. Memory Embedding And pgvector

PostgreSQL memory is the production canonical memory store. Memory embedding is enabled by default for Postgres-backed runs:

- `AGENT_MEMORY_EMBEDDING_ENABLED=true`
- `AGENT_MEMORY_EMBEDDING_BACKEND=auto`
- `AGENT_MEMORY_EMBEDDING_MODEL=embeddinggemma`
- `AGENT_MEMORY_EMBEDDING_DIMENSIONS=768`
- `AGENT_MEMORY_VECTOR_SEARCH_MODE=hybrid`

Local auto mode prefers Ollama `embeddinggemma`. The app does not run `ollama pull` for you:

```bash
ollama pull embeddinggemma
```

The chat provider may use `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`; the embedding provider normalizes that to Ollama native `http://127.0.0.1:11434` and calls `/api/tags` and `/api/embed`.

For cloud embeddings, configure an explicit OpenAI-compatible embedding backend instead of relying on the chat model provider:

```env
AGENT_MEMORY_EMBEDDING_BACKEND=openai_compatible
AGENT_MEMORY_EMBEDDING_MODEL=text-embedding-3-small
AGENT_MEMORY_EMBEDDING_DIMENSIONS=1536
AGENT_MEMORY_EMBEDDING_BASE_URL=https://api.openai.com/v1
AGENT_MEMORY_EMBEDDING_API_KEY_ENV=OPENAI_API_KEY
# or set AGENT_MEMORY_EMBEDDING_API_KEY directly in a local secret file
```

Use the maintenance CLI for read-only diagnostics and controlled index rebuilds:

```bash
focus-agent-memory-embedding doctor --database-uri "$DATABASE_URI"
focus-agent-memory-embedding rebuild --database-uri "$DATABASE_URI" --confirm-delete-index --backfill
```

`rebuild` drops and recreates only `focus_memory_embeddings`; it does not delete `focus_memories`, audit events, tombstones, candidates, or checkpoints.

Production environments should usually preinstall the Postgres `vector` extension with a privileged migration role and run the app with:

```env
AGENT_MEMORY_PGVECTOR_EXTENSION_MODE=required
```

## 5. Local Checkpoint Signatures

When the local pickle-backed fallback is used, checkpoint and store files are
loaded only if they are owned by the current user. Signature verification is on
by default: set `FOCUS_AGENT_CHECKPOINT_HMAC_KEY` to a stable local secret so
new pickle files get a matching `<file>.sig` HMAC signature and can be restored
on the next startup.

For a short rollback or migration window with existing unsigned local pickle
files, set:

```env
FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE=false
```

Remove that flag after the service rewrites the checkpoint files with
`FOCUS_AGENT_CHECKPOINT_HMAC_KEY` configured.

Local performance rollout flags are documented in `.env.example`. The defaults
enable DB pooling, checkpoint debounce, async memory embedding dispatch, and the
isolated tool pool. For rollback, set the specific flag off and restart:

```env
FOCUS_AGENT_DB_POOL_ENABLED=false
FOCUS_AGENT_CHECKPOINT_INCREMENTAL=false
FOCUS_AGENT_MEMORY_EMBED_ASYNC=false
FOCUS_AGENT_TOOL_POOL_ISOLATED=false
FOCUS_AGENT_CHECKPOINT_BACKEND=pickle
```

## 6. Runtime Coordination

Default local coordination is local-first:

- `BACKGROUND_JOB_EXECUTION=best_effort`
- `BACKGROUND_JOB_BACKEND=memory`
- `RUNTIME_THREAD_LOCK_TTL_SECONDS=300`
- `RUNTIME_THREAD_LOCK_HEARTBEAT_SECONDS=30`
- `BACKGROUND_JOB_CLAIM_TTL_SECONDS=300`

Durable background execution is useful for shared Postgres deployments and must be configured together:

```env
BACKGROUND_JOB_EXECUTION=durable
BACKGROUND_JOB_BACKEND=postgres
DATABASE_URI=postgresql://user:pass@host:5432/focus_agent
```

Durable jobs use claim tokens and claim heartbeats; thread turns use per-thread leases. Post-turn branch title/metadata refresh is scheduled after the chat turn lease is released, so immediate background workers should not contend with the active turn lock.

## 7. Branch Recommendations

Branch decision automation is disabled by default. To collect recommendation
evidence without changing chat behavior:

```env
AGENT_BRANCH_DECISION_ENABLED=true
AGENT_BRANCH_DECISION_MODE=shadow
AGENT_BRANCH_RECOMMENDATION_ENABLED=true
AGENT_BRANCH_RECOMMENDATION_MODE=shadow
```

To let high-confidence pre-turn recommendations appear as user-confirmed Branch
Action cards, use:

```env
AGENT_BRANCH_RECOMMENDATION_ENABLED=true
AGENT_BRANCH_RECOMMENDATION_MODE=suggest
AGENT_BRANCH_RECOMMENDATION_MIN_CONFIDENCE=0.72
```

`suggest` mode still does not fork silently; the user confirms or dismisses the
card in the chat transcript. See [Branch Decisions](branch-decisions.md) for the
full config, API, SDK, and validation contract.

## 8. Frontend Development

To develop the frontend against the local API:

```bash
make web-dev
```

Then set this in `.focus_agent/local.env` when you want `/app` to redirect to the Vite dev server:

```env
WEB_APP_DEV_SERVER_URL=http://127.0.0.1:5173/app
```

In that mode:

- frontend: `http://127.0.0.1:5173/app/`
- API: `http://127.0.0.1:8000`

The Web app defaults `VITE_FOCUS_AGENT_API_BASE_URL` to `window.location.origin`.
Set it only when the Vite page should call a different API origin.

## 8. One-Command Local Modes

- `make serve` / `make serve-dev`: frontend Vite dev server + backend API with reload
- `make serve-prod`: build the static frontend bundle first, then start only the backend without reload
- `make dev`: backend only with `API_RELOAD=1`

## 9. Local Auth

The built-in app routes unauthenticated users to `/app/auth/login` and preserves the protected target in `return_to`. In local development, the fastest browser path is:

1. Open `http://127.0.0.1:5173/app/` in Vite mode or `http://127.0.0.1:8000/app/` for the backend-served bundle.
2. Click `Demo 登录` to bootstrap the default local demo user and return to the requested app route.
3. Use the account control in the left sidebar to sign out.
4. To switch accounts, sign out first, then log in again with username/password, `Demo 登录`, or the Bearer Token panel.

For token-oriented testing, create a local demo access token:

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/demo-token \
  -H 'content-type: application/json' \
  -d '{"user_id": "researcher-1"}'
```

Paste the returned `access_token` into the login page's `使用 Bearer Token` panel and submit with `继续`. The `清空` action removes the locally stored token. Password registration creates a persistent local account, so reserve it for tests that explicitly need username/password behavior.

Registration and test-account notes:

- Usernames are trimmed and lowercased before uniqueness checks.
- Passwords must be at least 8 characters and include both letters and numbers.
- Self-registration creates an active `member`, not an admin.
- `AUTH_DEMO_TOKENS_ENABLED=true` is the local default; non-development deployments must disable demo tokens.
- In local/development mode, the first non-anonymous user can bootstrap as admin. You can also use `AUTH_BOOTSTRAP_ADMIN_USER_IDS` for explicit local admin IDs. Production database deployments should configure admin users deliberately.
- Admin user creation in `/app/admin/users` creates the user record; reset that user's password before testing username/password login.
- Logout clears the Web app's stored token, clears auth cookies, and revokes the refresh session. Access tokens and demo tokens are stateless, so a copied token remains usable until expiry or key rotation.

Admin Console local checks:

- `/app/admin/users` is the user directory, create-user drawer, and user-detail drawer.
- `/app/admin/audit-events` is the admin audit event browser.
- Admin status, role, session revoke, and password reset actions require a reason and write audit events.
- Bearer token scopes alone do not grant admin access; the persisted user role must allow it.

## 10. Browser Smoke Testing

The default `make ui-smoke` target expects the app URL from `scripts/ui_smoke_test.py`, which is usually the Vite dev URL. When you want to test the backend-served static bundle or disable auth for local debugging, start the API explicitly and pass the app URL:

```bash
AUTH_ENABLED=false WEB_APP_DEV_SERVER_URL= API_PORT=8001 ./scripts/run-api.sh
uv run python scripts/ui_smoke_test.py \
  --app-url http://127.0.0.1:8001/app/ \
  --health-url http://127.0.0.1:8001/healthz \
  --message '最近一周华钰矿业这只A股股票的表现怎么样？请联网查询并用中文简要说明。'
```

Use a real, tool-using prompt when changing streaming, transport validation, or web search behavior. The smoke script waits for the streamed assistant response to stabilize before asserting the final text.

For the Vite dev server, keep the trailing slash in `http://127.0.0.1:5173/app/`; `http://127.0.0.1:5173/app` may be handled differently by the dev server. The smoke script launches Chrome with a temporary user data directory, which avoids stale localStorage, extensions, and personal-profile auth state. If a manual browser opens a blank login page while the smoke script passes, retry with a clean profile or clear site data for `127.0.0.1` before treating it as an app regression.

## 11. Next Docs

- [Memory System v2](memory-system-v2.md)
- [Branch Decisions](branch-decisions.md)
- [Observability Runbook](observability-runbook.md)
- [Auth / Access](auth-access.md)
- [Admin Console](admin-console.md)
- [Development Guide](development.md)
- [Docker Deployment](docker-deployment.md)
- [Architecture](architecture.md)
