from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 210_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _pbkdf2(password, salt, PBKDF2_ITERATIONS)
    return "$".join(
        (
            PBKDF2_ALGORITHM,
            str(PBKDF2_ITERATIONS),
            _b64(salt),
            _b64(digest),
        )
    )


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
    except (TypeError, ValueError):
        return False
    if algorithm != PBKDF2_ALGORITHM or iterations <= 0:
        return False
    actual = _pbkdf2(password, salt, iterations)
    return hmac.compare_digest(actual, expected)


def password_needs_rehash(encoded: str | None) -> bool:
    if not encoded:
        return True
    try:
        algorithm, iterations_text, _, _ = encoded.split("$", 3)
        iterations = int(iterations_text)
    except (TypeError, ValueError):
        return True
    return algorithm != PBKDF2_ALGORITHM or iterations < PBKDF2_ITERATIONS


def _pbkdf2(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


__all__ = [
    "PBKDF2_ALGORITHM",
    "PBKDF2_ITERATIONS",
    "hash_password",
    "password_needs_rehash",
    "verify_password",
]
