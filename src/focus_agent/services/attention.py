from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from pydantic import ValidationError

from focus_agent.core.attention import (
    AttentionCursor,
    AttentionDiff,
    AttentionEvidence,
    AttentionItem,
    AttentionPolicy,
    AttentionReason,
    AttentionSnapshot,
    ResumePacket,
)
from focus_agent.storage.namespaces import attention_cursor_namespace

_CURSOR_KEY = "cursor:v1"
_MAX_OUTCOMES = 512
_MAX_ACTIONS = 512
_MAX_HIGHLIGHTS = 12
_MAX_OPEN_ITEMS = 32
_MAX_DECISIONS = 32
_MAX_EVIDENCE = 64
_FAILURE_STATUSES = {"blocked", "error", "errored", "failed", "failure", "timed_out", "timeout"}
_DEGRADED_STATUSES = {"degraded", "degraded_answer", "partial"}
_SUCCESS_STATUSES = {"complete", "completed", "done", "ok", "recovered", "succeeded", "success"}
_ACTIVE_STATUSES = {"in_progress", "pending", "queued", "running", "started"}
_PENDING_STATUSES = {"awaiting_approval", "awaiting_review", "pending", "proposed", "requested"}
_DECISION_STATUSES = {"adopted", "approved", "merged"}


class AttentionReviewConflictError(ValueError):
    """The presented review cursor cannot be applied to the current thread."""


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _state_value(state: Any, key: str, default: Any = None) -> Any:
    value = _get(state, key)
    if value is not None:
        return value
    values = _get(state, "values")
    if values is not None:
        value = _get(values, key)
        if value is not None:
            return value
    return default


def _text(value: Any, limit: int = 800) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        parts: list[str] = []
        for block in value:
            if isinstance(block, str):
                parts.append(block)
                continue
            block_type = str(_get(block, "type", "text") or "text").lower()
            if block_type not in {"output_text", "text"}:
                continue
            block_text = _get(block, "text")
            if isinstance(block_text, str):
                parts.append(block_text)
        text = "\n".join(part.strip() for part in parts if part.strip()).strip()
    else:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _identifier(record: Any, *names: str) -> str:
    for name in (*names, "id"):
        value = _get(record, name)
        if value is not None and str(value):
            return str(value)
    return ""


def _records(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        if any(key in value for key in ("id", "status", "type", "action_id", "outcome_id")):
            return [value]
        records = []
        for key, item in value.items():
            if isinstance(item, Mapping) and not _identifier(item):
                item = {**item, "id": str(key)}
            records.append(item)
        return records
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _message_type(message: Any) -> str:
    message_type = str(_get(message, "type", "") or "").lower()
    if message_type:
        return message_type
    role = str(_get(message, "role", "") or "").lower()
    return {"user": "human", "assistant": "ai"}.get(role, role)


def _message_id(message: Any) -> str:
    return _identifier(message, "message_id")


def _last_message_id(messages: list[Any]) -> str | None:
    for message in reversed(messages):
        message_id = _message_id(message)
        if message_id:
            return message_id
    return None


def _outcomes(state: Any) -> list[Any]:
    return _records(_state_value(state, "tool_outcomes", []))


def _outcome_id(outcome: Any) -> str:
    return _identifier(outcome, "outcome_id", "tool_call_id")


def _status(record: Any) -> str:
    value = _get(record, "status", "") or ""
    return str(value).lower()


def _actions(state: Any) -> list[Any]:
    return _records(_state_value(state, "branch_actions", []))


def _action_id(action: Any) -> str:
    return _identifier(action, "action_id")


def _merge_records(state: Any, thread_id: str) -> list[tuple[str, str, str, Any]]:
    branch_meta = _state_value(state, "branch_meta", {})
    branch_status = str(_get(branch_meta, "branch_status", "") or "").lower()
    owner_id = _identifier(branch_meta, "branch_id") or thread_id
    decision = _state_value(state, "merge_decision")
    proposal = _state_value(state, "merge_proposal")
    records: list[tuple[str, str, str, Any]] = []
    if decision:
        approved = _get(decision, "approved") is True
        status = "merged" if approved and branch_status == "merged" else "approved"
        if not approved:
            status = "rejected"
        records.append(("merge_decision", owner_id, status, decision))
    elif proposal and branch_status == "awaiting_merge_review":
        records.append(("proposal", owner_id, "pending", proposal))
    for index, imported in enumerate(_records(_state_value(state, "merge_queue", []))):
        source_id = _identifier(imported, "child_thread_id", "branch_id") or f"{owner_id}:{index}"
        records.append(("proposal", source_id, "merged", imported))
    return records


def _interrupts(state: Any) -> list[Any]:
    records = _records(_state_value(state, "interrupts", []))
    records.extend(_records(_state_value(state, "__interrupt__", [])))
    return records


def _current_cursor(state: Any) -> AttentionCursor:
    messages = list(_state_value(state, "messages", []) or [])
    outcome_ids = list(
        dict.fromkeys(filter(None, (_outcome_id(item) for item in _outcomes(state))))
    )
    action_statuses = {
        action_id: _status(action)
        for action in _actions(state)
        if (action_id := _action_id(action)) and _status(action)
    }
    return AttentionCursor(
        last_message_id=_last_message_id(messages),
        seen_outcome_ids=outcome_ids[-_MAX_OUTCOMES:],
        action_statuses=dict(list(action_statuses.items())[-_MAX_ACTIONS:]),
    )


def _same_frontier(left: AttentionCursor, right: AttentionCursor) -> bool:
    return left.model_dump(exclude={"reviewed_at"}) == right.model_dump(exclude={"reviewed_at"})


def _with_reviewed_time(
    current: AttentionCursor,
    stored: AttentionCursor | None,
    *,
    reviewed_at: str | None,
) -> AttentionCursor:
    if stored is not None and _same_frontier(current, stored):
        return current.model_copy(update={"reviewed_at": stored.reviewed_at})
    return current.model_copy(update={"reviewed_at": reviewed_at})


def _merge_review_cursor(
    state: Any,
    presented: AttentionCursor,
    stored: AttentionCursor | None,
    *,
    reviewed_at: str,
) -> AttentionCursor:
    if stored is None:
        return presented.model_copy(update={"reviewed_at": reviewed_at})
    message_ids = [
        message_id
        for message in list(_state_value(state, "messages", []) or [])
        if (message_id := _message_id(message))
    ]
    positions = {message_id: index for index, message_id in enumerate(message_ids)}
    last_message_id = presented.last_message_id
    if positions.get(stored.last_message_id or "", -1) > positions.get(
        presented.last_message_id or "", -1
    ):
        last_message_id = stored.last_message_id
    seen_outcome_ids = list(dict.fromkeys([*presented.seen_outcome_ids, *stored.seen_outcome_ids]))[
        -_MAX_OUTCOMES:
    ]
    current_actions = {
        action_id: _status(action)
        for action in _actions(state)
        if (action_id := _action_id(action))
    }
    action_statuses: dict[str, str] = {}
    for action_id in presented.action_statuses.keys() | stored.action_statuses.keys():
        presented_status = presented.action_statuses.get(action_id)
        stored_status = stored.action_statuses.get(action_id)
        current_status = current_actions.get(action_id)
        if stored_status == presented_status or current_status == stored_status:
            status = stored_status
        elif current_status == presented_status:
            status = presented_status
        else:
            status = stored_status or presented_status
        if status:
            action_statuses[action_id] = status
    merged = presented.model_copy(
        update={
            "last_message_id": last_message_id,
            "seen_outcome_ids": seen_outcome_ids,
            "action_statuses": dict(list(action_statuses.items())[-_MAX_ACTIONS:]),
        }
    )
    return _with_reviewed_time(merged, stored, reviewed_at=reviewed_at)


def _message_diff(
    messages: list[Any],
    stored: AttentionCursor,
) -> tuple[bool, int, list[Any]]:
    frontier = stored.last_message_id
    if not frontier:
        return False, len(messages), messages
    for index in range(len(messages) - 1, -1, -1):
        if _message_id(messages[index]) == frontier:
            new_messages = messages[index + 1 :]
            return False, len(new_messages), new_messages
    return True, 0, []


def _diff(state: Any, stored: AttentionCursor | None) -> AttentionDiff:
    if stored is None:
        return AttentionDiff(first_visit=True)

    messages = list(_state_value(state, "messages", []) or [])
    frontier_missing, message_count, new_messages = _message_diff(messages, stored)
    seen_outcomes = set(stored.seen_outcome_ids)
    current_outcomes = _outcomes(state)[-_MAX_OUTCOMES:]
    new_outcomes = [
        outcome
        for outcome in current_outcomes
        if (outcome_id := _outcome_id(outcome)) and outcome_id not in seen_outcomes
    ]
    unique_outcomes: dict[str, Any] = {}
    for outcome in new_outcomes:
        unique_outcomes[_outcome_id(outcome)] = outcome
    new_outcomes = list(unique_outcomes.values())
    failed_count = sum(_status(outcome) in _FAILURE_STATUSES for outcome in new_outcomes)

    transitions: list[tuple[Any, str]] = []
    current_actions = _actions(state)[-_MAX_ACTIONS:]
    for action in current_actions:
        action_id = _action_id(action)
        status = _status(action)
        if not action_id or not status:
            continue
        previous = stored.action_statuses.get(action_id)
        if previous != status:
            transitions.append((action, previous or ""))

    final_messages = [
        message
        for message in new_messages
        if _message_type(message) in {"ai", "assistant"}
        and not _get(message, "tool_calls")
        and _text(_get(message, "content"))
        and _message_id(message)
    ]
    message_highlights = [
        AttentionItem(
            source_id=_message_id(message),
            kind="message",
            status="final",
            text=_text(_get(message, "content")),
        )
        for message in final_messages
    ]
    failed_highlights = [
        _outcome_highlight(outcome)
        for outcome in new_outcomes
        if _status(outcome) in _FAILURE_STATUSES | _DEGRADED_STATUSES
    ]
    other_outcome_highlights = [
        _outcome_highlight(outcome)
        for outcome in new_outcomes
        if _status(outcome) in _SUCCESS_STATUSES
    ]
    action_highlights = [
        AttentionItem(
            source_id=_action_id(action),
            kind="branch_action",
            status=_status(action),
            previous_status=previous or None,
            text=_text(f"Branch action: {previous or 'new'} -> {_status(action)}"),
        )
        for action, previous in transitions
    ]
    highlights = (
        action_highlights + failed_highlights + other_outcome_highlights + message_highlights
    )[:_MAX_HIGHLIGHTS]
    return AttentionDiff(
        first_visit=False,
        frontier_missing=frontier_missing,
        new_message_count=message_count,
        new_outcome_count=len(new_outcomes),
        new_failed_outcome_count=failed_count,
        action_transition_count=len(transitions),
        highlights=highlights,
    )


def _outcome_highlight(outcome: Any) -> AttentionItem:
    status = _status(outcome)
    tool_name = _text(
        _get(outcome, "tool_name") or _get(outcome, "tool") or _get(outcome, "name"),
        120,
    )
    label = f"Tool {tool_name}" if tool_name else "Tool outcome"
    return AttentionItem(
        source_id=_outcome_id(outcome),
        kind="tool_outcome",
        status=status,
        text=_text(f"{label}: {status or 'unknown'}"),
    )


def _goal(state: Any) -> str:
    for key in ("active_goal", "task_brief"):
        goal = _text(_state_value(state, key), 1200)
        if goal:
            return goal
    branch_meta = _state_value(state, "branch_meta", {})
    fork_brief = _get(branch_meta, "fork_brief", {})
    goal = _text(_get(fork_brief, "goal"), 1200)
    if goal:
        return goal
    # State payloads can be truncated to recent messages. Prefer the durable
    # goal/brief above; the earliest retained user message is only a fallback.
    for message in list(_state_value(state, "messages", []) or []):
        if _message_type(message) in {"human", "user"}:
            return _text(_get(message, "content"), 1200)
    return ""


def _record_text(record: Any, fallback: str) -> str:
    return (
        _text(
            _get(record, "title")
            or _get(record, "summary")
            or _get(record, "handoff_message")
            or _get(record, "question")
            or _get(record, "suggested_branch_name"),
            800,
        )
        or fallback
    )


def _resume_and_policy(thread_id: str, state: Any) -> tuple[ResumePacket, AttentionPolicy]:
    decisions: list[AttentionItem] = []
    open_items: list[AttentionItem] = []
    evidence = [AttentionEvidence(source_id=thread_id, kind="thread", thread_id=thread_id)]
    ask_reasons: dict[str, list[str]] = {}

    ask_items: list[AttentionItem] = []
    failed_action_ids: list[str] = []
    for action in _actions(state):
        status = _status(action)
        action_id = _action_id(action) or "branch-action"
        if status in _FAILURE_STATUSES:
            item = AttentionItem(
                source_id=action_id,
                kind="branch_action",
                status=status,
                text=_record_text(action, "Branch action failed"),
            )
            open_items.append(item)
            evidence.append(
                AttentionEvidence(
                    source_id=action_id,
                    kind="branch_action",
                    thread_id=thread_id,
                    action_id=action_id,
                )
            )
            failed_action_ids.append(action_id)
            continue
        if status not in _PENDING_STATUSES:
            continue
        if _get(action, "recommendation_user_visible") is False:
            continue
        action_kind = _text(
            _get(action, "kind") or _get(action, "action_type") or _get(action, "type"),
            120,
        )
        item = AttentionItem(
            source_id=action_id,
            kind="branch_action",
            status=status,
            text=_record_text(action, action_kind or "Branch action requires review"),
        )
        open_items.append(item)
        ask_items.append(item)
        evidence.append(
            AttentionEvidence(
                source_id=action_id,
                kind="branch_action",
                thread_id=thread_id,
                action_id=action_id,
            )
        )
        ask_reasons.setdefault("branch_action_pending", []).append(action_id)

    for index, interrupt in enumerate(_interrupts(state)):
        interrupt_id = (
            _identifier(interrupt, "interrupt_id", "tool_call_id") or f"interrupt-{index}"
        )
        item = AttentionItem(
            source_id=interrupt_id,
            kind="interrupt",
            status="pending",
            text="Interrupt requires review",
        )
        open_items.append(item)
        ask_items.append(item)
        evidence.append(
            AttentionEvidence(
                source_id=interrupt_id,
                kind="interrupt",
                thread_id=thread_id,
            )
        )
        ask_reasons.setdefault("interrupt_pending", []).append(interrupt_id)

    for kind, source_id, status, record in _merge_records(state, thread_id):
        if status in _DECISION_STATUSES:
            decisions.append(
                AttentionItem(
                    source_id=source_id,
                    kind=kind,
                    status=status,
                    text=_record_text(record, f"{kind}: {status}"),
                )
            )
        elif status in _PENDING_STATUSES:
            item = AttentionItem(
                source_id=source_id,
                kind=kind,
                status=status,
                text=_record_text(record, f"{kind} requires review"),
            )
            open_items.append(item)
            ask_items.append(item)
            ask_reasons.setdefault(f"{kind}_pending", []).append(source_id)
        else:
            continue
        evidence.append(AttentionEvidence(source_id=source_id, kind=kind, thread_id=thread_id))

    decision_summary = _state_value(state, "branch_decision_summary", {})
    handoff_decision = _get(decision_summary, "latest_decision")
    handoff_metadata = _get(handoff_decision, "metadata", {})
    handoff_status = str(_get(handoff_metadata, "handoff_run_status", "") or "").lower()
    handoff_error = _text(_get(handoff_decision, "error"), 240)
    if handoff_decision and (
        handoff_status in _FAILURE_STATUSES
        or (handoff_error and handoff_status not in _SUCCESS_STATUSES)
    ):
        run_id = str(_get(handoff_metadata, "handoff_run_id") or "")
        source_id = run_id or _identifier(handoff_decision, "decision_id") or f"{thread_id}:handoff"
        status = handoff_status or "error"
        open_items.append(
            AttentionItem(
                source_id=source_id,
                kind="branch_handoff",
                status=status,
                text=_record_text(handoff_decision, handoff_error or "Branch handoff failed"),
            )
        )
        evidence.append(
            AttentionEvidence(
                source_id=source_id,
                kind="branch_handoff",
                thread_id=thread_id,
                run_id=run_id or None,
            )
        )

    notify_reasons: dict[str, list[str]] = {}
    if handoff_decision and (
        handoff_status in _FAILURE_STATUSES
        or (handoff_error and handoff_status not in _SUCCESS_STATUSES)
    ):
        notify_reasons["branch_handoff_failed"] = [source_id]
    if failed_action_ids:
        notify_reasons["branch_action_failed"] = failed_action_ids
    current: Any = None
    source_id = ""
    task = _state_value(state, "task_outcome")
    if task:
        current = task
        source_id = f"{thread_id}:task-outcome"
    elif _outcomes(state):
        current = _outcomes(state)[-1]
        source_id = _outcome_id(current) or f"{thread_id}:tool-outcome"
    if current is not None:
        status = _status(current)
        reason_code = ""
        if status in _FAILURE_STATUSES:
            reason_code = "task_outcome_failed"
        elif status in _DEGRADED_STATUSES or _get(current, "degraded_reason"):
            reason_code = "task_outcome_degraded"
        elif status not in _SUCCESS_STATUSES | _ACTIVE_STATUSES | {"answered"}:
            status = status or "unknown"
            reason_code = "task_outcome_unknown"
        if reason_code:
            open_items.append(
                AttentionItem(
                    source_id=source_id,
                    kind="task_outcome",
                    status=status,
                    text=f"Current task outcome: {status}",
                )
            )
            evidence.append(
                AttentionEvidence(
                    source_id=source_id,
                    kind="task_outcome",
                    thread_id=thread_id,
                )
            )
            notify_reasons[reason_code] = [source_id]

    reasons = [
        AttentionReason(code=code, source_ids=source_ids[:16])
        for code, source_ids in [*ask_reasons.items(), *notify_reasons.items()]
    ]
    level = "ask" if ask_reasons else "notify" if notify_reasons else "quiet"
    resume = ResumePacket(
        goal=_goal(state),
        decisions=decisions[:_MAX_DECISIONS],
        open_items=open_items[:_MAX_OPEN_ITEMS],
        next_action=(ask_items or open_items)[0] if open_items else None,
        evidence=evidence[:_MAX_EVIDENCE],
    )
    return resume, AttentionPolicy(level=level, reasons=reasons[:32])


def build_attention_snapshot(
    *,
    thread_id: str,
    state: Any,
    stored_cursor: AttentionCursor | None,
) -> AttentionSnapshot:
    current = _with_reviewed_time(_current_cursor(state), stored_cursor, reviewed_at=None)
    resume, policy = _resume_and_policy(thread_id, state)
    return AttentionSnapshot(
        thread_id=thread_id,
        policy=policy,
        resume=resume,
        diff=_diff(state, stored_cursor),
        current_cursor=current,
    )


class AttentionService:
    _REVIEW_LOCK = Lock()

    def __init__(self, store: Any):
        self.store = store

    @staticmethod
    def _namespace(tenant_id: str, user_id: str, thread_id: str) -> tuple[str, ...]:
        return attention_cursor_namespace(tenant_id, user_id, thread_id)

    def _load(self, tenant_id: str, user_id: str, thread_id: str) -> AttentionCursor | None:
        item = self.store.get(self._namespace(tenant_id, user_id, thread_id), _CURSOR_KEY)
        if item is None:
            return None
        value = _get(item, "value", item)
        try:
            return AttentionCursor.model_validate(value)
        except (ValidationError, TypeError, ValueError):
            return None

    def get_snapshot(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        state: Any,
    ) -> AttentionSnapshot:
        stored = self._load(tenant_id, user_id, thread_id)
        return build_attention_snapshot(thread_id=thread_id, state=state, stored_cursor=stored)

    def review(
        self,
        *,
        tenant_id: str,
        user_id: str,
        thread_id: str,
        state: Any,
        presented_cursor: AttentionCursor,
    ) -> AttentionCursor:
        message_ids = {
            message_id
            for message in list(_state_value(state, "messages", []) or [])
            if (message_id := _message_id(message))
        }
        if presented_cursor.last_message_id and presented_cursor.last_message_id not in message_ids:
            raise AttentionReviewConflictError("The reviewed message frontier no longer exists.")
        outcome_ids = set(filter(None, (_outcome_id(item) for item in _outcomes(state))))
        if set(presented_cursor.seen_outcome_ids) - outcome_ids:
            raise AttentionReviewConflictError("Some reviewed tool outcomes no longer exist.")
        action_ids = set(filter(None, (_action_id(item) for item in _actions(state))))
        if set(presented_cursor.action_statuses) - action_ids:
            raise AttentionReviewConflictError("Some reviewed branch actions no longer exist.")

        with self._REVIEW_LOCK:
            stored = self._load(tenant_id, user_id, thread_id)
            reviewed_at = datetime.now(UTC).isoformat()
            current = _merge_review_cursor(
                state,
                presented_cursor,
                stored,
                reviewed_at=reviewed_at,
            )
            if stored is not None and _same_frontier(current, stored):
                return stored
            self.store.put(
                self._namespace(tenant_id, user_id, thread_id),
                _CURSOR_KEY,
                current.model_dump(mode="json"),
            )
            return current


__all__ = ["AttentionReviewConflictError", "AttentionService", "build_attention_snapshot"]
