from __future__ import annotations

from typing import Any

from ..config import Settings
from ..core.branching import BranchMeta


def build_trace_metadata(
    *,
    settings: Settings,
    thread_id: str,
    user_id: str,
    root_thread_id: str,
    branch_meta: BranchMeta | None = None,
    scene: str = "long_dialog_research",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "thread_id": thread_id,
        "root_thread_id": root_thread_id,
        "scene": scene,
        "user_id": user_id,
        "app_version": settings.app_version,
    }
    if branch_meta is not None:
        metadata.update(
            {
                "parent_thread_id": branch_meta.parent_thread_id,
                "branch_id": branch_meta.branch_id,
                "branch_depth": branch_meta.branch_depth,
                "branch_status": branch_meta.branch_status.value,
                "branch_role": branch_meta.branch_role.value,
            }
        )
    return metadata


def build_trace_tags(*, root_thread_id: str, thread_id: str, branch_meta: BranchMeta | None = None) -> list[str]:
    tags = [
        "focus-agent",
        "long-dialogue",
        "research",
        f"root:{root_thread_id}",
        f"thread:{thread_id}",
    ]
    if branch_meta is not None:
        tags.extend(
            [
                "branch",
                f"branch:{branch_meta.branch_id}",
                f"status:{branch_meta.branch_status.value}",
            ]
        )
    else:
        tags.append("main")
    return tags


def build_invoke_config(
    *,
    settings: Settings,
    thread_id: str,
    user_id: str,
    root_thread_id: str,
    branch_meta: BranchMeta | None = None,
    run_name: str = "focus_agent_turn",
    scene: str = "long_dialog_research",
) -> dict[str, Any]:
    return {
        "run_name": run_name,
        "configurable": {"thread_id": thread_id},
        "metadata": build_trace_metadata(
            settings=settings,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=root_thread_id,
            branch_meta=branch_meta,
            scene=scene,
        ),
        "tags": build_trace_tags(root_thread_id=root_thread_id, thread_id=thread_id, branch_meta=branch_meta),
    }
