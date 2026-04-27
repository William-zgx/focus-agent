"""Pure token usage helpers shared by API routes."""

from __future__ import annotations

from typing import Any, Sequence

from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.postgres_trajectory_repository import TrajectoryTurnQuery

from .trajectory import maybe_get_trajectory_repository


def normalize_token_usage(raw: dict[str, Any] | None = None) -> dict[str, int]:
    payload = dict(raw or {})
    input_tokens = int(payload.get("input_tokens") or 0)
    output_tokens = int(payload.get("output_tokens") or 0)
    total_tokens = int(payload.get("total_tokens") or (input_tokens + output_tokens))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def accumulate_token_usage(current: dict[str, int], delta: dict[str, int] | None = None) -> dict[str, int]:
    normalized = normalize_token_usage(delta)
    return {
        "input_tokens": int(current.get("input_tokens") or 0) + normalized["input_tokens"],
        "output_tokens": int(current.get("output_tokens") or 0) + normalized["output_tokens"],
        "total_tokens": int(current.get("total_tokens") or 0) + normalized["total_tokens"],
    }


def aggregate_token_usage_from_turns(turns: Sequence[dict[str, Any]]) -> dict[str, int]:
    total = normalize_token_usage()
    for turn in turns:
        total = accumulate_token_usage(total, dict(turn.get("metrics") or {}))
    return total


def token_usage_for_root_thread(*, runtime: AppRuntime, root_thread_id: str) -> dict[str, int]:
    repo = maybe_get_trajectory_repository(runtime)
    if repo is None:
        return normalize_token_usage()
    try:
        turns = repo.list_turns(TrajectoryTurnQuery(root_thread_id=root_thread_id, limit=None, newest_first=True))
    except Exception:  # noqa: BLE001
        return normalize_token_usage()
    return aggregate_token_usage_from_turns(turns)


def token_usage_by_thread_for_root(*, runtime: AppRuntime, root_thread_id: str) -> dict[str, dict[str, int]]:
    repo = maybe_get_trajectory_repository(runtime)
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
        grouped[thread_id] = accumulate_token_usage(
            grouped.get(thread_id, normalize_token_usage()),
            dict(turn.get("metrics") or {}),
        )
    return grouped


def annotate_branch_tree_token_usage(
    node,
    *,
    by_thread_id: dict[str, dict[str, int]],
    root_thread_usage: dict[str, int] | None = None,
):
    is_root_main_node = not getattr(node, "branch_id", None) and str(getattr(node, "thread_id", "")) == str(
        getattr(node, "root_thread_id", "")
    )
    token_usage = root_thread_usage if is_root_main_node and root_thread_usage is not None else by_thread_id.get(node.thread_id)
    return node.model_copy(
        update={
            "token_usage": normalize_token_usage(token_usage),
            "children": [
                annotate_branch_tree_token_usage(
                    child,
                    by_thread_id=by_thread_id,
                    root_thread_usage=root_thread_usage,
                )
                for child in list(node.children or [])
            ],
        }
    )


__all__ = [
    "accumulate_token_usage",
    "aggregate_token_usage_from_turns",
    "annotate_branch_tree_token_usage",
    "normalize_token_usage",
    "token_usage_by_thread_for_root",
    "token_usage_for_root_thread",
]
