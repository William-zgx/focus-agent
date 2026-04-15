from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings


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
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "iss": settings.auth_jwt_issuer,
        "sub": user_id,
        "iat": now,
        "exp": expiry,
        "scope": " ".join(scopes or []),
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    header_b64 = _b64url_encode(_json_dumps(header))
    payload_b64 = _b64url_encode(_json_dumps(payload))
    signature_b64 = _sign(header_b64, payload_b64, settings.auth_jwt_secret)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_access_token(token: str, *, settings: Settings) -> Principal:
    try:
        header_b64, payload_b64, signature_b64 = token.split('.', 2)
    except ValueError as exc:
        raise AuthError('Malformed bearer token.') from exc

    expected_signature = _sign(header_b64, payload_b64, settings.auth_jwt_secret)
    if not hmac.compare_digest(signature_b64, expected_signature):
        raise AuthError('Bearer token signature is invalid.')

    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:  # noqa: BLE001
        raise AuthError('Bearer token payload is invalid JSON.') from exc

    if header.get('alg') != 'HS256':
        raise AuthError('Only HS256 bearer tokens are supported by this skeleton.')
    if payload.get('iss') != settings.auth_jwt_issuer:
        raise AuthError('Bearer token issuer mismatch.')
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
