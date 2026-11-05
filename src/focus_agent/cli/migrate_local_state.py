"""``focus-agent-migrate-local-state``: copy local dev state into PostgreSQL."""

from __future__ import annotations

from focus_agent.migrations.local.applier import main

if __name__ == "__main__":
    raise SystemExit(main())
