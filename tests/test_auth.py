import base64
import hashlib
import hmac
import json
import time

import pytest

from focus_agent.config import AuthJwtKey, Settings
from focus_agent.security.tokens import AuthError
from focus_agent.security.tokens import create_access_token, decode_access_token


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _signed_token(
    settings: Settings,
    payload: dict[str, object],
    *,
    secret: str | None = None,
    kid: str | None = None,
) -> str:
    header: dict[str, object] = {"alg": "HS256", "typ": "JWT"}
    if kid is not None:
        header["kid"] = kid
    header_b64 = _b64url_encode(json.dumps(header).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        (secret or settings.auth_jwt_secret).encode("utf-8"),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"


def _decode_header(token: str) -> dict[str, object]:
    header_b64, _, _ = token.split(".", 2)
    return json.loads(base64.urlsafe_b64decode(header_b64 + "=" * (-len(header_b64) % 4)))


def _decode_payload(token: str) -> dict[str, object]:
    _, payload_b64, _ = token.split(".", 2)
    return json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))


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


def test_hs256_token_roundtrip_includes_kid_when_configured():
    settings = Settings(
        auth_jwt_secret="secret-1",
        auth_jwt_key_id="current",
        auth_jwt_issuer="focus-agent-test",
    )

    token = create_access_token(settings=settings, user_id="user-1")

    assert _decode_header(token)["kid"] == "current"
    assert decode_access_token(token, settings=settings).user_id == "user-1"


def test_token_ttl_uses_settings_default_and_explicit_override():
    settings = Settings(
        auth_jwt_secret="secret-1",
        auth_jwt_issuer="focus-agent-test",
        auth_access_token_ttl_seconds=900,
    )

    default_ttl_token = create_access_token(settings=settings, user_id="user-1")
    default_payload = _decode_payload(default_ttl_token)
    assert int(default_payload["exp"]) - int(default_payload["iat"]) == 900

    override_ttl_token = create_access_token(
        settings=settings,
        user_id="user-1",
        expires_in_seconds=60,
    )
    override_payload = _decode_payload(override_ttl_token)
    assert int(override_payload["exp"]) - int(override_payload["iat"]) == 60


def test_secret_rotation_rejects_tokens_signed_with_previous_secret():
    old_settings = Settings(auth_jwt_secret="old-secret", auth_jwt_issuer="focus-agent-test")
    new_settings = Settings(auth_jwt_secret="new-secret", auth_jwt_issuer="focus-agent-test")
    token = create_access_token(settings=old_settings, user_id="user-1")

    with pytest.raises(AuthError, match="signature is invalid"):
        decode_access_token(token, settings=new_settings)


def test_jwt_key_rotation_accepts_old_and_new_active_secrets():
    settings = Settings(
        auth_jwt_key_id="new",
        auth_jwt_keys=(
            AuthJwtKey(kid="new", secret="new-secret"),
            AuthJwtKey(kid="old", secret="old-secret"),
        ),
        auth_jwt_issuer="focus-agent-test",
    )
    now = int(time.time())
    base_payload = {"iss": "focus-agent-test", "sub": "user-1", "iat": now, "exp": now + 3600}

    new_token = create_access_token(settings=settings, user_id="user-1")
    old_token = _signed_token(settings, base_payload, secret="old-secret", kid="old")

    assert _decode_header(new_token)["kid"] == "new"
    assert decode_access_token(new_token, settings=settings).user_id == "user-1"
    assert decode_access_token(old_token, settings=settings).user_id == "user-1"


def test_jwt_key_rotation_rejects_wrong_kid_without_secret_fallback():
    settings = Settings(
        auth_jwt_secret="new-secret",
        auth_jwt_key_id="new",
        auth_jwt_keys=(AuthJwtKey(kid="old", secret="old-secret"),),
        auth_jwt_issuer="focus-agent-test",
    )
    now = int(time.time())
    payload = {"iss": "focus-agent-test", "sub": "user-1", "iat": now, "exp": now + 3600}
    token = _signed_token(settings, payload, secret="new-secret", kid="old")

    with pytest.raises(AuthError, match="signature is invalid"):
        decode_access_token(token, settings=settings)


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


def test_rotated_external_jwt_still_rejects_expired_token():
    settings = Settings(
        auth_jwt_key_id="old",
        auth_jwt_keys=(AuthJwtKey(kid="old", secret="old-secret"),),
        auth_jwt_issuer="focus-agent-test",
    )
    now = int(time.time())
    token = _signed_token(
        settings,
        {"iss": "focus-agent-test", "sub": "user-1", "iat": now - 3600, "exp": now - 1},
        secret="old-secret",
        kid="old",
    )

    with pytest.raises(AuthError, match="expired"):
        decode_access_token(token, settings=settings)


def test_rotated_external_jwt_still_rejects_wrong_issuer_and_audience():
    settings = Settings(
        auth_jwt_key_id="current",
        auth_jwt_keys=(AuthJwtKey(kid="current", secret="secret-1"),),
        auth_jwt_issuer="focus-agent-test",
        auth_jwt_audience="focus-agent-web",
    )
    now = int(time.time())
    base_payload = {
        "iss": "focus-agent-test",
        "aud": "focus-agent-web",
        "sub": "user-1",
        "iat": now,
        "exp": now + 3600,
    }

    wrong_issuer = _signed_token(
        settings,
        {**base_payload, "iss": "other-issuer"},
        secret="secret-1",
        kid="current",
    )
    with pytest.raises(AuthError, match="issuer mismatch"):
        decode_access_token(wrong_issuer, settings=settings)

    wrong_audience = _signed_token(
        settings,
        {**base_payload, "aud": "other-client"},
        secret="secret-1",
        kid="current",
    )
    with pytest.raises(AuthError, match="audience mismatch"):
        decode_access_token(wrong_audience, settings=settings)
