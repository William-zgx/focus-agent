from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from focus_agent.core.users import (
    AdminAuditEvent,
    AuditEventListResult,
    User,
    UserListResult,
    UserSession,
)
from focus_agent.security.tokens import Principal

from .user_repository import (
    AuditEventListFilters,
    LastActiveAdminError,
    UserListFilters,
    UserRepository,
)


class SQLiteUserRepository(UserRepository):
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._setup()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _setup(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    display_name TEXT,
                    email TEXT,
                    tenant_id TEXT,
                    status TEXT NOT NULL,
                    roles_json TEXT NOT NULL,
                    password_hash TEXT,
                    auth_provider TEXT NOT NULL DEFAULT 'local',
                    external_subject TEXT,
                    failed_login_count INTEGER NOT NULL DEFAULT 0,
                    locked_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen_at TEXT,
                    last_login_at TEXT,
                    password_updated_at TEXT,
                    data_json TEXT NOT NULL
                )
                """
            )
            self._add_missing_user_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    refresh_token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    last_seen_at TEXT,
                    data_json TEXT NOT NULL
                )
                """
            )
            self._add_missing_session_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_audit_events (
                    event_id TEXT PRIMARY KEY,
                    actor_user_id TEXT,
                    tenant_id TEXT,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    decision TEXT NOT NULL,
                    reason TEXT,
                    request_id TEXT,
                    created_at TEXT NOT NULL,
                    data_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_tenant_status ON users(tenant_id, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_status_created ON users(status, created_at DESC)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(LOWER(username)) WHERE username IS NOT NULL"
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_users_external_subject
                ON users(auth_provider, external_subject)
                WHERE external_subject IS NOT NULL
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_created ON user_sessions(user_id, created_at DESC)"
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_user_sessions_refresh_token_hash
                ON user_sessions(refresh_token_hash)
                WHERE refresh_token_hash <> ''
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_revoked ON user_sessions(user_id, revoked_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_admin_audit_actor_created ON admin_audit_events(actor_user_id, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_admin_audit_resource_created ON admin_audit_events(resource_type, resource_id, created_at DESC)"
            )
            conn.commit()

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> User:
        return User.model_validate(json.loads(row["data_json"]))

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> UserSession:
        return UserSession.model_validate(json.loads(row["data_json"]))

    @staticmethod
    def _audit_event_from_row(row: sqlite3.Row) -> AdminAuditEvent:
        return AdminAuditEvent.model_validate(json.loads(row["data_json"]))

    @staticmethod
    def _add_missing_user_columns(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        columns = {
            "username": "TEXT",
            "password_hash": "TEXT",
            "auth_provider": "TEXT NOT NULL DEFAULT 'local'",
            "external_subject": "TEXT",
            "failed_login_count": "INTEGER NOT NULL DEFAULT 0",
            "locked_until": "TEXT",
            "last_login_at": "TEXT",
            "password_updated_at": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")

    @staticmethod
    def _add_missing_session_columns(conn: sqlite3.Connection) -> None:
        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(user_sessions)").fetchall()
        }
        if "refresh_token_hash" not in existing:
            conn.execute(
                "ALTER TABLE user_sessions ADD COLUMN refresh_token_hash TEXT NOT NULL DEFAULT ''"
            )

    def create_user(self, user: User) -> User:
        with self._connect() as conn:
            try:
                self._insert_user(conn, user)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"User already exists: {user.user_id}") from exc
            conn.commit()
        return user

    def save_user(self, user: User) -> User:
        with self._connect() as conn:
            self._update_user(conn, user)
            conn.commit()
        return user

    def save_user_preserving_last_active_admin(self, user: User) -> User:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT data_json FROM users WHERE user_id = ?",
                (user.user_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown user: {user.user_id}")
            current = self._user_from_row(row)
            if self._removes_active_admin(current, user):
                rows = conn.execute(
                    "SELECT data_json FROM users WHERE status = ?",
                    ("active",),
                ).fetchall()
                active_admin_count = sum(
                    1
                    for active_row in rows
                    if self._is_active_admin(self._user_from_row(active_row))
                )
                if active_admin_count <= 1:
                    raise LastActiveAdminError("Cannot remove the last active admin.")
            self._update_user(conn, user)
            conn.commit()
        return user

    def get_user(self, user_id: str) -> User:
        user = self.get_user_or_none(user_id)
        if user is None:
            raise KeyError(f"Unknown user: {user_id}")
        return user

    def get_user_or_none(self, user_id: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        return self._user_from_row(row)

    def get_user_by_username(self, username: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM users WHERE LOWER(username) = ?",
                (username.lower(),),
            ).fetchone()
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
        filters = filters or UserListFilters()
        where, params = self._user_where(filters)
        with self._connect() as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) AS count FROM users {where}", params
            ).fetchone()
            rows = conn.execute(
                f"SELECT data_json FROM users {where} ORDER BY created_at DESC, user_id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
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
        return self.create_user(defaults)

    def count_active_admins(self) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data_json FROM users WHERE status = ?", ("active",)
            ).fetchall()
        return sum(1 for row in rows if "admin" in set(self._user_from_row(row).roles))

    def create_session(self, session: UserSession) -> UserSession:
        with self._connect() as conn:
            try:
                self._insert_session(conn, session)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"User session already exists: {session.session_id}") from exc
            conn.commit()
        return session

    def save_session(self, session: UserSession) -> UserSession:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE user_sessions SET
                    user_id = ?,
                    refresh_token_hash = ?,
                    updated_at = ?,
                    expires_at = ?,
                    revoked_at = ?,
                    last_seen_at = ?,
                    data_json = ?
                WHERE session_id = ?
                """,
                (
                    session.user_id,
                    session.refresh_token_hash,
                    session.updated_at,
                    session.expires_at,
                    session.revoked_at,
                    session.last_seen_at,
                    session.model_dump_json(),
                    session.session_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown user session: {session.session_id}")
            conn.commit()
        return session

    def get_session(self, session_id: str) -> UserSession:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM user_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
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
            clauses.append("user_id = ?")
            params.append(user_id)
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT data_json FROM user_sessions {where} ORDER BY created_at DESC, session_id DESC",
                tuple(params),
            ).fetchall()
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
        sessions = [
            session
            for session in self.list_sessions(user_id=user_id)
            if session.session_id != current_session_id
        ]
        for session in sessions:
            self.save_session(
                session.model_copy(update={"revoked_at": revoked_at, "updated_at": revoked_at})
            )
        return len(sessions)

    def record_audit_event(self, event: AdminAuditEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_audit_events (
                    event_id, actor_user_id, tenant_id, action, resource_type, resource_id,
                    decision, reason, request_id, created_at, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    actor_user_id = excluded.actor_user_id,
                    tenant_id = excluded.tenant_id,
                    action = excluded.action,
                    resource_type = excluded.resource_type,
                    resource_id = excluded.resource_id,
                    decision = excluded.decision,
                    reason = excluded.reason,
                    request_id = excluded.request_id,
                    created_at = excluded.created_at,
                    data_json = excluded.data_json
                """,
                (
                    event.event_id,
                    event.actor_user_id,
                    event.tenant_id,
                    event.action,
                    event.resource_type,
                    event.resource_id,
                    event.decision.value
                    if hasattr(event.decision, "value")
                    else str(event.decision),
                    event.reason,
                    event.request_id,
                    event.created_at,
                    event.model_dump_json(),
                ),
            )
            conn.commit()

    def list_audit_events(
        self,
        *,
        filters: AuditEventListFilters | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditEventListResult:
        filters = filters or AuditEventListFilters()
        where, params = self._audit_where(filters)
        with self._connect() as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) AS count FROM admin_audit_events {where}", params
            ).fetchone()
            rows = conn.execute(
                f"SELECT data_json FROM admin_audit_events {where} ORDER BY created_at DESC, event_id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        count = int(count_row["count"] if count_row is not None else 0)
        return AuditEventListResult(
            items=[self._audit_event_from_row(row) for row in rows],
            count=count,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _insert_user(conn: sqlite3.Connection, user: User) -> None:
        conn.execute(
            """
            INSERT INTO users (
                user_id, username, display_name, email, tenant_id, status, roles_json,
                password_hash, auth_provider, external_subject, failed_login_count,
                locked_until, created_at, updated_at, last_seen_at, last_login_at,
                password_updated_at, data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.user_id,
                user.username,
                user.display_name,
                user.email,
                user.tenant_id,
                user.status.value if hasattr(user.status, "value") else str(user.status),
                json.dumps(user.roles, separators=(",", ":"), sort_keys=True),
                user.password_hash,
                user.auth_provider,
                user.external_subject,
                user.failed_login_count,
                user.locked_until,
                user.created_at,
                user.updated_at,
                user.last_seen_at,
                user.last_login_at,
                user.password_updated_at,
                user.model_dump_json(),
            ),
        )

    @staticmethod
    def _update_user(conn: sqlite3.Connection, user: User) -> None:
        cursor = conn.execute(
            """
            UPDATE users SET
                username = ?,
                display_name = ?,
                email = ?,
                tenant_id = ?,
                status = ?,
                roles_json = ?,
                password_hash = ?,
                auth_provider = ?,
                external_subject = ?,
                failed_login_count = ?,
                locked_until = ?,
                updated_at = ?,
                last_seen_at = ?,
                last_login_at = ?,
                password_updated_at = ?,
                data_json = ?
            WHERE user_id = ?
            """,
            (
                user.username,
                user.display_name,
                user.email,
                user.tenant_id,
                user.status.value if hasattr(user.status, "value") else str(user.status),
                json.dumps(user.roles, separators=(",", ":"), sort_keys=True),
                user.password_hash,
                user.auth_provider,
                user.external_subject,
                user.failed_login_count,
                user.locked_until,
                user.updated_at,
                user.last_seen_at,
                user.last_login_at,
                user.password_updated_at,
                user.model_dump_json(),
                user.user_id,
            ),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Unknown user: {user.user_id}")

    @staticmethod
    def _is_active_admin(user: User) -> bool:
        status = user.status.value if hasattr(user.status, "value") else str(user.status)
        return status == "active" and "admin" in set(user.roles)

    @classmethod
    def _removes_active_admin(cls, current: User, updated: User) -> bool:
        return cls._is_active_admin(current) and not cls._is_active_admin(updated)

    @staticmethod
    def _insert_session(conn: sqlite3.Connection, session: UserSession) -> None:
        conn.execute(
            """
            INSERT INTO user_sessions (
                session_id, user_id, refresh_token_hash, created_at, updated_at, expires_at,
                revoked_at, last_seen_at, data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.user_id,
                session.refresh_token_hash,
                session.created_at,
                session.updated_at,
                session.expires_at,
                session.revoked_at,
                session.last_seen_at,
                session.model_dump_json(),
            ),
        )

    @staticmethod
    def _user_where(filters: UserListFilters) -> tuple[str, tuple[object, ...]]:
        clauses: list[str] = []
        params: list[object] = []
        if filters.status:
            clauses.append("status = ?")
            params.append(filters.status)
        if filters.tenant_id:
            clauses.append("tenant_id = ?")
            params.append(filters.tenant_id)
        if filters.role:
            clauses.append("roles_json LIKE ?")
            params.append(f'%"{filters.role}"%')
        if filters.query:
            clauses.append(
                "(LOWER(user_id) LIKE ? OR LOWER(username) LIKE ? OR LOWER(display_name) LIKE ? OR LOWER(email) LIKE ?)"
            )
            pattern = f"%{filters.query.lower()}%"
            params.extend([pattern, pattern, pattern, pattern])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)

    @staticmethod
    def _audit_where(filters: AuditEventListFilters) -> tuple[str, tuple[object, ...]]:
        clauses: list[str] = []
        params: list[object] = []
        if filters.actor_user_id:
            clauses.append("actor_user_id = ?")
            params.append(filters.actor_user_id)
        if filters.resource_type:
            clauses.append("resource_type = ?")
            params.append(filters.resource_type)
        if filters.resource_id:
            clauses.append("resource_id = ?")
            params.append(filters.resource_id)
        if filters.decision:
            clauses.append("decision = ?")
            params.append(filters.decision)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, tuple(params)


__all__ = ["SQLiteUserRepository"]
