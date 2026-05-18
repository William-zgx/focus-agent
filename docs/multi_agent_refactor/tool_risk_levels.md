# Tool Risk Levels

## Levels

- `low`: read-only or local introspection tools.
- `medium`: bounded writes to generated artifacts or task-local files.
- `high`: repository writes, shell commands, migrations, network actions.
- `critical`: destructive operations, credential changes, production deployment.

## Auto Approval Example

When `multi_agent_async_approval_enabled` is on, low-risk requests may be configured for `AUTO_APPROVED`; all higher-risk requests stay pending until an approver decides.
