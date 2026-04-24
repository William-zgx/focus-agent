# Development Guide

This guide collects the day-to-day development and validation commands that do not belong in the root README.

## Command Matrix

```bash
make help
make install
make setup-local
make api
make dev
make serve
make serve-dev
make serve-prod
make web-dev
make web-build
make sdk-check
make sdk-build
make ci-test
make ci
make ui-smoke
make ui-smoke-observability
```

## Common Flows

### Backend only

- `make api`: start the API server
- `make dev`: start the API server with `API_RELOAD=1`

### Full local development

- `make serve` / `make serve-dev`: run frontend Vite dev server and backend API together
- `make serve-prod`: build the frontend bundle first, then run only the backend without reload

### Frontend only

- `make web-dev`: start the React frontend dev server
- `make web-build`: build the bundle that FastAPI serves at `/app`

## Validation

Recommended validation ladder:

1. Broad changes:

```bash
make ci
```

2. If the frontend SDK changed:

```bash
make sdk-check
make sdk-build
```

3. If the Web App changed:

```bash
make web-check
make web-build
```

4. If browser-level chat, branch tree, or merge-review flows changed:

```bash
make ui-smoke
```

5. If observability pages or seeded trajectory browser flows changed:

```bash
make ui-smoke-observability
```

6. If trajectory observability contracts changed:

```bash
uv run pytest tests/test_api_middleware.py tests/test_api_trajectory_observability.py tests/test_api_trajectory_actions.py tests/test_trajectory_cli.py
```

7. If Agent role routing, memory curator, tool router, context engineering, helper-model fallback, or governance observability changed:

```bash
uv run pytest tests/test_agent_roles.py tests/test_agent_governance.py tests/test_agent_delegation.py tests/test_agent_context_engineering.py tests/eval/test_agent_arch_suite.py tests/eval/test_agent_governance_suite.py tests/eval/test_agent_delegation_suite.py tests/eval/test_agent_context_suite.py
uv run python -m tests.eval --suite agent_arch --concurrency 1
uv run python -m tests.eval --suite agent_governance --concurrency 1
uv run python -m tests.eval --suite agent_delegation --concurrency 1
uv run python -m tests.eval --suite agent_context --concurrency 1
```

If local test collection fails because the active `.venv` `psycopg` install cannot load `libpq`, use the focused stub workaround for observability checks:

```bash
PYTHONPATH=/tmp/psycopg_stub .venv/bin/pytest \
  tests/test_api_middleware.py \
  tests/test_metadata.py \
  tests/test_trajectory_observability.py \
  tests/test_api_trajectory_observability.py \
  tests/test_chat_service.py
```

`make ci-test` runs pytest with `FOCUS_AGENT_LOCAL_ENV_FILE` pointed at a missing file, which mirrors GitHub Actions more closely and prevents repo-local `.focus_agent/local.env` secrets from masking setup gaps.

## Related Docs

- [Quick Start](quick-start.md)
- [Docker Deployment](docker-deployment.md)
- [Architecture](architecture.md)
- [Agent Role Routing](agent-role-routing.md)
- [Roadmap](roadmap.md)
