from __future__ import annotations

from typing import Any, Sequence

from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.postgres_trajectory_repository import TrajectoryTurnQuery

from .trajectory import _maybe_get_trajectory_repository


def _normalize_token_usage(raw: dict[str, Any] | None = None) -> dict[str, int]:
    payload = dict(raw or {})
    input_tokens = int(payload.get("input_tokens") or 0)
    output_tokens = int(payload.get("output_tokens") or 0)
    total_tokens = int(payload.get("total_tokens") or (input_tokens + output_tokens))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _accumulate_token_usage(current: dict[str, int], delta: dict[str, int] | None = None) -> dict[str, int]:
    normalized = _normalize_token_usage(delta)
    return {
        "input_tokens": int(current.get("input_tokens") or 0) + normalized["input_tokens"],
        "output_tokens": int(current.get("output_tokens") or 0) + normalized["output_tokens"],
        "total_tokens": int(current.get("total_tokens") or 0) + normalized["total_tokens"],
    }


def _aggregate_token_usage_from_turns(turns: Sequence[dict[str, Any]]) -> dict[str, int]:
    total = _normalize_token_usage()
    for turn in turns:
        total = _accumulate_token_usage(total, dict(turn.get("metrics") or {}))
    return total


def _token_usage_for_root_thread(*, runtime: AppRuntime, root_thread_id: str) -> dict[str, int]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return _normalize_token_usage()
    try:
        turns = repo.list_turns(TrajectoryTurnQuery(root_thread_id=root_thread_id, limit=None, newest_first=True))
    except Exception:  # noqa: BLE001
        return _normalize_token_usage()
    return _aggregate_token_usage_from_turns(turns)


def _token_usage_by_thread_for_root(*, runtime: AppRuntime, root_thread_id: str) -> dict[str, dict[str, int]]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return {}
    try:
        turns = repo.list_turns(TrajectoryTurnQuery(root_thread_id=root_thread_id, limit=None, newest_first=True))
    except Exception:  # noqa: BLE001
        return {}

    grouped: dict[str, dict[str, int]] = {}
    for turn in turns:
        thread_id = str(turn.get("thread_id") or "").strip()
        if not thread_id:
            continue
        grouped[thread_id] = _accumulate_token_usage(grouped.get(thread_id, _normalize_token_usage()), dict(turn.get("metrics") or {}))
    return grouped


def _annotate_branch_tree_token_usage(
    node,
    *,
    by_thread_id: dict[str, dict[str, int]],
    root_thread_usage: dict[str, int] | None = None,
):
    is_root_main_node = not getattr(node, "branch_id", None) and str(getattr(node, "thread_id", "")) == str(getattr(node, "root_thread_id", ""))
    token_usage = root_thread_usage if is_root_main_node and root_thread_usage is not None else by_thread_id.get(node.thread_id)
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
