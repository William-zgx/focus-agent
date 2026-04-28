from __future__ import annotations

import logging
from typing import Any

from ..core.branching import BranchMeta
from ..observability.tracing import TraceCorrelation
from ..observability.trajectory import build_turn_trajectory_record

logger = logging.getLogger("focus_agent.chat")


def record_turn_trajectory_best_effort(
    *,
    recorder: Any,
    settings: Any,
    thread_id: str,
    user_id: str,
    root_thread_id: str,
    kind: str,
    status: str,
    final_values: dict[str, Any],
    initial_message_count: int,
    initial_llm_calls: int,
    started_at: Any,
    finished_at: Any,
    branch_meta: BranchMeta | None,
    trace_correlation: TraceCorrelation | None = None,
    input_messages: list[Any] | None = None,
    answer: str | None = None,
    error: str | None = None,
) -> None:
    if recorder is None:
        return
    record_turn = getattr(recorder, 'record_turn', None)
    if not callable(record_turn):
        return
    try:
        record = build_turn_trajectory_record(
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=root_thread_id,
            kind=kind,
            status=status,
            final_values=final_values,
            initial_message_count=initial_message_count,
            initial_llm_calls=initial_llm_calls,
            started_at=started_at,
            finished_at=finished_at,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
            input_messages=input_messages,
            answer=answer,
            error=error,
            observation_max_chars=settings.trajectory_observation_max_chars,
            answer_max_chars=settings.trajectory_answer_max_chars,
            hash_user_id=settings.trajectory_hash_user_id,
        )
        record_turn(record)
    except Exception:  # noqa: BLE001
        logger.warning("failed to persist turn trajectory", exc_info=True)
