"""Current-time helpers shared across layers (stdlib only)."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    """Current UTC time as ISO 8601 with a ``+00:00`` offset."""

    return datetime.now(UTC).isoformat()


def utc_now_iso_z() -> str:
    """Current UTC time as ISO 8601 with a ``Z`` suffix."""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["utc_now", "utc_now_iso", "utc_now_iso_z"]
