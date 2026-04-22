# Release Checklist

This checklist is intended for maintainers preparing Focus Agent for a public release or a tagged internal milestone.

## Repository Readiness

- Confirm `README.md` reflects the current project scope and setup flow
- Confirm `README.zh-CN.md` is still aligned with the English README
- Confirm `CONTRIBUTING.md` reflects the expected contribution workflow
- Confirm `SECURITY.md` has a real private reporting path before public release
- Confirm `.github` issue templates and PR template still match repository conventions
- Remove internal-only references, examples, or wording from docs
- Review tracked files for secrets, tokens, internal hosts, or private organization details

## Licensing and Governance

- Confirm MIT license references still match the root `LICENSE` file
- Ensure README and other docs reference the final license correctly
- Decide whether a `NOTICE`, CLA, or DCO process is required

## Product and API Review

- Confirm the documented API routes still exist and match current behavior
- Confirm SSE event names and payload expectations are still accurate
- Confirm branch lifecycle behavior is still reflected correctly in docs
- Confirm auth behavior and ownership rules are documented accurately
- Confirm the frontend SDK examples still match the live contract
- Confirm trajectory observability docs match the live API, CLI, and `/app/observability/trajectory` console
- Confirm OTel exporter env vars and runtime readiness docs still match the live tracing behavior

## Configuration Review

- Review `.env.example` for completeness and safe defaults
- Review local config instructions under `.focus_agent/`
- Decide which settings are development-only versus production-ready
- Confirm default secrets or demo credentials are not appropriate for public deployment
- Review persistence-related settings such as `DATABASE_URI`, managed local Postgres runtime files, trajectory settings, and artifact paths

## Quality Checks

- Run `make ci`
- If Web App changed, run `make web-check` and `make web-build`
- If browser workflows changed, run `make ui-smoke`
- If observability pages changed, run `make ui-smoke-observability`
- If deployment or persistence changed, run the targeted Postgres / containerization tests referenced in `docs/architecture.md`

- Review recent changes for accidental breaking API or SDK changes
- Ensure docs were updated for any behavior changes

## Security Review

- Review authentication defaults
- Review token creation and validation behavior
- Review thread ownership enforcement paths
- Review any filesystem write locations used by tools or examples
- Review dependency versions and known advisories
- Confirm no sensitive values are present in tracked docs or examples

## Release Packaging

- Decide on the release version
- Update version references if needed
- Prepare release notes or changelog entries
- Identify any breaking changes and migration notes
- Tag the release according to repository conventions

## Post-Release Follow-Up

- Monitor issues and security reports after release
- Triage documentation gaps discovered by first external users
- Capture follow-up tasks for onboarding, deployment, and production hardening
