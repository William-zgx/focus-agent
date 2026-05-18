from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from focus_agent.core.repo_call import (
    REPO_METHOD_ERROR,
    REPO_METHOD_MISSING,
    has_repo_method,
    safe_repo_call,
)
from focus_agent.core.token_usage import (
    accumulate_token_usage,
    messages_token_usage,
    normalize_token_usage,
)
from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.postgres_trajectory_repository import TrajectoryTurnQuery

from .trajectory import _maybe_get_trajectory_repository


def _aggregate_token_usage_from_turns(turns: Sequence[dict[str, Any]]) -> dict[str, int]:
    total = normalize_token_usage()
    for turn in turns:
        total = accumulate_token_usage(total, dict(turn.get("metrics") or {}))
    return total


def _trajectory_turns_for_root(runtime: AppRuntime, root_thread_id: str) -> list[dict[str, Any]]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return []
    query = TrajectoryTurnQuery(root_thread_id=root_thread_id, limit=None, newest_first=True)
    turns = safe_repo_call(repo, "list_turns", query, default_missing=[], default_error=[])
    return list(turns)


def _token_usage_for_root_thread(*, runtime: AppRuntime, root_thread_id: str) -> dict[str, int]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return _aggregate_token_usage_from_thread_map(
            _token_usage_by_thread_from_graph(runtime=runtime, root_thread_id=root_thread_id)
        )
    aggregate = safe_repo_call(
        repo,
        "get_root_thread_token_usage",
        root_thread_id,
        default_missing=REPO_METHOD_MISSING,
        default_error=REPO_METHOD_ERROR,
    )
    if aggregate is REPO_METHOD_MISSING:
        turns = _trajectory_turns_for_root(runtime=runtime, root_thread_id=root_thread_id)
        return _aggregate_token_usage_from_turns(turns)
    if aggregate is REPO_METHOD_ERROR:
        return normalize_token_usage()
    return normalize_token_usage(aggregate)


def _token_usage_by_thread_for_root(
    *, runtime: AppRuntime, root_thread_id: str
) -> dict[str, dict[str, int]]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return _token_usage_by_thread_from_graph(runtime=runtime, root_thread_id=root_thread_id)
    rows = safe_repo_call(
        repo,
        "get_thread_token_usage_for_root",
        root_thread_id,
        default_missing=REPO_METHOD_MISSING,
        default_error=REPO_METHOD_ERROR,
    )
    if rows is REPO_METHOD_ERROR:
        return {}
    if rows is not REPO_METHOD_MISSING:
        return {
            str(thread_id): normalize_token_usage(usage)
            for thread_id, usage in dict(rows or {}).items()
            if str(thread_id).strip()
        }
    turns = _trajectory_turns_for_root(runtime=runtime, root_thread_id=root_thread_id)

    grouped: dict[str, dict[str, int]] = {}
    for turn in turns:
        thread_id = str(turn.get("thread_id") or "").strip()
        if not thread_id:
            continue
        grouped[thread_id] = accumulate_token_usage(
            grouped.get(thread_id, normalize_token_usage()), dict(turn.get("metrics") or {})
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
    records = safe_repo_call(
        getattr(runtime, "repo", None),
        "list_by_root_thread_id",
        root_thread_id,
        default_missing=[],
        default_error=[],
    )
    for record in records or []:
        child_thread_id = str(getattr(record, "child_thread_id", "") or "").strip()
        if child_thread_id and child_thread_id not in thread_ids:
            thread_ids.append(child_thread_id)
    return thread_ids


def _token_usage_for_thread_from_graph(
    *, graph: Any, thread_id: str, is_root_thread: bool
) -> dict[str, int]:
    if not has_repo_method(graph, "get_state"):
        return normalize_token_usage()
    try:
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    except Exception:  # noqa: BLE001
        return normalize_token_usage()
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
            return normalize_token_usage()
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
    total = normalize_token_usage()
    for usage in by_thread_id.values():
        total = accumulate_token_usage(total, usage)
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
            "token_usage": normalize_token_usage(token_usage),
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
    "_aggregate_token_usage_from_turns",
    "_token_usage_for_root_thread",
    "_token_usage_by_thread_for_root",
    "_annotate_branch_tree_token_usage",
]
