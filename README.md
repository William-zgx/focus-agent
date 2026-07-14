# Focus Agent

---

**English** | [中文](README.zh-CN.md)

[![CI](https://github.com/William-zgx/focus-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/William-zgx/focus-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Node.js 20+](https://img.shields.io/badge/node.js-20%2B-339933?logo=node.js&logoColor=white)

![Focus Agent showcase](docs/assets/focus-agent-readme-hero.svg)

Focus Agent is a **self-hosted, branch-aware Agent workbench and platform reference** for long AI workflows. The core idea is simple: keep the main thread focused, explore in temporary branches, and merge conclusions back only when they are ready.

Around that branching workflow, the repository ships a full product surface: streaming chat APIs, a React web app, a typed frontend SDK, access control, Admin operations, observability, memory and retrieval, Productivity tools, Agent Team collaboration, sandbox execution, release/eval evidence, and an optional Android shell.

> Positioning detail, scale snapshot, fit/non-fit, and runtime spines:
> **[docs/project-overview.md](docs/project-overview.md)**

## Project Status

Focus Agent is an **open-source platform reference and self-hosted workbench**, not a hosted SaaS product. It is intended for local development, product prototyping, and adaptation into team-owned branch-aware AI workspaces.

Treat it as a **medium-sized monorepo** (backend + typed SDK + React app + optional Android target + broad OpenAPI surface), not a weekend chat template. Current scale numbers and product layers live in [project-overview.md](docs/project-overview.md) so they stay in one place. The branch workflow, backend API, SSE stream contract, frontend SDK, and documented Web surfaces are protected by contract, build, and smoke checks. Deployment choices such as model provider, auth policy, PostgreSQL hosting, observability backend, and release process remain explicit configuration decisions for each adopter.

### Hardened And Validated Baseline

- **Durable local state:** the maintained `make api` / `make dev` / `make serve*` entry points still manage a repo-local PostgreSQL when `DATABASE_URI` is unset. Direct API startup without `DATABASE_URI` instead persists app-state plus LangGraph checkpoints/store in local SQLite; signed legacy pickle is compatibility-only and fails closed on owner or HMAC verification errors. See [Quick Start](docs/quick-start.md) and [Architecture](docs/architecture.md).
- **Security boundaries:** cookie-authenticated mutations enforce same-origin browser metadata and use CSRF double-submit when non-development clients omit that metadata; disabled users are rejected on protected requests and lose refresh sessions; governance trajectories are owner-scoped unless a global permission is granted; `web_fetch` combines DNS validation with fixed-IP transport to resist rebinding SSRF. See [Security](SECURITY.md) and [Auth / Access](docs/auth-access.md).
- **Production evidence:** schema-v2 evidence packs bind reports to commit, deployment ID, deployment version, environment, and timezone-aware generation time; production mode validates identity and freshness instead of accepting an unrelated or stale report. See [Release Checklist](docs/release-checklist.md) and [CI Release Gate](docs/ci/github-actions-release-gate.md).
- **Executable UI and mobile gates:** a dedicated workflow runs real Chrome chat and observability interactions, while CI builds, lints, and unit-tests the Android debug project. Android also has bounded/cancellable native HTTP, one-shot cold/hot deep-link delivery, secure key storage, and disabled Capacitor bridge logging. See [Validation](docs/validation-runbook.md) and [Android](docs/android.md).
- **Resilient streams:** ended in-memory streams are reclaimed after a replay window; SDK reconnects deduplicate event IDs across connections and raise `FocusAgentIncompleteStreamError` if EOF arrives without a terminal event. See [Streaming Contract](docs/streaming-contract.md) and the [Frontend SDK](frontend-sdk/README.md).
- **Measured architecture debt:** the architecture gate blocks non-generated files above 800 lines with no grandfathered large-file debt. Compatibility debt is tracked by stable item ID; the current baseline contains **169** intentional 1.x items, including public facades that remain until their 2.0 removal criteria are met. See the [architecture](docs/architecture-debt-baseline.json) and [compatibility](docs/compat-debt-baseline.json) baselines.
- **App Postgres schema:** application schema version is **v19** (Agent Team v2 tables plus earlier productivity / branch-decision / embedding-status migrations). See [Architecture §14](docs/architecture.md).

### Fit And Non-Fit

| Better fit | Usually a poor fit |
|------------|--------------------|
| Self-hosted AI workbench with audit, replay, and release evidence | Minimal LangGraph + single chat page weekend project |
| Teams that want branch/merge as a first-class workflow | “Install once, enterprise agent employee” expectations |
| Product/platform groups that can own auth, Postgres, and stream contracts | Teams with no capacity to maintain a medium monorepo |
| Typed SDK + observability closed loop for near-production paths | Need for turnkey enterprise IdP / multi-region HA out of the box |

Honest boundary: **platform completeness is currently stronger than end-to-end agent outcome evidence.** Eval, golden failures, cost/latency profiles, and multi-agent quality gates are still open work. See [Roadmap](docs/roadmap.md).

## Why Focus Agent

Most agent demos assume one chat box and one final answer. Focus Agent is built around a different idea: serious research, debugging, writing, and review work are not linear.

Instead of forcing every detour into one noisy thread, Focus Agent treats the main thread as shared progress and branches as temporary workspaces for exploration, verification, and comparison. Branch recommendations never silently fork; they create user-confirmed Branch Action cards.

## Core Capabilities

- Branch-aware conversations with controlled merge-back
- AI-assisted branch decisions and pre-turn branch recommendations that produce user-confirmed Branch Action cards
- Streaming chat APIs (default harness path: `/v2/threads/.../runs[/stream]`) and a built-in React web app at `/app`
- Current context-window usage in the composer, with non-destructive manual and automatic compaction
- Agent Team Mission Runner for goal-driven multi-agent planning, task evidence, and final-answer synthesis (v2 execution is flag-gated; see [Agent Team v2 rollout](docs/agent-team-v2-rollout.md))
- Owner-scoped Productivity workbench (notes + tasks) with source trace (`/app/productivity/notes`, `/app/productivity/tasks`)
- Split observability flow: `/app/observability/overview` for trends and hotspots, `/app/observability/trajectory` for single-turn review
- Access control, Admin Console, capability-centered settings, Zvec-backed retrieval/RAG, memory pipeline, governance feedback trends, and typed frontend SDK
- Quarantined tool/protocol streams so `message.delta` only carries confirmed visible assistant text
- Built-in repo read/edit, git, web, artifact, memory, productivity, and Skill catalog tools with guarded workspace command execution
- Thread-level sandbox execution for workspace commands and declared Skill entrypoints, with Docker-first isolation and explicit local fallback metadata
- Admin-managed runtime settings for model connections, tool providers, Skill enablement, Agent behavior, security/runtime policy, and low-frequency advanced options

## Repository Layout

| Path | Purpose |
|------|---------|
| `src/focus_agent/` | Python backend: API, `AppRuntime`, harness, LangGraph engine, services, persistence, tools, memory, retrieval, observability |
| `apps/web/` | React Web App served under `/app` (plus Android local-runtime modules) |
| `frontend-sdk/` | Typed TypeScript SDK for API, SSE, and stream reducer integration |
| `android/` | Capacitor Android shell around the web target |
| `docs/` | Architecture, setup, deployment, feature, contract, and operations documentation |
| `migrations/` | Alembic migrations for PostgreSQL-backed deployments |
| `scripts/` | Local setup, validation, release, screenshot, and maintenance helpers |
| `tests/` | Python, contract, integration, eval, and frontend regression tests |
| `compose.yaml`, `compose.prod.yaml` | Local and production-oriented Docker Compose entry points |

## Quick Start

Requirements:

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ if you want to build the web frontend and SDK
- Corepack with pnpm 9.15.9 (`corepack enable && corepack prepare pnpm@9.15.9 --activate`)
- Node.js 22+, JDK 21, and Android Studio / Android SDK if you want to build the Android app

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[openai,dev]'
make setup-local
pnpm install --registry=https://registry.npmjs.org
pnpm web:build
make api
```

For full-stack local development with hot reload (API + Vite), use `make serve-dev` after the same setup steps. Details are in [docs/quick-start.md](docs/quick-start.md).

`make setup-local` creates `.focus_agent/local.env`, `.focus_agent/models.toml`, and `.focus_agent/tools.toml`.
The root `.env.example` is a reference for Compose or manual shell exports; the local API startup path reads `.focus_agent/local.env` and process environment variables.

`make api` and the other maintained local `make` entry points manage a
repo-local PostgreSQL when `DATABASE_URI` is not explicitly exported. The raw
API binary does not start that helper; without `DATABASE_URI`, it uses durable
local SQLite app-state, checkpoints, and store instead. The exact startup and
migration boundaries are documented in [docs/quick-start.md](docs/quick-start.md).

Model/provider metadata is loaded from the packaged default catalog and can be
overridden locally through `.focus_agent/models.toml`; keep provider secrets in
`.focus_agent/local.env`. See [docs/quick-start.md](docs/quick-start.md) for the
custom OpenAI-compatible model path.

Skill runtime settings are local-first as well. Bundled skills provide the
baseline catalog, optional local skills live under `.focus_agent/skills`, and
the Admin settings page can enable or disable the Skill system or individual
skills without changing tracked source.

Code execution uses a thread-level sandbox service. For Docker-backed command
and Skill execution, prepare the sandbox image with `make sandbox-image`; local
development can fall back to `local_subprocess` or `local_venv`, and those
results are explicitly marked as fallback. See
[docs/sandbox-execution.md](docs/sandbox-execution.md).

Zvec is the default rebuildable retrieval index for memory search, artifact RAG, Skill matching, trajectory reuse, branch/team shadow signals, and workspace semantic search. PostgreSQL and the filesystem remain canonical stores. See [docs/retrieval-zvec.md](docs/retrieval-zvec.md).

Memory embedding is enabled by default when PostgreSQL memory is available. Local auto mode prefers Ollama `embeddinggemma`; install it explicitly with `ollama pull embeddinggemma`, or configure an OpenAI-compatible embedding endpoint.

Then open:

- `http://127.0.0.1:8000/app`
- `http://127.0.0.1:8000/app/agent-team`
- `http://127.0.0.1:8000/app/agent/governance`
- `http://127.0.0.1:8000/app/admin/config`
- `http://127.0.0.1:8000/app/observability/overview`
- `http://127.0.0.1:8000/readyz` and `http://127.0.0.1:8000/metrics`

For the full local startup flow, managed repo-local PostgreSQL behavior, Vite dev mode, and local auth examples, see [docs/quick-start.md](docs/quick-start.md). The built-in auth page supports username/password, Demo login, and Bearer Token login; account switching is logout followed by another login method.

## Android App

The Android target packages the React app with Capacitor and uses the SDK **local transport** for a device-local single-user runtime (`apps/web/src/android-local-runtime/`). Provider keys stay in native secure storage; native HTTP is bounded and cancellable, deep links are allowlisted and delivered once for cold and hot intents, and bridge logging is disabled. The Web target remains **server-backed** on `/v1` and `/v2`. See [Android App](docs/android.md) for the capability boundary, limits, CI checks, and device/emulator validation.

```bash
pnpm android:web:build
pnpm android:sync
pnpm android:apk:debug
```

Use `pnpm android:open` to inspect the native project in Android Studio, or `pnpm android:run` to sync and run on a connected device/emulator.

## Container Deployment

- Local Docker: `compose.yaml`
- Production/staging template: `compose.prod.yaml`
- Full deployment guide: [docs/docker-deployment.md](docs/docker-deployment.md)

```bash
export FOCUS_AGENT_AUTH_JWT_SECRET=replace-with-a-strong-secret-at-least-32-chars
export OPENAI_API_KEY=replace-me
docker compose up --build
```

For production or staging, use `compose.prod.yaml` with an external Postgres connection in `FOCUS_AGENT_DATABASE_URI`.

## Development and Validation

Use `make help` to list the maintained local commands. The broad local check is:

```bash
make ci
```

GitHub CI also checks generated OpenAPI and SDK type drift. If backend routes or Pydantic response models changed, run and commit:

```bash
make sdk-openapi-types-check
```

For focused changes, use the narrower gates documented in [docs/development.md](docs/development.md). Common examples are:

```bash
make lint-strict
make contract-check
make architecture-gate
make compat-gate
pnpm sdk:check
pnpm web:check
pnpm web:build
make frontend-qa
```

If your change affects user-facing behavior, streaming events, auth, storage, or SDK types, include the relevant tests and update documentation in the same pull request.

GitHub Actions also contains a real Chrome workflow for chat, branch/review, and
observability interaction gates, plus an Android job that runs debug build,
lint, and unit tests. Local equivalents and simulator/device checks are listed
in [docs/validation-runbook.md](docs/validation-runbook.md). For broad runtime,
sandbox, Skill, Agent Team, observability, or release-readiness work, use that
runbook as the full evidence path (source checks, OpenAPI/SDK drift guards,
real-browser smoke, and `/readyz`).

## Contributing and Support

Contributions are welcome when they keep the runtime understandable, tested, and easy to adapt. Prefer focused changes that respect platform boundaries and existing contracts. Start with [CONTRIBUTING.md](CONTRIBUTING.md) for setup, pull request expectations, and issue-reporting guidance.

Please use the GitHub issue templates for bugs, feature requests, and documentation improvements. For vulnerabilities or sensitive findings, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Documentation

- [Project Overview (positioning & scale)](docs/project-overview.md)
- [Docs Index](docs/README.md)
- [Quick Start](docs/quick-start.md)
- [Development Guide](docs/development.md)
- [Validation Runbook](docs/validation-runbook.md)
- [Architecture and module map](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Streaming Contract](docs/streaming-contract.md)
- [Auth / Access](docs/auth-access.md)
- [Agent Team Workbench](docs/agent-team-workbench.md)
- [Agent Team v2 Rollout](docs/agent-team-v2-rollout.md)
- [Android App](docs/android.md)
- [Release Checklist](docs/release-checklist.md)
- [Frontend SDK](frontend-sdk/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE) for details.
