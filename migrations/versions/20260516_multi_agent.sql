-- Multi-agent coordination tables.
-- These tables are additive and guarded by feature flags.

CREATE TABLE IF NOT EXISTS agent_resource_claims (
    claim_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    lock_mode TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    released BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_resource_claims_active
    ON agent_resource_claims (session_id, resource_id)
    WHERE NOT released;

CREATE TABLE IF NOT EXISTS agent_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_agent TEXT NOT NULL,
    target_agent TEXT,
    message_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    acked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_messages_pending
    ON agent_messages (session_id, target_agent, created_at)
    WHERE acked_at IS NULL;

CREATE TABLE IF NOT EXISTS tool_approval_requests (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_args JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_level TEXT NOT NULL,
    status TEXT NOT NULL,
    timeout_at TIMESTAMPTZ NOT NULL,
    decided_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_approval_requests_status
    ON tool_approval_requests (session_id, status);
