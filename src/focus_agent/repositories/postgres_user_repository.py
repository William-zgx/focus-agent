from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from focus_agent.core.users import (
    AdminAuditEvent,
    AuditEventListResult,
    User,
    UserListResult,
    UserSession,
)
from focus_agent.security.tokens import Principal

from .postgres_schema import ensure_app_postgres_schema_on_connection
from .user_repository import AuditEventListFilters, UserListFilters, UserRepository


class PostgresUserRepository(UserRepository):
    def __init__(self, database_uri: str):
        self.database_uri = database_uri

    def setup(self) -> None:
        with psycopg.connect(self.database_uri) as conn:
            ensure_app_postgres_schema_on_connection(conn)
            self._ensure_schema_compatibility(conn)

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    @staticmethod
    def _ensure_schema_compatibility(conn: object) -> None:
        with conn.cursor() as cur:
            columns = {
                "focus_users": {
                    "username": "TEXT",
                    "password_hash": "TEXT",
                    "auth_provider": "TEXT NOT NULL DEFAULT 'local'",
                    "external_subject": "TEXT",
                    "failed_login_count": "INT NOT NULL DEFAULT 0",
                    "locked_until": "TIMESTAMPTZ",
                    "last_login_at": "TIMESTAMPTZ",
                    "password_updated_at": "TIMESTAMPTZ",
                },
                "focus_user_sessions": {
                    "refresh_token_hash": "TEXT NOT NULL DEFAULT ''",
                },
            }
            users_table_exists = False
            sessions_table_exists = False

            for table, table_columns in columns.items():
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = %s
                    """,
                    (table,),
                )
                exists = cur.fetchone() is not None
                if table == "focus_users":
                    users_table_exists = exists
                elif table == "focus_user_sessions":
                    sessions_table_exists = exists
                if not exists:
                    continue
                for column, definition in table_columns.items():
                    cur.execute(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
                        """,
                        (table, column),
                    )
                    if cur.fetchone() is None:
                        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

            if users_table_exists:
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_users_username
                    ON focus_users(LOWER(username))
                    WHERE username IS NOT NULL
                    """
                )
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_users_external_subject
                    ON focus_users(auth_provider, external_subject)
                    WHERE external_subject IS NOT NULL
                    """
                )
            if sessions_table_exists:
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_user_sessions_refresh_token_hash
                    ON focus_user_sessions(refresh_token_hash)
                    WHERE refresh_token_hash <> ''
                    """
                )

    @staticmethod
    def _decode_payload(value: object) -> dict[str, Any]:
        if isinstance(value, str):
            return json.loads(value)
        if isinstance(value, dict):
            return value
        return dict(value)  # type: ignore[arg-type]

    @classmethod
    def _user_from_row(cls, row: dict[str, object]) -> User:
        return User.model_validate(cls._decode_payload(row["data_json"]))

    @classmethod
    def _session_from_row(cls, row: dict[str, object]) -> UserSession:
        return UserSession.model_validate(cls._decode_payload(row["data_json"]))

    @classmethod
    def _audit_event_from_row(cls, row: dict[str, object]) -> AdminAuditEvent:
        return AdminAuditEvent.model_validate(cls._decode_payload(row["data_json"]))

    @staticmethod
    def _user_payload(user: User) -> dict[str, Any]:
        return user.model_dump(mode="json")

    @staticmethod
    def _audit_payload(event: AdminAuditEvent) -> dict[str, Any]:
        return event.model_dump(mode="json")

    @staticmethod
    def _session_payload(session: UserSession) -> dict[str, Any]:
        return session.model_dump(mode="json")

    def create_user(self, user: User) -> User:
        with self._connect() as conn:
            with conn.cursor() as cur:
                try:
                    self._insert_user(cur, user)
                except psycopg.errors.UniqueViolation as exc:
                    raise ValueError(f"User already exists: {user.user_id}") from exc
        return user

    def save_user(self, user: User) -> User:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_users SET
                        username = %(username)s,
                        display_name = %(display_name)s,
                        email = %(email)s,
                        tenant_id = %(tenant_id)s,
                        status = %(status)s,
                        roles_json = %(roles_json)s,
                        password_hash = %(password_hash)s,
                        auth_provider = %(auth_provider)s,
                        external_subject = %(external_subject)s,
                        failed_login_count = %(failed_login_count)s,
                        locked_until = %(locked_until)s,
                        updated_at = %(updated_at)s,
                        last_seen_at = %(last_seen_at)s,
                        last_login_at = %(last_login_at)s,
                        password_updated_at = %(password_updated_at)s,
                        data_json = %(data_json)s
                    WHERE user_id = %(user_id)s
                    """,
                    self._user_params(user),
                )
                if cur.rowcount == 0:
                    raise KeyError(f"Unknown user: {user.user_id}")
        return user

    def get_user(self, user_id: str) -> User:
        user = self.get_user_or_none(user_id)
        if user is None:
            raise KeyError(f"Unknown user: {user_id}")
        return user

    def get_user_or_none(self, user_id: str) -> User | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT data_json FROM focus_users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return self._user_from_row(row)

    def get_user_by_username(self, username: str) -> User | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data_json FROM focus_users WHERE LOWER(username) = %s",
                    (username.lower(),),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return self._user_from_row(row)

    def list_users(
        self,
        *,
        filters: UserListFilters | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> UserListResult:
        where, params = self._user_where(filters or UserListFilters())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS count FROM focus_users {where}", params)
                count_row = cur.fetchone()
                cur.execute(
                    f"""
                    SELECT data_json FROM focus_users {where}
                    ORDER BY created_at DESC, user_id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, limit, offset),
                )
                rows = cur.fetchall()
        count = int(count_row["count"] if count_row is not None else 0)
        return UserListResult(
            items=[self._user_from_row(row) for row in rows],
            count=count,
            limit=limit,
            offset=offset,
        )

    def ensure_user_from_principal(self, principal: Principal, *, defaults: User) -> User:
        existing = self.get_user_or_none(principal.user_id)
        if existing is not None:
            return existing
        try:
            return self.create_user(defaults)
        except ValueError:
            return self.get_user(principal.user_id)

    def count_active_admins(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS count FROM focus_users
                    WHERE status = %s AND roles_json @> %s
                    """,
                    ("active", Jsonb(["admin"])),
                )
                row = cur.fetchone()
        return int(row["count"] if row is not None else 0)

    def create_session(self, session: UserSession) -> UserSession:
        with self._connect() as conn:
            with conn.cursor() as cur:
                try:
                    self._insert_session(cur, session)
                except psycopg.errors.UniqueViolation as exc:
                    raise ValueError(f"User session already exists: {session.session_id}") from exc
        return session

    def save_session(self, session: UserSession) -> UserSession:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_user_sessions SET
                        user_id = %(user_id)s,
                        refresh_token_hash = %(refresh_token_hash)s,
                        updated_at = %(updated_at)s,
                        expires_at = %(expires_at)s,
                        revoked_at = %(revoked_at)s,
                        last_seen_at = %(last_seen_at)s,
                        data_json = %(data_json)s
                    WHERE session_id = %(session_id)s
                    """,
                    self._session_params(session),
                )
                if cur.rowcount == 0:
                    raise KeyError(f"Unknown user session: {session.session_id}")
        return session

    def get_session(self, session_id: str) -> UserSession:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data_json FROM focus_user_sessions WHERE session_id = %s", (session_id,)
                )
                row = cur.fetchone()
        if row is None:
            raise KeyError(f"Unknown user session: {session_id}")
        return self._session_from_row(row)

    def list_sessions(
        self,
        *,
        user_id: str | None = None,
        include_revoked: bool = False,
    ) -> list[UserSession]:
        clauses: list[str] = []
        params: list[object] = []
        if user_id is not None:
            clauses.append("user_id = %s")
            params.append(user_id)
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT data_json FROM focus_user_sessions {where}
                    ORDER BY created_at DESC, session_id DESC
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return [self._session_from_row(row) for row in rows]

    def revoke_session(self, session_id: str, *, revoked_at: str) -> UserSession:
        session = self.get_session(session_id)
        if session.revoked_at is not None:
            return session
        revoked = session.model_copy(update={"revoked_at": revoked_at, "updated_at": revoked_at})
        return self.save_session(revoked)

    def revoke_other_sessions(
        self,
        *,
        user_id: str,
        current_session_id: str,
        revoked_at: str,
    ) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data_json FROM focus_user_sessions
                    WHERE user_id = %s
                        AND session_id <> %s
                        AND revoked_at IS NULL
                    """,
                    (user_id, current_session_id),
                )
                sessions = [self._session_from_row(row) for row in cur.fetchall()]
                for session in sessions:
                    cur.execute(
                        """
                        UPDATE focus_user_sessions SET
                            updated_at = %(updated_at)s,
                            revoked_at = %(revoked_at)s,
                            data_json = %(data_json)s
                        WHERE session_id = %(session_id)s
                        """,
                        self._session_params(
                            session.model_copy(
                                update={"revoked_at": revoked_at, "updated_at": revoked_at}
                            )
                        ),
                    )
        return len(sessions)

    def record_audit_event(self, event: AdminAuditEvent) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_admin_audit_events (
                        event_id, actor_user_id, tenant_id, action, resource_type,
                        resource_id, decision, reason, request_id, created_at, data_json
                    ) VALUES (
                        %(event_id)s, %(actor_user_id)s, %(tenant_id)s, %(action)s,
                        %(resource_type)s, %(resource_id)s, %(decision)s, %(reason)s,
                        %(request_id)s, %(created_at)s, %(data_json)s
                    )
                    ON CONFLICT (event_id) DO UPDATE SET
                        actor_user_id = EXCLUDED.actor_user_id,
                        tenant_id = EXCLUDED.tenant_id,
                        action = EXCLUDED.action,
                        resource_type = EXCLUDED.resource_type,
                        resource_id = EXCLUDED.resource_id,
                        decision = EXCLUDED.decision,
                        reason = EXCLUDED.reason,
                        request_id = EXCLUDED.request_id,
                        created_at = EXCLUDED.created_at,
                        data_json = EXCLUDED.data_json
                    """,
                    self._audit_params(event),
                )

    def list_audit_events(
        self,
        *,
        filters: AuditEventListFilters | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditEventListResult:
        where, params = self._audit_where(filters or AuditEventListFilters())
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) AS count FROM focus_admin_audit_events {where}",
                    params,
                )
                count_row = cur.fetchone()
                cur.execute(
                    f"""
                    SELECT data_json FROM focus_admin_audit_events {where}
                    ORDER BY created_at DESC, event_id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, limit, offset),
                )
                rows = cur.fetchall()
        count = int(count_row["count"] if count_row is not None else 0)
        return AuditEventListResult(
            items=[self._audit_event_from_row(row) for row in rows],
            count=count,
            limit=limit,
            offset=offset,
        )

    def _insert_user(self, cur: object, user: User) -> None:
        cur.execute(
            """
            INSERT INTO focus_users (
                user_id, username, display_name, email, tenant_id, status, roles_json,
                password_hash, auth_provider, external_subject, failed_login_count,
                locked_until, created_at, updated_at, last_seen_at, last_login_at,
                password_updated_at, data_json
            ) VALUES (
                %(user_id)s, %(username)s, %(display_name)s, %(email)s,
                %(tenant_id)s, %(status)s, %(roles_json)s, %(password_hash)s,
                %(auth_provider)s, %(external_subject)s, %(failed_login_count)s,
                %(locked_until)s, %(created_at)s, %(updated_at)s, %(last_seen_at)s,
                %(last_login_at)s, %(password_updated_at)s,
                %(data_json)s
            )
            """,
            self._user_params(user),
        )

    def _insert_session(self, cur: object, session: UserSession) -> None:
        cur.execute(
            """
            INSERT INTO focus_user_sessions (
                session_id, user_id, refresh_token_hash, created_at, updated_at, expires_at,
                revoked_at, last_seen_at, data_json
            ) VALUES (
                %(session_id)s, %(user_id)s, %(refresh_token_hash)s, %(created_at)s,
                %(updated_at)s, %(expires_at)s, %(revoked_at)s, %(last_seen_at)s,
                %(data_json)s
            )
            """,
            self._session_params(session),
        )

    def _user_params(self, user: User) -> dict[str, object]:
        status = user.status.value if hasattr(user.status, "value") else str(user.status)
        return {
            "user_id": user.user_id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "tenant_id": user.tenant_id,
            "status": status,
            "roles_json": Jsonb(list(user.roles)),
            "password_hash": user.password_hash,
            "auth_provider": user.auth_provider,
            "external_subject": user.external_subject,
            "failed_login_count": user.failed_login_count,
            "locked_until": user.locked_until,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "last_seen_at": user.last_seen_at,
            "last_login_at": user.last_login_at,
            "password_updated_at": user.password_updated_at,
            "data_json": Jsonb(self._user_payload(user)),
        }

    def _session_params(self, session: UserSession) -> dict[str, object]:
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "refresh_token_hash": session.refresh_token_hash,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "expires_at": session.expires_at,
            "revoked_at": session.revoked_at,
            "last_seen_at": session.last_seen_at,
            "data_json": Jsonb(self._session_payload(session)),
        }

    def _audit_params(self, event: AdminAuditEvent) -> dict[str, object]:
        decision = event.decision.value if hasattr(event.decision, "value") else str(event.decision)
        return {
            "event_id": event.event_id,
            "actor_user_id": event.actor_user_id,
            "tenant_id": event.tenant_id,
            "action": event.action,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "decision": decision,
            "reason": event.reason,
            "request_id": event.request_id,
            "created_at": event.created_at,
            "data_json": Jsonb(self._audit_payload(event)),
        }

    @staticmethod
    def _user_where(filters: UserListFilters) -> tuple[str, tuple[object, ...]]:
        clauses: list[str] = []
        params: list[object] = []
        if filters.status:
            clauses.append("status = %s")
            params.append(filters.status)
        if filters.tenant_id:
            clauses.append("tenant_id = %s")
            params.append(filters.tenant_id)
        if filters.role:
            clauses.append("roles_json @> %s")
            params.append(Jsonb([filters.role]))
        if filters.query:
            pattern = f"%{filters.query.lower()}%"
            clauses.append(
                "(LOWER(user_id) LIKE %s OR LOWER(username) LIKE %s OR LOWER(display_name) LIKE %s OR LOWER(email) LIKE %s)"
            )
            params.extend([pattern, pattern, pattern, pattern])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)

    @staticmethod
    def _audit_where(filters: AuditEventListFilters) -> tuple[str, tuple[object, ...]]:
        clauses: list[str] = []
        params: list[object] = []
        if filters.actor_user_id:
            clauses.append("actor_user_id = %s")
            params.append(filters.actor_user_id)
        if filters.resource_type:
            clauses.append("resource_type = %s")
            params.append(filters.resource_type)
        if filters.resource_id:
            clauses.append("resource_id = %s")
            params.append(filters.resource_id)
        if filters.decision:
            clauses.append("decision = %s")
            params.append(filters.decision)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)


__all__ = ["PostgresUserRepository"]
