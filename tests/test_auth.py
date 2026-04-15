from focus_agent.config import Settings
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
