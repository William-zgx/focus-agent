from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import DEFAULT_AUTH_JWT_SECRET, Settings


class AuthError(ValueError):
    pass


@dataclass(slots=True)
class Principal:
    user_id: str
    tenant_id: str | None = None
    scopes: tuple[str, ...] = field(default_factory=tuple)
    claims: dict[str, Any] = field(default_factory=dict)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    padding = '=' * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _sign(header_b64: str, payload_b64: str, secret: str) -> str:
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return _b64url_encode(signature)


def _include_single_secret(settings: Settings) -> bool:
    if not settings.auth_jwt_secret:
        return False
    if not settings.auth_jwt_keys:
        return True
    if settings.auth_jwt_secret != DEFAULT_AUTH_JWT_SECRET:
        return True
    return "AUTH_JWT_SECRET" in settings.resolved_env


def _signing_key(settings: Settings) -> tuple[str | None, str]:
    if settings.auth_jwt_key_id:
        for key in settings.auth_jwt_keys:
            if key.active and key.kid == settings.auth_jwt_key_id:
                return key.kid, key.secret
        if _include_single_secret(settings):
            return settings.auth_jwt_key_id, settings.auth_jwt_secret
        raise AuthError("JWT signing key id is not configured.")

    for key in settings.auth_jwt_keys:
        if key.active:
            return key.kid, key.secret
    if _include_single_secret(settings):
        return None, settings.auth_jwt_secret
    raise AuthError("JWT signing secret is not configured.")


def _dedupe_secrets(secrets: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(secret for secret in secrets if secret))


def _verification_secrets(settings: Settings, kid: str | None) -> tuple[str, ...]:
    if kid:
        secrets = [
            key.secret
            for key in settings.auth_jwt_keys
            if key.active and key.kid == kid
        ]
        if settings.auth_jwt_key_id == kid and _include_single_secret(settings):
            secrets.append(settings.auth_jwt_secret)
        deduped = _dedupe_secrets(secrets)
        if not deduped:
            raise AuthError("Bearer token key id is not configured.")
        return deduped

    secrets = [key.secret for key in settings.auth_jwt_keys if key.active]
    if _include_single_secret(settings):
        secrets.insert(0, settings.auth_jwt_secret)
    return _dedupe_secrets(secrets)


def create_access_token(
    *,
    settings: Settings,
    user_id: str,
    tenant_id: str | None = None,
    scopes: list[str] | tuple[str, ...] | None = None,
    expires_in_seconds: int | None = None,
) -> str:
    now = int(time.time())
    expiry = now + int(expires_in_seconds or settings.auth_access_token_ttl_seconds)
    kid, secret = _signing_key(settings)
    header = {"alg": "HS256", "typ": "JWT"}
    if kid:
        header["kid"] = kid
    payload: dict[str, Any] = {
        "iss": settings.auth_jwt_issuer,
        "sub": user_id,
        "iat": now,
        "exp": expiry,
        "scope": " ".join(scopes or []),
    }
    if settings.auth_jwt_audience:
        payload["aud"] = settings.auth_jwt_audience
    if tenant_id:
        payload["tenant_id"] = tenant_id
    header_b64 = _b64url_encode(_json_dumps(header))
    payload_b64 = _b64url_encode(_json_dumps(payload))
    signature_b64 = _sign(header_b64, payload_b64, secret)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_access_token(token: str, *, settings: Settings) -> Principal:
    try:
        header_b64, payload_b64, signature_b64 = token.split('.', 2)
    except ValueError as exc:
        raise AuthError('Malformed bearer token.') from exc

    try:
        header = json.loads(_b64url_decode(header_b64))
    except Exception as exc:  # noqa: BLE001
        raise AuthError('Bearer token header is invalid JSON.') from exc

    if header.get('alg') != 'HS256':
        raise AuthError('Only HS256 bearer tokens are supported by this skeleton.')

    kid = header.get("kid")
    if kid is not None:
        kid = str(kid)
    secrets = _verification_secrets(settings, kid)
    if not any(
        hmac.compare_digest(signature_b64, _sign(header_b64, payload_b64, secret))
        for secret in secrets
    ):
        raise AuthError('Bearer token signature is invalid.')

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:  # noqa: BLE001
        raise AuthError('Bearer token payload is invalid JSON.') from exc

    if payload.get('iss') != settings.auth_jwt_issuer:
        raise AuthError('Bearer token issuer mismatch.')
    if settings.auth_jwt_audience and payload.get('aud') != settings.auth_jwt_audience:
        raise AuthError('Bearer token audience mismatch.')
    if not payload.get('sub'):
        raise AuthError('Bearer token is missing subject.')

    now = int(time.time())
    if int(payload.get('exp', 0)) <= now:
        raise AuthError('Bearer token has expired.')

    scope_text = str(payload.get('scope') or '').strip()
    scopes = tuple(item for item in scope_text.split(' ') if item)
    return Principal(
        user_id=str(payload['sub']),
        tenant_id=payload.get('tenant_id'),
        scopes=scopes,
        claims=payload,
    )
