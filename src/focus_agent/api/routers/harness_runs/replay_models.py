from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class HarnessRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str | None = None
    input: dict[str, Any] | None = None
    model: str | None = None
    thinking_mode: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    skill_hints: list[str] = Field(default_factory=list)
    on_disconnect: Literal["cancel", "continue", "rollback"] = "cancel"
    multitask_strategy: Literal["reject", "interrupt", "rollback", "enqueue"] = "reject"


class HarnessRunResponse(BaseModel):
    run: dict[str, Any]
    thread_state: dict[str, Any] | None = None


class HarnessRunCancelRequest(BaseModel):
    action: Literal["interrupt", "rollback"] = "interrupt"


class HarnessResumeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    resume: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    on_disconnect: Literal["cancel", "continue", "rollback"] = "cancel"
    multitask_strategy: Literal["reject", "interrupt", "rollback", "enqueue"] = "reject"


__all__ = [
    "HarnessResumeRequest",
    "HarnessRunCancelRequest",
    "HarnessRunRequest",
    "HarnessRunResponse",
]
