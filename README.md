# Focus Agent

---

**English** | [中文](README.zh-CN.md)

[![CI](https://github.com/William-zgx/focus-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/William-zgx/focus-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Node.js 20+](https://img.shields.io/badge/node.js-20%2B-339933?logo=node.js&logoColor=white)

![Focus Agent showcase](docs/assets/focus-agent-readme-hero.svg)

Focus Agent is a branch-aware, web-first Agent application scaffold for long AI workflows. Its core idea is simple: keep the main thread focused, let exploration happen in temporary branches, and merge conclusions back only when they are ready.

Around that branching workflow, the project provides streaming chat APIs, a React Web app, a typed frontend SDK, access control, Admin operations, observability, memory, Productivity tools, and Agent Team workflows as supporting surfaces.

## Project Status

Focus Agent is an open-source application scaffold and reference implementation, not a hosted SaaS product. It is intended for local development, product prototyping, and adaptation into team-owned branch-aware AI workspaces.

The branch workflow, backend API, SSE stream contract, frontend SDK, and documented Web surfaces are protected by contract, build, and smoke checks. Deployment choices such as model provider, auth policy, PostgreSQL hosting, observability backend, and release process remain explicit configuration decisions for each adopter.

## Why Focus Agent

Most agent demos assume one chat box and one final answer. Focus Agent is built around a different idea: serious research, debugging, writing, and review work are not linear.

Instead of forcing every detour into one noisy thread, Focus Agent treats the main thread as shared progress and branches as temporary workspaces for exploration, verification, and comparison.

## Core Capabilities

- Branch-aware conversations with controlled merge-back
- AI-assisted branch decisions and pre-turn branch recommendations that produce user-confirmed Branch Action cards
- Streaming chat APIs and a built-in React web app at `/app`
- Current context-window usage in the composer, with non-destructive manual and automatic compaction
- Agent Team Mission Runner for goal-driven multi-agent planning, task evidence, and final-answer synthesis
- Owner-scoped Productivity workbench (notes + tasks) with source trace (`/app/productivity/notes`, `/app/productivity/tasks`)
- Split observability flow: `/app/observability/overview` for trends and hotspots, `/app/observability/trajectory` for single-turn review
- Access control, Admin Console, capability-centered settings, memory pipeline, governance feedback trends, and typed frontend SDK
- Quarantined tool/protocol streams so `message.delta` only carries confirmed visible assistant text
- Built-in repo read/edit, git, web, artifact, memory, productivity, and Skill catalog tools with guarded workspace command execution
- Thread-level sandbox execution for workspace commands and declared Skill entrypoints, with Docker-first isolation and explicit local fallback metadata
- Admin-managed runtime settings for model connections, tool providers, Skill enablement, Agent behavior, security/runtime policy, and low-frequency advanced options

## Repository Layout

| Path | Purpose |
|------|---------|
| `src/focus_agent/` | Python backend runtime, API, services, persistence, tools, memory, and observability modules |
| `apps/web/` | React Web App served under `/app` |
| `frontend-sdk/` | Typed TypeScript SDK for API, SSE, and stream reducer integration |
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

`make setup-local` creates `.focus_agent/local.env`, `.focus_agent/models.toml`, and `.focus_agent/tools.toml`.
The root `.env.example` is a reference for Compose or manual shell exports; the local API startup path reads `.focus_agent/local.env` and process environment variables.

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

Memory embedding is enabled by default when PostgreSQL memory is available. Local auto mode prefers Ollama `embeddinggemma`; install it explicitly with `ollama pull embeddinggemma`, or configure an OpenAI-compatible embedding endpoint.

Then open:

- `http://127.0.0.1:8000/app`
- `http://127.0.0.1:8000/app/agent-team`
- `http://127.0.0.1:8000/app/agent/memory`
- `http://127.0.0.1:8000/app/agent/roles`
- `http://127.0.0.1:8000/app/agent/governance`
- `http://127.0.0.1:8000/app/admin/config`
- `http://127.0.0.1:8000/app/admin/users`
- `http://127.0.0.1:8000/app/admin/audit-events`
- `http://127.0.0.1:8000/app/productivity/notes`
- `http://127.0.0.1:8000/app/productivity/tasks`
- `http://127.0.0.1:8000/app/observability/overview`
- `http://127.0.0.1:8000/app/observability/trajectory`
- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/readyz`
- `http://127.0.0.1:8000/metrics`

For the full local startup flow, managed repo-local PostgreSQL behavior, Vite dev mode, and local auth examples, see [docs/quick-start.md](docs/quick-start.md). The built-in auth page supports username/password, Demo login, and Bearer Token login; account switching is logout followed by another login method.

## Android App

The Android target packages the React app with Capacitor. It keeps Chat, Admin, Focus Score branch routing, recommended Branch Actions, merge review, local governance/memory/observability routes, and Android-local web search tool calls, uses `/` as the in-app route base, and disables only the Agent Team / Productivity workbenches for the mobile build. Android uses the SDK local transport for an in-app Focus Agent runtime instead of connecting to a Focus Agent HTTP backend; model calls go directly to the user-configured OpenAI-compatible provider API key stored in native secure storage. The Web target still uses the default `/v1` and `/v2` backend transport.

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
pnpm sdk:check
pnpm web:check
pnpm web:build
make frontend-qa
```

If your change affects user-facing behavior, streaming events, auth, storage, or SDK types, include the relevant tests and update documentation in the same pull request.

## Contributing and Support

Contributions are welcome when they keep the runtime understandable, tested, and easy to adapt. Start with [CONTRIBUTING.md](CONTRIBUTING.md) for setup, pull request expectations, and issue-reporting guidance.

Please use the GitHub issue templates for bugs, feature requests, and documentation improvements. For vulnerabilities or sensitive findings, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Documentation

- [Docs Index](docs/README.md)
- [Quick Start](docs/quick-start.md)
- [Development Guide](docs/development.md)
- [Architecture and module map](docs/architecture.md)
- [Android App](docs/android.md)
- [Auth / Access](docs/auth-access.md)
- [Agent Team Workbench](docs/agent-team-workbench.md)
- [Productivity System](docs/productivity-system.md)
- [Admin Console](docs/admin-console.md)
- [Branch Decisions](docs/branch-decisions.md)
- [Streaming Contract](docs/streaming-contract.md)
- [Frontend Visual System](docs/frontend-visual-system.md)
- [Release Checklist](docs/release-checklist.md)
- [Frontend SDK](frontend-sdk/README.md)
- [Current Context Window](docs/context-window.md)
- [Docker Deployment](docs/docker-deployment.md)
- [Sandbox Execution](docs/sandbox-execution.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE) for details.
