from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from focus_agent.services import attention as attention_service
from focus_agent.services.attention import build_attention_snapshot

ATTENTION_EVALUATION_LIMITATION = (
    "Review units are deterministic proxies based on canonical record counts, not "
    "measurements of human attention, reading time, or task quality. A suite fails "
    "when required actionable/failure sources lose policy or evidence visibility."
)

_PENDING = {"awaiting_approval", "awaiting_review", "pending", "proposed", "requested"}
_FAILURE = {"blocked", "error", "errored", "failed", "failure", "timed_out", "timeout"}
_DEGRADED = {"degraded", "degraded_answer", "partial"}


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _state_value(state: Any, key: str, default: Any = None) -> Any:
    return attention_service._state_value(state, key, default)


def _status(value: Any) -> str:
    return attention_service._status(value)


def _identifier(value: Any, *names: str) -> str:
    return attention_service._identifier(value, *names)


def _records(value: Any) -> list[Any]:
    return attention_service._records(value)


def _required_sources(state: Any, thread_id: str) -> dict[tuple[str, str], str]:
    required: dict[tuple[str, str], str] = {}
    for action in _records(_state_value(state, "branch_actions", [])):
        status = _status(action)
        if status in _FAILURE or (
            status in _PENDING and _get(action, "recommendation_user_visible") is not False
        ):
            source_id = _identifier(action, "action_id") or "branch-action"
            level = "notify" if status in _FAILURE else "ask"
            required[("branch_action", source_id)] = level
    for index, interrupt in enumerate(attention_service._interrupts(state)):
        required[
            (
                "interrupt",
                _identifier(interrupt, "interrupt_id", "tool_call_id") or f"interrupt-{index}",
            )
        ] = "ask"

    for kind, source_id, status, _record in attention_service._merge_records(state, thread_id):
        if status in _PENDING:
            required[(kind, source_id)] = "ask"

    decision_summary = _state_value(state, "branch_decision_summary", {})
    handoff_decision = _get(decision_summary, "latest_decision")
    handoff_metadata = _get(handoff_decision, "metadata", {})
    handoff_status = str(_get(handoff_metadata, "handoff_run_status", "") or "").lower()
    handoff_error = str(_get(handoff_decision, "error", "") or "")
    if handoff_decision and (
        handoff_status in _FAILURE
        or (
            handoff_error
            and handoff_status
            not in {"complete", "completed", "done", "ok", "recovered", "succeeded", "success"}
        )
    ):
        run_id = str(_get(handoff_metadata, "handoff_run_id") or "")
        source_id = run_id or _identifier(handoff_decision, "decision_id") or f"{thread_id}:handoff"
        required[("branch_handoff", source_id)] = "notify"

    task = _state_value(state, "task_outcome")
    outcomes = _records(_state_value(state, "tool_outcomes", []))
    current = task or (outcomes[-1] if outcomes else None)
    if current is not None:
        status = _status(current)
        if (
            status in _FAILURE | _DEGRADED
            or _get(current, "degraded_reason")
            or status
            not in {
                "answered",
                "complete",
                "completed",
                "done",
                "ok",
                "recovered",
                "succeeded",
                "success",
                "in_progress",
                "pending",
                "queued",
                "running",
                "started",
            }
        ):
            required[
                (
                    "task_outcome",
                    f"{thread_id}:task-outcome"
                    if task
                    else _identifier(current, "outcome_id", "tool_call_id")
                    or f"{thread_id}:tool-outcome",
                )
            ] = "notify"
    return required


def _baseline_units(state: Any) -> int:
    return (
        len(_records(_state_value(state, "messages", [])))
        + len(_records(_state_value(state, "tool_outcomes", [])))
        + len(_records(_state_value(state, "branch_actions", [])))
        + len(attention_service._interrupts(state))
        + len(attention_service._merge_records(state, str(_state_value(state, "thread_id", ""))))
    )


def _attention_units(snapshot: Any) -> int:
    resume = snapshot.resume
    units = int(bool(resume.goal))
    units += len(resume.decisions) + len(resume.open_items) + len(snapshot.diff.highlights)
    if resume.next_action and not any(
        item.kind == resume.next_action.kind and item.source_id == resume.next_action.source_id
        for item in resume.open_items
    ):
        units += 1
    evidence = {
        (
            item.kind,
            item.source_id,
            item.thread_id,
            item.action_id,
            item.run_id,
        )
        for item in resume.evidence
    }
    return units + len(evidence)


def _policy_reason_kind(code: str) -> str:
    for prefix, kind in (
        ("branch_action_", "branch_action"),
        ("branch_handoff_", "branch_handoff"),
        ("interrupt_", "interrupt"),
        ("proposal_", "proposal"),
        ("merge_decision_", "merge_decision"),
        ("task_outcome_", "task_outcome"),
    ):
        if code.startswith(prefix):
            return kind
    return ""


def _ratio(baseline: int, attention: int) -> float | None:
    return (baseline - attention) / baseline if baseline else None


def evaluate_attention_workbench(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id") or f"case-{len(results) + 1}")
        state = case["state"]
        thread_id = str(case.get("thread_id") or _state_value(state, "thread_id") or case_id)
        snapshot = build_attention_snapshot(
            thread_id=thread_id,
            state=state,
            stored_cursor=case.get("stored_cursor"),
        )
        baseline = _baseline_units(state)
        attention = _attention_units(snapshot)
        required = _required_sources(state, thread_id)
        required_level = "ask" if "ask" in required.values() else "notify" if required else "quiet"
        required_keys = required.keys()
        recalled = {(item.kind, item.source_id) for item in snapshot.resume.open_items}
        if snapshot.resume.next_action:
            recalled.add((snapshot.resume.next_action.kind, snapshot.resume.next_action.source_id))
        evidence = {(item.kind, item.source_id) for item in snapshot.resume.evidence}
        policy_keys = {
            (kind, source_id)
            for reason in snapshot.policy.reasons
            if (kind := _policy_reason_kind(reason.code))
            for source_id in reason.source_ids
        }
        missing = required_keys - recalled
        uncovered = required_keys - evidence
        missing_policy = required_keys - policy_keys
        expected_missing = case.get("expect_frontier_missing")
        frontier_mismatch = (
            expected_missing is not None and snapshot.diff.frontier_missing is not expected_missing
        )
        unexpected_alert = not required and snapshot.policy.level != "quiet"
        missing_required_alert = bool(required) and snapshot.policy.level == "quiet"
        passed = (
            not missing
            and not uncovered
            and not missing_policy
            and not missing_required_alert
            and snapshot.policy.level == required_level
            and not frontier_mismatch
            and not unexpected_alert
        )
        results.append(
            {
                "id": case_id,
                "baseline_units": baseline,
                "attention_units": attention,
                "reduction_ratio": _ratio(baseline, attention),
                "policy": snapshot.policy.level,
                "required_level": required_level,
                "required_source_count": len(required),
                "recalled_source_count": len(required_keys & recalled),
                "evidence_covered_source_count": len(required_keys & evidence),
                "missing_source_ids": [
                    f"{kind}:{source_id}" for kind, source_id in sorted(missing)
                ],
                "uncovered_source_ids": [
                    f"{kind}:{source_id}" for kind, source_id in sorted(uncovered)
                ],
                "missing_policy_source_ids": [
                    f"{kind}:{source_id}" for kind, source_id in sorted(missing_policy)
                ],
                "frontier_missing": snapshot.diff.frontier_missing,
                "unexpected_alert": unexpected_alert,
                "missing_required_alert": missing_required_alert,
                "passed": passed,
            }
        )

    baseline_total = sum(item["baseline_units"] for item in results)
    attention_total = sum(item["attention_units"] for item in results)
    required_total = sum(item["required_source_count"] for item in results)
    return {
        "cases": results,
        "summary": {
            "case_count": len(results),
            "baseline_units": baseline_total,
            "attention_units": attention_total,
            "reduction_ratio": _ratio(baseline_total, attention_total),
            "required_source_count": required_total,
            "recalled_source_count": sum(item["recalled_source_count"] for item in results),
            "evidence_covered_source_count": sum(
                item["evidence_covered_source_count"] for item in results
            ),
            "passed": bool(results) and all(item["passed"] for item in results),
        },
        "limitation": ATTENTION_EVALUATION_LIMITATION,
    }


__all__ = ["ATTENTION_EVALUATION_LIMITATION", "evaluate_attention_workbench"]
