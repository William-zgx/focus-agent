from __future__ import annotations

from pydantic import BaseModel, Field

from focus_agent.core.governance import (
    BranchDecisionConfig,
    BranchDecisionEvent,
    BranchDecisionSummary,
)


class BranchDecisionConfigResponse(BranchDecisionConfig):
    pass


class BranchDecisionEventResponse(BranchDecisionEvent):
    pass


class BranchDecisionListResponse(BaseModel):
    items: list[BranchDecisionEventResponse] = Field(default_factory=list)
    count: int = 0


class BranchDecisionDismissRequest(BaseModel):
    reason: str | None = None


class BranchDecisionSummaryResponse(BranchDecisionSummary):
    pass


__all__ = [
    "BranchDecisionConfigResponse",
    "BranchDecisionDismissRequest",
    "BranchDecisionEventResponse",
    "BranchDecisionListResponse",
    "BranchDecisionSummaryResponse",
]
