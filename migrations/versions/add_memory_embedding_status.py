from __future__ import annotations

from alembic import op

revision = "add_memory_embedding_status"
down_revision = "001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE focus_memories
        ADD COLUMN IF NOT EXISTS embedding_status TEXT NOT NULL DEFAULT 'pending'
        """
    )
    op.execute(
        """
        UPDATE focus_memories
        SET embedding_status = CASE
            WHEN data_json->>'embedding_status' IN ('pending', 'ready', 'failed')
                THEN data_json->>'embedding_status'
            ELSE 'pending'
        END
        """
    )
    op.execute(
        """
        UPDATE focus_memories
        SET data_json = jsonb_set(
            data_json,
            '{embedding_status}',
            to_jsonb(embedding_status),
            true
        )
        WHERE data_json->>'embedding_status' IS DISTINCT FROM embedding_status
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_memories_embedding_status_updated
        ON focus_memories(embedding_status, updated_at DESC)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM focus_schema_migrations
                WHERE version = 18
            ) THEN
                DROP INDEX IF EXISTS idx_focus_memories_embedding_status_updated;
                UPDATE focus_memories
                SET data_json = data_json - 'embedding_status';
                ALTER TABLE focus_memories
                DROP COLUMN IF EXISTS embedding_status;
            END IF;
        END $$;
        """
    )
