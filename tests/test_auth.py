import pytest

from focus_agent.config import Settings
from focus_agent.security.tokens import AuthError
from focus_agent.security.tokens import create_access_token, decode_access_token


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
