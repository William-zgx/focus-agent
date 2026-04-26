import base64
import hashlib
import hmac
import json
import time

import pytest

from focus_agent.config import Settings
from focus_agent.security.tokens import AuthError
from focus_agent.security.tokens import create_access_token, decode_access_token


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _signed_token(settings: Settings, payload: dict[str, object]) -> str:
    header_b64 = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        settings.auth_jwt_secret.encode("utf-8"),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"


def test_hs256_token_roundtrip():
    settings = Settings(auth_jwt_secret="secret-1", auth_jwt_issuer="focus-agent-test")
    token = create_access_token(
        settings=settings,
        user_id="user-1",
        tenant_id="tenant-1",
        scopes=["chat", "branches"],
        expires_in_seconds=3600,
    )
    principal = decode_access_token(token, settings=settings)
    assert principal.user_id == "user-1"
    assert principal.tenant_id == "tenant-1"
    assert principal.scopes == ("chat", "branches")
    assert principal.claims["iss"] == "focus-agent-test"


def test_token_audience_is_enforced_when_configured():
    settings = Settings(
        auth_jwt_secret="secret-1",
        auth_jwt_issuer="focus-agent-test",
        auth_jwt_audience="focus-agent-web",
    )
    token = create_access_token(settings=settings, user_id="user-1", expires_in_seconds=3600)

    principal = decode_access_token(token, settings=settings)

    assert principal.claims["aud"] == "focus-agent-web"

    wrong_audience = Settings(
        auth_jwt_secret="secret-1",
        auth_jwt_issuer="focus-agent-test",
        auth_jwt_audience="other-client",
    )
    with pytest.raises(AuthError, match="audience mismatch"):
        decode_access_token(token, settings=wrong_audience)

    token_without_audience = create_access_token(
        settings=Settings(auth_jwt_secret="secret-1", auth_jwt_issuer="focus-agent-test"),
        user_id="user-1",
        expires_in_seconds=3600,
    )
    with pytest.raises(AuthError, match="audience mismatch"):
        decode_access_token(token_without_audience, settings=settings)


def test_external_jwt_rejects_missing_or_wrong_issuer():
    settings = Settings(auth_jwt_secret="secret-1", auth_jwt_issuer="focus-agent-test")
    now = int(time.time())
    base_payload = {"sub": "user-1", "iat": now, "exp": now + 3600}

    missing_issuer = _signed_token(settings, base_payload)
    with pytest.raises(AuthError, match="issuer mismatch"):
        decode_access_token(missing_issuer, settings=settings)

    wrong_issuer = _signed_token(settings, {**base_payload, "iss": "other-issuer"})
    with pytest.raises(AuthError, match="issuer mismatch"):
        decode_access_token(wrong_issuer, settings=settings)


def test_external_jwt_rejects_missing_or_wrong_audience_when_configured():
    settings = Settings(
        auth_jwt_secret="secret-1",
        auth_jwt_issuer="focus-agent-test",
        auth_jwt_audience="focus-agent-web",
    )
    now = int(time.time())
    base_payload = {"iss": "focus-agent-test", "sub": "user-1", "iat": now, "exp": now + 3600}

    missing_audience = _signed_token(settings, base_payload)
    with pytest.raises(AuthError, match="audience mismatch"):
        decode_access_token(missing_audience, settings=settings)

    wrong_audience = _signed_token(settings, {**base_payload, "aud": "other-client"})
    with pytest.raises(AuthError, match="audience mismatch"):
        decode_access_token(wrong_audience, settings=settings)


def test_external_jwt_rejects_expired_token():
    settings = Settings(auth_jwt_secret="secret-1", auth_jwt_issuer="focus-agent-test")
    token = create_access_token(settings=settings, user_id="user-1", expires_in_seconds=-1)

    with pytest.raises(AuthError, match="expired"):
        decode_access_token(token, settings=settings)
