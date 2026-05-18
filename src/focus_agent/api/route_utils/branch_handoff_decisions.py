from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("focus_agent.api.branch_handoff_decisions")


def record_branch_handoff_decision_for_run(
    *,
    runtime: Any,
    thread_id: str,
    user_id: str,
    message: str | None,
    root_thread_id: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    run_id: str | None = None,
    run_status: str | None = None,
) -> Any | None:
    service = getattr(runtime, "branch_decision_service", None)
    handler = getattr(service, "record_branch_handoff_decision", None)
    if callable(handler):
        try:
            return handler(
                thread_id=thread_id,
                user_id=user_id,
                message=message,
                root_thread_id=root_thread_id,
                run_id=run_id,
                run_status=run_status,
                request_id=request_id,
                trace_id=trace_id,
            )
        except TypeError:
            logger.debug("branch handoff decision service does not accept public signature")
        except Exception:  # noqa: BLE001 - handoff evidence must never block chat.
            logger.debug("failed to record branch handoff decision", exc_info=True)
            return None
    handler = getattr(service, "record_branch_handoff_auto_run_decision", None)
    if not callable(handler):
        return None
    try:
        return handler(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            root_thread_id=root_thread_id,
            handoff_run_id=run_id,
            handoff_run_status=run_status,
            request_id=request_id,
            trace_id=trace_id,
        )
    except Exception:  # noqa: BLE001 - handoff evidence must never block chat.
        logger.debug("failed to record branch handoff decision", exc_info=True)
        return None


def mark_branch_handoff_decision_outcome(
    *,
    runtime: Any,
    decision: Any | None,
    run_status: str,
    run_id: str | None = None,
    message: str | None = None,
    error: str | None = None,
) -> Any | None:
    if isinstance(decision, dict):
        decision_id = str(decision.get("decision_id") or "")
    else:
        decision_id = str(getattr(decision, "decision_id", "") or "")
    if not decision_id:
        return None
    service = getattr(runtime, "branch_decision_service", None)
    handler = getattr(service, "mark_branch_handoff_decision_outcome", None)
    if callable(handler):
        try:
            return handler(
                decision_id=decision_id,
                run_id=run_id,
                run_status=run_status,
                message=message,
                error=error,
            )
        except TypeError:
            logger.debug("branch handoff outcome service does not accept public signature")
        except Exception:  # noqa: BLE001 - outcome evidence must never block chat.
            logger.debug("failed to update branch handoff decision", exc_info=True)
            return None
    handler = getattr(service, "update_branch_handoff_auto_run_outcome", None)
    if not callable(handler):
        return None
    try:
        return handler(
            decision_id=decision_id,
            handoff_run_id=run_id,
            handoff_run_status=run_status,
            message=message,
            error=error,
        )
    except Exception:  # noqa: BLE001 - outcome evidence must never block chat.
        logger.debug("failed to update branch handoff decision", exc_info=True)
        return None


async def ensure_branch_handoff_decision_from_journal(
    *,
    runtime: Any,
    thread_id: str,
    user_id: str,
    request_id: str | None = None,
) -> Any | None:
    service = getattr(runtime, "branch_decision_service", None)
    list_decisions = getattr(service, "list_decisions", None)
    if not callable(list_decisions):
        return None
    try:
        existing = list_decisions(thread_id=thread_id, user_id=user_id, limit=1)
    except Exception:  # noqa: BLE001
        return None
    if existing:
        return existing[0]

    journal = getattr(runtime, "event_store", None) or getattr(
        getattr(runtime, "harness", None),
        "event_store",
        None,
    )
    list_runs = getattr(journal, "list_runs", None)
    if not callable(list_runs):
        return None
    try:
        runs = await list_runs(thread_id=thread_id)
    except Exception:  # noqa: BLE001
        logger.debug("failed to inspect run journal for branch handoff", exc_info=True)
        return None

    handoff_runs = [
        run
        for run in runs
        if isinstance(getattr(run, "metadata", None), dict)
        and run.metadata.get("branch_handoff_auto_run") is True
    ]
    if not handoff_runs:
        return None
    run = handoff_runs[-1]
    message = _handoff_message_from_run(run)
    event = record_branch_handoff_decision_for_run(
        runtime=runtime,
        thread_id=thread_id,
        user_id=user_id,
        message=message,
        request_id=request_id,
        root_thread_id=_root_thread_id_from_run(run),
        run_id=getattr(run, "run_id", None),
        run_status=getattr(run, "status", None),
    )
    if event is not None:
        mark_branch_handoff_decision_outcome(
            runtime=runtime,
            decision=event,
            run_status=str(getattr(run, "status", "") or ""),
            run_id=getattr(run, "run_id", None),
            message=message,
            error=getattr(run, "error", None),
        )
    return event


def _handoff_message_from_run(run: Any) -> str:
    kwargs = getattr(run, "kwargs", None)
    if not isinstance(kwargs, dict):
        return ""
    input_payload = kwargs.get("input")
    if not isinstance(input_payload, dict):
        return ""
    task_brief = str(input_payload.get("task_brief") or "").strip()
    if task_brief:
        return task_brief
    messages = input_payload.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _root_thread_id_from_run(run: Any) -> str | None:
    metadata = getattr(run, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("root_thread_id", "rootThreadId"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
    kwargs = getattr(run, "kwargs", None)
    if isinstance(kwargs, dict):
        for key in ("root_thread_id", "rootThreadId"):
            value = str(kwargs.get(key) or "").strip()
            if value:
                return value
    return None


__all__ = [
    "ensure_branch_handoff_decision_from_journal",
    "mark_branch_handoff_decision_outcome",
    "record_branch_handoff_decision_for_run",
]
