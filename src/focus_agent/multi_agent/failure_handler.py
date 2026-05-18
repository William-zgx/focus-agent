"""Failure strategy ladder for retry, reassignment, degradation, and escalation."""

from __future__ import annotations

from .contracts import FailureStrategy


class FailureHandler:
    """Deterministic failure policy: retry, reassign, degrade, then escalate."""

    def __init__(
        self,
        *,
        retry_attempts: int = 1,
        reassign_attempts: int = 2,
        degradable_errors: set[str] | None = None,
    ) -> None:
        self.retry_attempts = max(0, int(retry_attempts or 0))
        self.reassign_attempts = max(self.retry_attempts, int(reassign_attempts or 0))
        self.degradable_errors = degradable_errors or {
            "timeout",
            "tool_error",
            "model_error",
            "execution_error",
        }

    def decide(self, *, task_id: str, error_category: str, attempt: int) -> FailureStrategy:
        if not str(task_id or "").strip():
            raise ValueError("task_id is required")
        normalized_error = str(error_category or "execution_error").strip().lower()
        current_attempt = max(1, int(attempt or 1))
        if current_attempt <= self.retry_attempts:
            return FailureStrategy.RETRY
        if current_attempt <= self.reassign_attempts:
            return FailureStrategy.REASSIGN
        if normalized_error in self.degradable_errors:
            return FailureStrategy.DEGRADE
        return FailureStrategy.ESCALATE


__all__ = ["FailureHandler"]
