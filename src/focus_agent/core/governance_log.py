"""Append-only governance record log.

Inspired by pi/opencode's event-sourced audit trail, ``GovernanceLog``
provides an in-memory, append-only container for governance records
extracted from ``AgentState.governance_records``. It supports filtering by
domain and cheap retrieval of the latest record for a given domain, which
is the common access pattern when prompt assembly or policy nodes need to
consult the most recent governance decision.

The log intentionally does not subclass ``list`` or expose mutating
sequence methods directly; ``append`` is the only write operation besides
``clear``. This preserves the append-only invariant that downstream
analytics and replay tooling rely on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class GovernanceLog:
    """Append-only log of governance/observability records.

    Parameters
    ----------
    records:
        Optional iterable of seed records. Each item must be a dict-like
        mapping (e.g., an ``AgentStateRecord`` instance).
    """

    __slots__ = ("_records",)

    def __init__(self, records: Iterable[Mapping[str, Any]] | None = None) -> None:
        seed: list[dict[str, Any]] = []
        if records is not None:
            for item in records:
                seed.append(dict(item))
        self._records: list[dict[str, Any]] = seed

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "GovernanceLog":
        """Create a ``GovernanceLog`` view from the current state.

        Reads ``state["governance_records"]`` (defaulting to ``[]``) and
        appends each entry into a new log. The resulting log is an
        independent view; mutating it does not write back to ``state``.
        This is the preferred entry point for read-only querying (e.g. in
        API handlers or service code that needs to filter governance
        history).
        """
        records = state.get("governance_records", []) if state else []
        log = cls()
        for r in records or []:
            log.append(r)
        return log

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------
    def append(self, record: Mapping[str, Any]) -> None:
        """Append a single record to the log.

        The record is shallow-copied into a dict so later mutations of the
        caller's mapping do not affect stored history.
        """
        self._records.append(dict(record))

    def extend(self, records: Iterable[Mapping[str, Any]]) -> None:
        """Append multiple records in iteration order."""
        for record in records:
            self.append(record)

    def clear(self) -> None:
        """Remove all records. Intended for tests and explicit resets only."""
        self._records.clear()

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------
    def all(self) -> list[dict[str, Any]]:
        """Return a shallow copy of every record in insertion order."""
        return list(self._records)

    def query(
        self,
        *,
        domain: str | None = None,
        name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return records matching the given filters.

        Parameters
        ----------
        domain:
            If provided, only records whose ``"domain"`` key matches are
            returned (case-sensitive).
        name:
            If provided, only records whose ``"name"`` key matches are
            returned.
        limit:
            Maximum number of records to return (capped from the *end* of
            the log, i.e. most recent first). Must be >= 1.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")
        results: list[dict[str, Any]] = []
        for record in reversed(self._records):
            if domain is not None and record.get("domain") != domain:
                continue
            if name is not None and record.get("name") != name:
                continue
            results.append(dict(record))
            if len(results) >= limit:
                break
        # Return in chronological order rather than reverse-chronological.
        results.reverse()
        return results

    def latest(
        self,
        name: str | None = None,
        *,
        domain: str | None = None,
        limit: int = 1,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Return the most recent matching record(s), or ``None`` if empty.

        Parameters
        ----------
        name:
            Optional record name to match.
        domain:
            Optional domain to match.
        limit:
            Number of recent records to return. When ``limit == 1`` (the
            default) a single dict or ``None`` is returned; otherwise a
            list (possibly empty) is returned in chronological order.
        """
        records = self.query(domain=domain, name=name, limit=max(limit, 1))
        if limit == 1:
            return records[-1] if records else None
        return records

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    @property
    def count(self) -> int:
        """Number of records currently in the log."""
        return len(self._records)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return self.count

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return bool(self._records)

    def __iter__(self):  # pragma: no cover - trivial
        return iter(self._records)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<GovernanceLog count={self.count}>"


__all__ = ["GovernanceLog"]
