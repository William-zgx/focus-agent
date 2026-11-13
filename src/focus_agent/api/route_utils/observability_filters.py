from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Query

from focus_agent.repositories.postgres_trajectory_repository import TrajectoryTurnQuery

from .trajectory import _trajectory_filters_payload, _trajectory_query_from_request

_PAGINATION_ONLY_FIELDS = frozenset({"limit", "offset", "newest_first"})


@dataclass(frozen=True, slots=True)
class ObservabilityTrajectoryParams:
    request_id: str | None = None
    trace_id: str | None = None
    thread_id: str | None = None
    root_thread_id: str | None = None
    parent_thread_id: str | None = None
    branch_id: str | None = None
    branch_role: Sequence[str] | None = None
    status: Sequence[str] | None = None
    scene: Sequence[str] | None = None
    kind: Sequence[str] | None = None
    tool: Sequence[str] | None = None
    model: Sequence[str] | None = None
    fallback_used: bool | None = None
    cache_hit: bool | None = None
    has_error: bool | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None
    min_latency_ms: float | None = None
    max_latency_ms: float | None = None
    min_tool_calls: int | None = None
    max_tool_calls: int | None = None
    limit: int | None = None
    offset: int = 0
    newest_first: bool = True

    def _filter_kwargs(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name not in _PAGINATION_ONLY_FIELDS
        }

    def payload(self) -> dict[str, Any]:
        return _trajectory_filters_payload(**self._filter_kwargs())

    def query(self) -> TrajectoryTurnQuery:
        return _trajectory_query_from_request(
            **self._filter_kwargs(),
            limit=self.limit,
            offset=self.offset,
            newest_first=self.newest_first,
        )


def observability_trajectory_params(
    request_id: str | None = None,
    trace_id: str | None = None,
    thread_id: str | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
    branch_id: str | None = None,
    branch_role: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    scene: list[str] | None = Query(default=None),
    kind: list[str] | None = Query(default=None),
    tool: list[str] | None = Query(default=None),
    model: list[str] | None = Query(default=None, alias="model"),
    fallback_used: bool | None = None,
    cache_hit: bool | None = None,
    has_error: bool | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_latency_ms: float | None = None,
    max_latency_ms: float | None = None,
    min_tool_calls: int | None = None,
    max_tool_calls: int | None = None,
    newest_first: bool = True,
) -> ObservabilityTrajectoryParams:
    return ObservabilityTrajectoryParams(**locals())


def observability_trajectory_list_params(
    request_id: str | None = None,
    trace_id: str | None = None,
    thread_id: str | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
    branch_id: str | None = None,
    branch_role: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    scene: list[str] | None = Query(default=None),
    kind: list[str] | None = Query(default=None),
    tool: list[str] | None = Query(default=None),
    model: list[str] | None = Query(default=None, alias="model"),
    fallback_used: bool | None = None,
    cache_hit: bool | None = None,
    has_error: bool | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_latency_ms: float | None = None,
    max_latency_ms: float | None = None,
    min_tool_calls: int | None = None,
    max_tool_calls: int | None = None,
    limit: int = Query(default=100, ge=0),
    offset: int = Query(default=0, ge=0),
    newest_first: bool = True,
) -> ObservabilityTrajectoryParams:
    return ObservabilityTrajectoryParams(**locals())


__all__ = [
    "ObservabilityTrajectoryParams",
    "observability_trajectory_list_params",
    "observability_trajectory_params",
]
