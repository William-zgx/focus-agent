from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RequestContext:
    user_id: str
    root_thread_id: str
    scene: str = "long_dialog_research"
    branch_id: str | None = None
    parent_thread_id: str | None = None
    branch_role: str | None = None
    project_id: str | None = None
    skill_hints: tuple[str, ...] = ()
