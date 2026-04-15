"""Compatibility shim.

Canonical import:
    from focus_agent.security.tokens import (
        AuthError,
        Principal,
        create_access_token,
        decode_access_token,
    )
"""

from .security.tokens import AuthError, Principal, create_access_token, decode_access_token

__all__ = [
    "AuthError",
    "Principal",
    "create_access_token",
    "decode_access_token",
]
