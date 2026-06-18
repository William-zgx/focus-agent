# Skill Execution Matrix

Updated: 2026-06-18

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
