"""Trajectory export helpers for eval replay and promotion flows."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .schema import EvalCase, EvalResult


_DEFAULT_CASE_ID_PREFIX = "traj"
_SUCCESS_STATUSES = {"succeeded", "success", "passed"}


@dataclass(slots=True)
class ConvertedTrajectoryCase:
    case: EvalCase
    source: dict[str, Any]


def load_trajectory_records(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        return []

    if source.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        payload = json.loads(text)
        records = _extract_records(payload)

    filtered = [record for record in records if isinstance(record, dict) and _looks_like_trajectory_record(record)]
    if not filtered:
        raise ValueError(f"unsupported trajectory payload: {source}")
    return filtered


def convert_trajectory_records(
    records: Iterable[dict[str, Any]],
    *,
    case_id_prefix: str = _DEFAULT_CASE_ID_PREFIX,
    copy_tool_trajectory: bool = False,
    copy_answer_substring: bool = False,
    answer_substring_chars: int = 160,
) -> list[ConvertedTrajectoryCase]:
    converted: list[ConvertedTrajectoryCase] = []
    for record in records:
        converted.append(
            ConvertedTrajectoryCase(
                case=trajectory_record_to_eval_case(
                    record,
                    case_id_prefix=case_id_prefix,
                    copy_tool_trajectory=copy_tool_trajectory,
                    copy_answer_substring=copy_answer_substring,
                    answer_substring_chars=answer_substring_chars,
                ),
                source=dict(record),
            )
        )
    return converted


def trajectory_record_to_eval_case(
    record: dict[str, Any],
    *,
    case_id_prefix: str = _DEFAULT_CASE_ID_PREFIX,
    copy_tool_trajectory: bool = False,
    copy_answer_substring: bool = False,
    answer_substring_chars: int = 160,
) -> EvalCase:
    user_message = str(record.get("user_message") or "").strip()
    if not user_message:
        raise ValueError("trajectory record is missing user_message")

    source_id = str(record.get("id") or record.get("turn_id") or "").strip()
    turn_index = record.get("turn_index")
    scene = str(record.get("scene") or "long_dialog_research")
    tool_names = _tool_names(record)
    source_answer = str(record.get("answer") or "").strip()
    expected: dict[str, Any] = {}
    if copy_tool_trajectory and tool_names:
        expected["optimal_tool_sequence"] = tool_names
        expected["max_tool_calls"] = len(tool_names)
    if copy_answer_substring:
        anchor = _answer_anchor(source_answer, max_chars=answer_substring_chars)
        if anchor:
            expected["answer_contains_any"] = [anchor]

    source_status = str(record.get("status") or "unknown").strip() or "unknown"
    tags = ["trajectory_replay", f"status:{_slug(source_status)}"]
    branch_role = str(record.get("branch_role") or "").strip()
    if branch_role:
        tags.append(f"branch_role:{_slug(branch_role)}")
    kind = str(record.get("kind") or "").strip()
    if kind:
        tags.append(f"kind:{_slug(kind)}")

    case_id_source = source_id or f"thread-{record.get('thread_id') or 'unknown'}-turn-{turn_index or 'na'}"
    case_id = _prefixed_case_id(case_id_source, prefix=case_id_prefix)
    return EvalCase(
        id=case_id,
        input={"user_message": user_message},
        expected=expected,
        tags=tags,
        scene=scene,
        judge={"rule": bool(expected), "llm": {"enabled": False}},
        origin={
            "type": "trajectory",
            "trajectory_id": source_id or None,
            "thread_id": record.get("thread_id"),
            "root_thread_id": record.get("root_thread_id"),
            "parent_thread_id": record.get("parent_thread_id"),
            "branch_id": record.get("branch_id"),
            "branch_role": record.get("branch_role"),
            "turn_index": turn_index,
            "status": source_status,
            "selected_model": record.get("selected_model"),
            "selected_thinking_mode": record.get("selected_thinking_mode"),
            "task_brief": record.get("task_brief"),
            "source_answer": record.get("answer"),
            "source_error": record.get("error"),
            "source_metrics": dict(record.get("metrics") or {}),
            "source_tools": tool_names,
            "source_trajectory": _summarize_steps(record.get("trajectory")),
        },
    )


def write_eval_cases_jsonl(path: str | Path, cases: Iterable[EvalCase]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_case_to_dict(case), ensure_ascii=False) for case in cases]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def build_replay_comparison(
    source_record: dict[str, Any],
    replay_result: EvalResult,
) -> dict[str, Any]:
    source_tools = _tool_names(source_record)
    replay_tools = [step.tool for step in replay_result.trajectory]
    source_metrics = dict(source_record.get("metrics") or {})
    return {
        "case_id": replay_result.case_id,
        "trajectory_id": source_record.get("id"),
        "source_status": source_record.get("status"),
        "source_failed": trajectory_record_failed(source_record),
        "replay_passed": replay_result.passed,
        "replay_error": replay_result.error,
        "source_tools": source_tools,
        "replay_tools": replay_tools,
        "tool_path_changed": source_tools != replay_tools,
        "source_tool_calls": len(source_tools),
        "replay_tool_calls": len(replay_tools),
        "source_latency_ms": float(source_metrics.get("latency_ms") or 0.0),
        "replay_latency_ms": float(replay_result.metrics.get("latency_ms") or 0.0),
        "source_fallback_uses": int(source_metrics.get("fallback_uses") or 0),
        "replay_fallback_uses": int(replay_result.metrics.get("fallback_uses") or 0),
        "source_cache_hits": int(source_metrics.get("cache_hits") or 0),
        "replay_cache_hits": int(replay_result.metrics.get("cache_hits") or 0),
        "source_answer_preview": str(source_record.get("answer") or "")[:160],
        "replay_answer_preview": replay_result.answer[:160],
    }


def format_replay_comparison(comparison: dict[str, Any]) -> str:
    return "\n".join(
        [
            (
                f"case_id={comparison.get('case_id')} trajectory_id={comparison.get('trajectory_id')} "
                f"source_failed={comparison.get('source_failed')} replay_passed={comparison.get('replay_passed')}"
            ),
            (
                f"tools_before={','.join(comparison.get('source_tools') or []) or '-'} "
                f"tools_after={','.join(comparison.get('replay_tools') or []) or '-'} "
                f"changed={comparison.get('tool_path_changed')}"
            ),
            (
                f"latency_ms_before={round(float(comparison.get('source_latency_ms') or 0.0), 1)} "
                f"latency_ms_after={round(float(comparison.get('replay_latency_ms') or 0.0), 1)} "
                f"fallback_before={comparison.get('source_fallback_uses')} "
                f"fallback_after={comparison.get('replay_fallback_uses')}"
            ),
        ]
    )


def trajectory_record_failed(record: dict[str, Any]) -> bool:
    status = str(record.get("status") or "").strip().lower()
    return bool(record.get("error")) or (bool(status) and status not in _SUCCESS_STATUSES)


def _case_to_dict(case: EvalCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "input": case.input,
        "expected": case.expected,
        "tags": case.tags,
        "scene": case.scene,
        "skill_hints": case.skill_hints,
        "setup": case.setup,
        "judge": case.judge,
        "origin": case.origin,
    }


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in ("records", "turns", "items", "trajectories", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
        if _looks_like_trajectory_record(payload):
            return [payload]
    raise ValueError("unsupported trajectory payload")


def _looks_like_trajectory_record(record: dict[str, Any]) -> bool:
    return bool(
        record.get("trajectory") is not None
        or record.get("user_message")
        or {"thread_id", "root_thread_id", "scene"} <= set(record)
    )


def _prefixed_case_id(source_id: str, *, prefix: str) -> str:
    slug = _slug(source_id) or "trajectory"
    clean_prefix = _slug(prefix)
    return f"{clean_prefix}-{slug}" if clean_prefix else slug


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "")).strip("-").lower()


def _tool_names(record: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for step in list(record.get("trajectory") or []):
        if isinstance(step, dict):
            tool = str(step.get("tool") or "").strip()
            if tool:
                names.append(tool)
    return names


def _summarize_steps(raw_steps: Any) -> list[dict[str, Any]]:
    summarized: list[dict[str, Any]] = []
    for step in list(raw_steps or []):
        if not isinstance(step, dict):
            continue
        summarized.append(
            {
                "tool": step.get("tool"),
                "args": dict(step.get("args") or {}),
                "cache_hit": bool(step.get("cache_hit")),
                "fallback_used": bool(step.get("fallback_used")),
                "fallback_group": step.get("fallback_group"),
                "parallel_batch_size": step.get("parallel_batch_size"),
                "duration_ms": float(step.get("duration_ms") or 0.0),
                "error": step.get("error"),
            }
        )
    return summarized


def _answer_anchor(answer: str, *, max_chars: int) -> str | None:
    text = re.sub(r"\s+", " ", str(answer or "")).strip()
    if not text:
        return None
    return text[: max(int(max_chars), 0)].strip() or None
