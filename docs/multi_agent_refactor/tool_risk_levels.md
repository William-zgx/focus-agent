# Tool Risk Levels

> **Historical refactor record.** These risk levels and approval examples are
> policy design notes, not evidence of a live approval/replay capability. For
> current defaults and open capability work, see the [current overview](../project-overview.md)
> and the 2026-09-28 [research](../plans/2026-09-28-agent-capabilities/research.md),
> [design](../plans/2026-09-28-agent-capabilities/design.md), and
> [plan](../plans/2026-09-28-agent-capabilities/plan.md).

## Levels

- `low`: read-only or local introspection tools.
- `medium`: bounded writes to generated artifacts or task-local files.
- `high`: repository writes, shell commands, migrations, network actions.
- `critical`: destructive operations, credential changes, production deployment.

## Auto Approval Example

When `multi_agent_async_approval_enabled` is on, low-risk requests may be configured for `AUTO_APPROVED`; all higher-risk requests stay pending until an approver decides.
