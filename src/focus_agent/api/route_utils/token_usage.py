from __future__ import annotations

from typing import Any, Sequence

from focus_agent.core.token_usage import (
    accumulate_token_usage,
    messages_token_usage,
    normalize_token_usage,
)
from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.postgres_trajectory_repository import TrajectoryTurnQuery

from .trajectory import _maybe_get_trajectory_repository


def _normalize_token_usage(raw: dict[str, Any] | None = None) -> dict[str, int]:
    return normalize_token_usage(raw)


def _accumulate_token_usage(
    current: dict[str, int], delta: dict[str, int] | None = None
) -> dict[str, int]:
    return accumulate_token_usage(current, delta)


def _aggregate_token_usage_from_turns(turns: Sequence[dict[str, Any]]) -> dict[str, int]:
    total = _normalize_token_usage()
    for turn in turns:
        total = _accumulate_token_usage(total, dict(turn.get("metrics") or {}))
    return total


def _token_usage_for_root_thread(*, runtime: AppRuntime, root_thread_id: str) -> dict[str, int]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return _aggregate_token_usage_from_thread_map(
            _token_usage_by_thread_from_graph(runtime=runtime, root_thread_id=root_thread_id)
        )
    aggregate = getattr(repo, "get_root_thread_token_usage", None)
    if callable(aggregate):
        try:
            return _normalize_token_usage(aggregate(root_thread_id))
        except Exception:  # noqa: BLE001
            return _normalize_token_usage()
    try:
        turns = repo.list_turns(
            TrajectoryTurnQuery(root_thread_id=root_thread_id, limit=None, newest_first=True)
        )
    except Exception:  # noqa: BLE001
        return _normalize_token_usage()
    return _aggregate_token_usage_from_turns(turns)


def _token_usage_by_thread_for_root(
    *, runtime: AppRuntime, root_thread_id: str
) -> dict[str, dict[str, int]]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return _token_usage_by_thread_from_graph(runtime=runtime, root_thread_id=root_thread_id)
    aggregate = getattr(repo, "get_thread_token_usage_for_root", None)
    if callable(aggregate):
        try:
            rows = aggregate(root_thread_id)
        except Exception:  # noqa: BLE001
            return {}
        return {
            str(thread_id): _normalize_token_usage(usage)
            for thread_id, usage in dict(rows or {}).items()
            if str(thread_id).strip()
        }
    try:
        turns = repo.list_turns(
            TrajectoryTurnQuery(root_thread_id=root_thread_id, limit=None, newest_first=True)
        )
    except Exception:  # noqa: BLE001
        return {}

    grouped: dict[str, dict[str, int]] = {}
    for turn in turns:
        thread_id = str(turn.get("thread_id") or "").strip()
        if not thread_id:
            continue
        grouped[thread_id] = _accumulate_token_usage(
            grouped.get(thread_id, _normalize_token_usage()), dict(turn.get("metrics") or {})
        )
    return grouped


def _token_usage_by_thread_from_graph(
    *, runtime: AppRuntime, root_thread_id: str
) -> dict[str, dict[str, int]]:
    graph = getattr(runtime, "graph", None)
    if graph is None:
        return {}
    thread_ids = _thread_ids_for_root(runtime=runtime, root_thread_id=root_thread_id)
    usage_by_thread: dict[str, dict[str, int]] = {}
    for thread_id in thread_ids:
        usage = _token_usage_for_thread_from_graph(
            graph=graph,
            thread_id=thread_id,
            is_root_thread=thread_id == root_thread_id,
        )
        if any(usage.values()):
            usage_by_thread[thread_id] = usage
    return usage_by_thread


def _thread_ids_for_root(*, runtime: AppRuntime, root_thread_id: str) -> list[str]:
    thread_ids = [str(root_thread_id)]
    repo = getattr(runtime, "repo", None)
    list_branches = getattr(repo, "list_by_root_thread_id", None)
    if callable(list_branches):
        try:
            records = list_branches(root_thread_id)
        except Exception:  # noqa: BLE001
            records = []
        for record in records or []:
            child_thread_id = str(getattr(record, "child_thread_id", "") or "").strip()
            if child_thread_id and child_thread_id not in thread_ids:
                thread_ids.append(child_thread_id)
    return thread_ids


def _token_usage_for_thread_from_graph(
    *, graph: Any, thread_id: str, is_root_thread: bool
) -> dict[str, int]:
    get_state = getattr(graph, "get_state", None)
    if not callable(get_state):
        return _normalize_token_usage()
    try:
        snapshot = get_state({"configurable": {"thread_id": thread_id}})
    except Exception:  # noqa: BLE001
        return _normalize_token_usage()
    values = dict(getattr(snapshot, "values", {}) or {})
    messages = list(values.get("messages") or [])
    if not is_root_thread:
        fork_message_count = _branch_fork_message_count(
            values.get("branch_meta"),
            message_count=len(messages),
        )
        if fork_message_count is not None:
            messages = messages[fork_message_count:]
        else:
            return _normalize_token_usage()
    return messages_token_usage(messages)


def _branch_fork_message_count(branch_meta: Any, *, message_count: int | None = None) -> int | None:
    if not isinstance(branch_meta, dict):
        return None
    raw = branch_meta.get("branch_fork_message_count")
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return None
    if count < 0:
        return None
    if message_count is not None and count > message_count:
        return message_count
    return count


def _aggregate_token_usage_from_thread_map(
    by_thread_id: dict[str, dict[str, int]],
) -> dict[str, int]:
    total = _normalize_token_usage()
    for usage in by_thread_id.values():
        total = _accumulate_token_usage(total, usage)
    return total


def _annotate_branch_tree_token_usage(
    node,
    *,
    by_thread_id: dict[str, dict[str, int]],
    root_thread_usage: dict[str, int] | None = None,
):
    is_root_main_node = not getattr(node, "branch_id", None) and str(
        getattr(node, "thread_id", "")
    ) == str(getattr(node, "root_thread_id", ""))
    token_usage = (
        root_thread_usage
        if is_root_main_node and root_thread_usage is not None
        else by_thread_id.get(node.thread_id)
    )
    return node.model_copy(
        update={
            "token_usage": _normalize_token_usage(token_usage),
            "children": [
                _annotate_branch_tree_token_usage(
                    child,
                    by_thread_id=by_thread_id,
                    root_thread_usage=root_thread_usage,
                )
                for child in list(node.children or [])
            ],
        }
    )


__all__ = [
    "_normalize_token_usage",
    "_accumulate_token_usage",
    "_aggregate_token_usage_from_turns",
    "_token_usage_for_root_thread",
    "_token_usage_by_thread_for_root",
    "_annotate_branch_tree_token_usage",
]
