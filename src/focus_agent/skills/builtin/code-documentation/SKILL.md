---
name: code-documentation
description: Generate or improve repository documentation such as READMEs, API docs, architecture notes, contributor guides, and code comments using the real structure of the current project.
triggers: docs:, document-code:
when_to_use: The user wants README or API docs, Existing code needs clearer documentation, Architecture or onboarding guidance should be derived from the repository
prompt_mode: execute
---

# Code Documentation

Write documentation from the repository that actually exists, not from assumptions.

## Workflow

1. Inspect the project first:
   - `list_files` for structure
   - `search_code` to locate manifests and entry points such as `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`
   - `read_file` for existing `README`, `docs/`, and tests
2. Decide the smallest doc scope that solves the request:
   - small script: usage notes or inline comments
   - library/service: README plus API or config notes
   - larger system: README, architecture notes, runbook, or contributor guide
3. Prefer updating existing docs over creating parallel versions.
4. Keep claims factual:
   - derive commands from the repo
   - derive configuration from real settings and code
   - mention unverified behavior as an assumption, not a fact
5. Match the audience:
   - end users need quick start and examples
   - contributors need architecture, tests, and workflow details

## Style

- Start with what the project does and why it exists.
- Use copy-pasteable commands.
- Keep sections concrete: prerequisites, install, run, test, deploy, limits.
- Add comments only where they explain non-obvious intent.

## Verification

Before finishing, verify that:

- file paths and commands exist
- terminology matches the codebase
- the new docs do not contradict current behavior
