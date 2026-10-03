# Skill Execution Matrix

Updated: 2026-09-28

This matrix is the machine-readable acceptance source for local Skill execution
coverage. The canonical data lives in
[`skill-execution-matrix.json`](skill-execution-matrix.json).

Execution categories:

- `prompt_only`: no command execution is required.
- `script_offline`: declared Skill entrypoint can run without network.
- `script_network`: declared Skill entrypoint requires network approval.
- `document_generation`: output-producing workflow that should move through a
  document-generation broker or a future declared generator entrypoint.
- `host_control`: high-risk host integration that must use a broker or explicit
  high-risk approval, not the general sandbox.

Current policy:

- Script-backed Skills must declare `entrypoints` in `SKILL.md`.
- Host-control Skills must not mount host sockets, SSH, home, or Docker into the
  general sandbox.
- Local fallback smoke is degraded evidence only; Docker success is required for
  secure execution acceptance.

This matrix classifies declared Skill entrypoints and their host-control policy;
it does not assert that an external dependency is installed or that a broker is
online. In particular, FastMCP/mcporter-style rows describe an installed
Skill/approval workflow, not a first-class MCP client, browser/computer-use
adapter, or account-backed connector supplied by the builtin runtime.
