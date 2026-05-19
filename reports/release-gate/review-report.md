# P2/P3 Review Report

Date: 2026-05-19
Branch: `integration/p2`

## Backend Reviewer

Status: signed with fixes applied.

Findings addressed:

- SQLite checkpoint migration root lineage no longer self-parents root checkpoints.
  Fixed in `d7ef048` with `tests/test_sqlite_checkpoint_migration.py`.
- Merged memories with changed text reset `embedding_status` to `pending` before
  async re-embed completes. Fixed in `d7ef048` with `tests/test_memory_service.py`.
- Branch handoff decision helper now wraps synchronous service calls with
  `run_sync_route_call`. Fixed in `d7ef048` with
  `tests/unit/test_route_async_boundaries.py`.

Residual risk:

- No live Postgres integration run was available in this local environment.
- Live SSE pressure and long-session performance remain blocked by missing
  `wrk` and provider credentials.

## Frontend / Contract Reviewer

Status: signed.

Verified:

- `pnpm sdk:check` passed.
- `pnpm contract:check` passed.
- `make sdk-openapi-types-check` passed.
- Harness split operation IDs are consistent across route functions, OpenAPI,
  contract snapshot, and generated SDK types.

Residual risk:

- Review was scoped to contract drift and generated SDK freshness, not deeper
  runtime behavior of split harness endpoints.

## Lead Gate

Passed locally:

- P2 targeted suites: `162 passed, 8 skipped`.
- Full non-slow suite after reviewer fixes:
  `1515 passed, 15 skipped, 1 deselected`.
- `ruff check src`.
- `make lint-strict`.
- `make architecture-report`.
- `pnpm sdk:check`.
- `pnpm contract:check`.
- `make sdk-openapi-types-check`.

Blocked locally:

- `wrk` 200-concurrency SSE run: `wrk` is not installed.
- Eval baseline comparison and API live pressure: `OPENAI_API_KEY` is unset.
- 10% -> 50% -> 100% rollout: requires live deployment and observation windows.
