from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from focus_agent.config import Settings
from focus_agent.core.repo_call import has_repo_method
from focus_agent.core.users import User, UserSession, UserStatus
from focus_agent.repositories.user_repository import UserRepository
from focus_agent.security.passwords import hash_password, password_needs_rehash, verify_password
from focus_agent.security.tokens import Principal, create_access_token


ERROR_INVALID_CREDENTIALS = "invalid_credentials"
ERROR_ACCOUNT_LOCKED = "account_locked"
ERROR_USERNAME_TAKEN = "username_taken"
ERROR_WEAK_PASSWORD = "weak_password"
ERROR_PASSWORD_MISMATCH = "password_mismatch"
ERROR_SESSION_REVOKED = "session_revoked"

MAX_FAILED_LOGIN_COUNT = 5
LOCKOUT_SECONDS = 15 * 60


class AuthServiceError(ValueError):
    code = "auth_error"


class InvalidCredentialsError(AuthServiceError):
    code = ERROR_INVALID_CREDENTIALS


class AccountLockedError(AuthServiceError):
    code = ERROR_ACCOUNT_LOCKED


class UsernameTakenError(AuthServiceError):
    code = ERROR_USERNAME_TAKEN


class WeakPasswordError(AuthServiceError):
    code = ERROR_WEAK_PASSWORD


class PasswordMismatchError(AuthServiceError):
    code = ERROR_PASSWORD_MISMATCH


class SessionRevokedError(AuthServiceError):
    code = ERROR_SESSION_REVOKED


class AuthTokenPair:
    def __init__(
        self,
        *,
        user: User,
        session: UserSession,
        access_token: str,
        refresh_token: str,
        expires_in_seconds: int,
        issuer: str,
    ) -> None:
        self.user = user
        self.session = session
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in_seconds = expires_in_seconds
        self.issuer = issuer


class AuthService:
    def __init__(self, repository: UserRepository, *, settings: Settings):
        self.repository = repository
        self.settings = settings

    def register(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
        email: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> AuthTokenPair:
        normalized = normalize_username(username)
        self._require_strong_password(password)
        if self.repository.get_user_by_username(normalized) is not None:
            raise UsernameTakenError("Username is already taken.")
        now = _now()
        user = User(
            user_id=normalized,
            username=normalized,
            display_name=display_name or normalized,
            email=email,
            status=UserStatus.ACTIVE,
            roles=["member"],
            password_hash=hash_password(password),
            auth_provider="local",
            created_at=now,
            updated_at=now,
            password_updated_at=now,
            metadata={},
        )
        try:
            created = self.repository.create_user(user)
        except ValueError as exc:
            raise UsernameTakenError("Username is already taken.") from exc
        return self._issue_token_pair(
            created,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    def login(
        self,
        *,
        username: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> AuthTokenPair:
        user = self.repository.get_user_by_username(normalize_username(username))
        if user is None or user.password_hash is None:
            raise InvalidCredentialsError("Invalid username or password.")
        if self._is_locked(user):
            raise AccountLockedError("Account is locked.")
        if not verify_password(password, user.password_hash):
            self._record_failed_login(user)
            raise InvalidCredentialsError("Invalid username or password.")
        now = _now()
        updates: dict[str, object] = {
            "failed_login_count": 0,
            "locked_until": None,
            "last_login_at": now,
            "last_seen_at": now,
            "updated_at": now,
        }
        if password_needs_rehash(user.password_hash):
            updates["password_hash"] = hash_password(password)
            updates["password_updated_at"] = now
        saved = self.repository.save_user(user.model_copy(update=updates))
        return self._issue_token_pair(saved, user_agent=user_agent, ip_address=ip_address)

    def refresh(self, refresh_token: str) -> AuthTokenPair:
        session = self._active_session(refresh_token)
        user = self._active_user(session.user_id)
        now = _now()
        saved_session = self.repository.save_session(
            session.model_copy(update={"last_seen_at": now, "updated_at": now})
        )
        return AuthTokenPair(
            user=user,
            session=saved_session,
            access_token=self._access_token(user),
            refresh_token=refresh_token,
            expires_in_seconds=self.settings.auth_access_token_ttl_seconds,
            issuer=self.settings.auth_jwt_issuer,
        )

    def logout(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        try:
            self.repository.revoke_session(_refresh_token_hash(refresh_token), revoked_at=_now())
        except KeyError:
            return

    def change_password(
        self,
        *,
        user_id: str,
        current_password: str,
        new_password: str,
        refresh_token: str | None = None,
    ) -> User:
        user = self._active_user(user_id)
        if not verify_password(current_password, user.password_hash):
            raise PasswordMismatchError("Current password does not match.")
        self._require_strong_password(new_password)
        now = _now()
        saved = self.repository.save_user(
            user.model_copy(
                update={
                    "password_hash": hash_password(new_password),
                    "password_updated_at": now,
                    "failed_login_count": 0,
                    "locked_until": None,
                    "updated_at": now,
                }
            )
        )
        current_session_id = _refresh_token_hash(refresh_token) if refresh_token else None
        self._revoke_other_sessions(user_id=user_id, current_session_id=current_session_id)
        return saved

    def reset_password(self, *, user_id: str, new_password: str) -> User:
        self._require_strong_password(new_password)
        user = self.repository.get_user(user_id)
        now = _now()
        saved = self.repository.save_user(
            user.model_copy(
                update={
                    "password_hash": hash_password(new_password),
                    "password_updated_at": now,
                    "failed_login_count": 0,
                    "locked_until": None,
                    "updated_at": now,
                }
            )
        )
        self._revoke_user_sessions(user_id=user_id)
        return saved

    def _issue_token_pair(
        self,
        user: User,
        *,
        user_agent: str | None,
        ip_address: str | None,
    ) -> AuthTokenPair:
        now = _now()
        refresh_token = secrets.token_urlsafe(32)
        refresh_token_hash = _refresh_token_hash(refresh_token)
        session = self.repository.create_session(
            UserSession(
                session_id=refresh_token_hash,
                user_id=user.user_id,
                refresh_token_hash=refresh_token_hash,
                created_at=now,
                updated_at=now,
                expires_at=_now_plus(self.settings.auth_refresh_token_ttl_seconds),
                last_seen_at=now,
                user_agent=user_agent,
                ip_address=ip_address,
            )
        )
        return AuthTokenPair(
            user=user,
            session=session,
            access_token=self._access_token(user),
            refresh_token=refresh_token,
            expires_in_seconds=self.settings.auth_access_token_ttl_seconds,
            issuer=self.settings.auth_jwt_issuer,
        )

    def _access_token(self, user: User) -> str:
        return create_access_token(
            settings=self.settings,
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            scopes=["chat", "branches"],
        )

    def _active_user(self, user_id: str) -> User:
        try:
            user = self.repository.get_user(user_id)
        except KeyError as exc:
            raise InvalidCredentialsError("Invalid username or password.") from exc
        if _status_value(user.status) != UserStatus.ACTIVE.value:
            raise AccountLockedError("Account is locked.")
        return user

    def _active_session(self, refresh_token: str) -> UserSession:
        try:
            session = self.repository.get_session(_refresh_token_hash(refresh_token))
        except KeyError as exc:
            raise SessionRevokedError("Session has been revoked.") from exc
        if session.revoked_at is not None or _parse_time(session.expires_at) <= datetime.now(UTC):
            raise SessionRevokedError("Session has been revoked.")
        return session

    def _is_locked(self, user: User) -> bool:
        if _status_value(user.status) != UserStatus.ACTIVE.value:
            return True
        if user.locked_until is None:
            return False
        return _parse_time(user.locked_until) > datetime.now(UTC)

    def _record_failed_login(self, user: User) -> None:
        failed_count = int(user.failed_login_count or 0) + 1
        updates: dict[str, object] = {"failed_login_count": failed_count, "updated_at": _now()}
        if failed_count >= MAX_FAILED_LOGIN_COUNT:
            updates["locked_until"] = _now_plus(LOCKOUT_SECONDS)
        self.repository.save_user(user.model_copy(update=updates))

    @staticmethod
    def _require_strong_password(password: str) -> None:
        if len(password) < 8:
            raise WeakPasswordError("Password must be at least 8 characters.")
        if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
            raise WeakPasswordError("Password must include letters and numbers.")

    def _revoke_other_sessions(self, *, user_id: str, current_session_id: str | None) -> None:
        now = _now()
        if current_session_id and has_repo_method(self.repository, "revoke_other_sessions"):
            self.repository.revoke_other_sessions(
                user_id=user_id, current_session_id=current_session_id, revoked_at=now
            )
            return
        for session in self.repository.list_sessions(user_id=user_id, include_revoked=False):
            if current_session_id and session.session_id == current_session_id:
                continue
            self.repository.revoke_session(session.session_id, revoked_at=now)

    def _revoke_user_sessions(self, *, user_id: str) -> None:
        now = _now()
        if has_repo_method(self.repository, "revoke_user_sessions"):
            self.repository.revoke_user_sessions(user_id=user_id, revoked_at=now)
            return
        for session in self.repository.list_sessions(user_id=user_id, include_revoked=False):
            self.repository.revoke_session(session.session_id, revoked_at=now)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def principal_for_user(user: User) -> Principal:
    return Principal(user_id=user.user_id, tenant_id=user.tenant_id, scopes=("chat", "branches"))


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _now_plus(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _status_value(status: UserStatus | str) -> str:
    return status.value if isinstance(status, UserStatus) else str(status)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _refresh_token_hash(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


__all__ = [
    "AuthService",
    "AuthServiceError",
    "AuthTokenPair",
    "InvalidCredentialsError",
    "AccountLockedError",
    "UsernameTakenError",
    "WeakPasswordError",
    "PasswordMismatchError",
    "SessionRevokedError",
    "normalize_username",
    "principal_for_user",
]
