"""Trajectory repository helpers for API routes."""

from __future__ import annotations

from typing import Any

from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.postgres_trajectory_repository import PostgresTrajectoryRepository


def maybe_get_trajectory_repository(runtime: AppRuntime | Any) -> PostgresTrajectoryRepository | Any | None:
    candidate = getattr(runtime, "trajectory_recorder", None)
    required_methods = ("list_turns", "get_turn", "list_steps_by_turn_ids", "get_turn_stats")
    if candidate is not None and all(callable(getattr(candidate, name, None)) for name in required_methods):
        return candidate
    database_uri = getattr(getattr(runtime, "settings", None), "database_uri", None)
    if database_uri:
        return PostgresTrajectoryRepository(database_uri)
    return None


__all__ = ["maybe_get_trajectory_repository"]
