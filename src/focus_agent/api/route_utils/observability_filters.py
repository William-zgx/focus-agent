from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Query

from focus_agent.repositories.postgres_trajectory_repository import TrajectoryTurnQuery

from .trajectory import _trajectory_filters_payload, _trajectory_query_from_request


@dataclass(frozen=True, slots=True)
class ObservabilityTrajectoryFilters:
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

    def _kwargs(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "thread_id": self.thread_id,
            "root_thread_id": self.root_thread_id,
            "parent_thread_id": self.parent_thread_id,
            "branch_id": self.branch_id,
            "branch_role": self.branch_role,
            "status": self.status,
            "scene": self.scene,
            "kind": self.kind,
            "tool": self.tool,
            "model": self.model,
            "fallback_used": self.fallback_used,
            "cache_hit": self.cache_hit,
            "has_error": self.has_error,
            "started_after": self.started_after,
            "started_before": self.started_before,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "min_tool_calls": self.min_tool_calls,
            "max_tool_calls": self.max_tool_calls,
        }

    def payload(self) -> dict[str, Any]:
        return _trajectory_filters_payload(**self._kwargs())

    def query(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        newest_first: bool = True,
    ) -> TrajectoryTurnQuery:
        return _trajectory_query_from_request(
            **self._kwargs(),
            limit=limit,
            offset=offset,
            newest_first=newest_first,
        )


@dataclass(frozen=True, slots=True)
class ObservabilityTrajectoryParams:
    filters: ObservabilityTrajectoryFilters
    limit: int | None = None
    offset: int = 0
    newest_first: bool = True

    def payload(self) -> dict[str, Any]:
        return self.filters.payload()

    def query(self) -> TrajectoryTurnQuery:
        return self.filters.query(
            limit=self.limit,
            offset=self.offset,
            newest_first=self.newest_first,
        )


def _build_observability_trajectory_params(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    thread_id: str | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
    branch_id: str | None = None,
    branch_role: Sequence[str] | None = None,
    status: Sequence[str] | None = None,
    scene: Sequence[str] | None = None,
    kind: Sequence[str] | None = None,
    tool: Sequence[str] | None = None,
    model: Sequence[str] | None = None,
    fallback_used: bool | None = None,
    cache_hit: bool | None = None,
    has_error: bool | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_latency_ms: float | None = None,
    max_latency_ms: float | None = None,
    min_tool_calls: int | None = None,
    max_tool_calls: int | None = None,
    limit: int | None = None,
    offset: int = 0,
    newest_first: bool = True,
) -> ObservabilityTrajectoryParams:
    return ObservabilityTrajectoryParams(
        filters=ObservabilityTrajectoryFilters(
            request_id=request_id,
            trace_id=trace_id,
            thread_id=thread_id,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
            branch_id=branch_id,
            branch_role=branch_role,
            status=status,
            scene=scene,
            kind=kind,
            tool=tool,
            model=model,
            fallback_used=fallback_used,
            cache_hit=cache_hit,
            has_error=has_error,
            started_after=started_after,
            started_before=started_before,
            min_latency_ms=min_latency_ms,
            max_latency_ms=max_latency_ms,
            min_tool_calls=min_tool_calls,
            max_tool_calls=max_tool_calls,
        ),
        limit=limit,
        offset=offset,
        newest_first=newest_first,
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
    return _build_observability_trajectory_params(
        request_id=request_id,
        trace_id=trace_id,
        thread_id=thread_id,
        root_thread_id=root_thread_id,
        parent_thread_id=parent_thread_id,
        branch_id=branch_id,
        branch_role=branch_role,
        status=status,
        scene=scene,
        kind=kind,
        tool=tool,
        model=model,
        fallback_used=fallback_used,
        cache_hit=cache_hit,
        has_error=has_error,
        started_after=started_after,
        started_before=started_before,
        min_latency_ms=min_latency_ms,
        max_latency_ms=max_latency_ms,
        min_tool_calls=min_tool_calls,
        max_tool_calls=max_tool_calls,
        newest_first=newest_first,
    )


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
    return _build_observability_trajectory_params(
        request_id=request_id,
        trace_id=trace_id,
        thread_id=thread_id,
        root_thread_id=root_thread_id,
        parent_thread_id=parent_thread_id,
        branch_id=branch_id,
        branch_role=branch_role,
        status=status,
        scene=scene,
        kind=kind,
        tool=tool,
        model=model,
        fallback_used=fallback_used,
        cache_hit=cache_hit,
        has_error=has_error,
        started_after=started_after,
        started_before=started_before,
        min_latency_ms=min_latency_ms,
        max_latency_ms=max_latency_ms,
        min_tool_calls=min_tool_calls,
        max_tool_calls=max_tool_calls,
        limit=limit,
        offset=offset,
        newest_first=newest_first,
    )


__all__ = [
    "ObservabilityTrajectoryFilters",
    "ObservabilityTrajectoryParams",
    "observability_trajectory_list_params",
    "observability_trajectory_params",
]
