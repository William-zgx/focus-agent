# Contributing to Focus Agent

Thank you for considering a contribution to Focus Agent.

This repository is intended to stay small, readable, and easy to adapt. The best contributions are usually focused improvements that make the agent runtime clearer, safer, better documented, or easier to integrate.

## Ways to Contribute

You can help by contributing:

- bug fixes
- tests for existing behavior
- API or SDK improvements
- documentation and examples
- developer experience improvements
- branching, streaming, and persistence enhancements

If you are planning a larger change, opening an issue or starting a short discussion first is strongly recommended.

## Development Setup

### Python environment

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[openai,dev]'
```

If you are developing against Anthropic instead of OpenAI:

```bash
uv pip install -e '.[anthropic,dev]'
```

### Local configuration

```bash
make setup-local
```

Keep provider credentials in `.focus_agent/local.env` or other untracked local configuration. Do not commit secrets, tokens, or private endpoints.

## Running the Project

Start the API locally through the repo startup path:

```bash
make api
```

When `DATABASE_URI` is unset, `make api` manages a repo-local PostgreSQL instance and injects the runtime connection string automatically. If you launch `.venv/bin/focus-agent-api` directly, export `DATABASE_URI` yourself first.

Useful local entry points:

- Web UI: `http://127.0.0.1:8000/app`
- Trajectory console: `http://127.0.0.1:8000/app/observability/trajectory`
- Demo CLI: `focus-agent-demo`

## Running Tests

Run the test suite before opening a pull request:

```bash
make ci-test
```

`make ci-test` intentionally points `FOCUS_AGENT_LOCAL_ENV_FILE` at a missing file so local secrets in `.focus_agent/local.env` do not hide CI setup gaps. You can also run Ruff locally if you are touching Python code:

```bash
make lint
```

If your change affects the frontend SDK, validate it as well:

```bash
make sdk-check
make sdk-build
```

If your change affects the Web App, validate it as well:

```bash
make web-check
make web-build
```

If your change affects trajectory observability, also run the API and CLI tests around that surface:

```bash
uv run pytest tests/test_api_trajectory_observability.py tests/test_api_trajectory_actions.py tests/test_trajectory_cli.py
```

To mirror the current GitHub Actions job locally, run:

```bash
make ci
```

For broad changes, prefer `make ci` as the baseline before PR review.

If your change affects browser-level chat, branch tree, or merge-review workflows, run:

```bash
make ui-smoke
```

## Contribution Guidelines

Please try to keep changes aligned with the existing goals of the repository:

- keep the architecture compact and understandable
- prefer clear module boundaries over clever abstractions
- preserve branch-aware conversation behavior
- preserve API and streaming contract clarity
- update docs when behavior or setup changes
- add or update tests when changing runtime behavior

When adding code:

- prefer canonical imports from the normalized module layout under `src/focus_agent/`
- avoid introducing secrets into tracked files
- keep compatibility shims only when they help migration or public package stability
- favor targeted changes over large unrelated refactors

## Pull Request Expectations

Good pull requests usually include:

- a clear summary of what changed
- the reason the change is needed
- any relevant API or behavior notes
- tests or an explanation of why tests were not added
- documentation updates when user-facing behavior changed

If your PR changes streaming events, auth behavior, repository shape, or public SDK types, please call that out explicitly in the description.
If it changes trajectory records, replay/promotion behavior, or the observability console, call that out as API/SDK impact too.

## Commit Scope

Please avoid mixing unrelated changes in a single pull request. Documentation-only changes, refactors, bug fixes, and new features are easier to review when they are kept separate.

## Reporting Issues

When reporting a bug, it helps to include:

- what you expected to happen
- what actually happened
- relevant request payloads or commands
- model/provider configuration details when relevant
- logs, stack traces, or screenshots if available
- whether the issue affects API routes, streaming, branching, storage, or the frontend SDK

## Documentation Contributions

Documentation improvements are welcome, including:

- onboarding improvements
- examples for API usage
- architecture clarifications
- non-English translations
- deployment and persistence guides

If you notice wording that feels too internal, too sparse, or too implementation-heavy for open-source readers, that is a great candidate for improvement.

## Security Issues

If you believe you found a security issue, please do not file a public bug report first. See [`SECURITY.md`](SECURITY.md) for the reporting guidance currently used by this repository.

## License Notes

By contributing, you agree that your contribution may be distributed under the MIT License used by this repository. See [`LICENSE`](LICENSE) for details.
