#!/usr/bin/env python3
"""Build the nightly feedback regression report."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_REPORT_JSON = Path("reports/nightly/feedback-regression.json")
DEFAULT_FEEDBACK_EVENTS_JSONL = Path("reports/nightly/feedback-events.jsonl")
DEFAULT_MERGE_REVIEWS_JSON = Path("reports/nightly/agent-team-merge-reviews.json")
DEFAULT_SKILL_SELECTIONS_JSON = Path("reports/nightly/skill-selection-events.json")
DEFAULT_CONTEXT_EVIDENCE_JSON = Path("reports/nightly/context-memory-evidence.json")
DEFAULT_PRODUCTIVITY_CAPTURES_JSON = Path("reports/nightly/productivity-captures.json")
DEFAULT_TRAJECTORY_REPORTS = (
    Path("reports/nightly/eval-trajectory-failures.json"),
    Path("reports/nightly/trajectory-replay.json"),
)
DEFAULT_SKILL_LOW_CONFIDENCE_THRESHOLD = 0.62
DEFAULT_CONTEXT_HIGH_DRIFT_THRESHOLD = 0.30
DEFAULT_TOP_FAILURE_LIMIT = 10


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve(path: str | Path) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = REPO_ROOT / target
    return target


def _read_json(path: str | Path) -> Any | None:
    target = _resolve(path)
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def _read_jsonl(path: str | Path) -> list[Any] | None:
    target = _resolve(path)
    if not target.exists():
        return None
    records: list[Any] = []
    for line_number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{target}:{line_number} contains invalid JSONL") from exc
    return records


def _items_from_payload(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in (
        "items",
        "events",
        "records",
        "results",
        "reviews",
        "selections",
        "evidence",
        "captures",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, Mapping)]
    return [dict(payload)]


def _artifact_records(
    path: str | Path, *, kind: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target = _resolve(path)
    payload = _read_jsonl(target) if target.suffix == ".jsonl" else _read_json(target)
    if payload is None:
        return {"kind": kind, "path": str(target), "status": "missing", "record_count": 0}, []
    records = _items_from_payload(payload)
    return {
        "kind": kind,
        "path": str(target),
        "status": "available",
        "record_count": len(records),
    }, records


def _first_text(record: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            return value.strip()
        return str(value)
    return ""


def _nested_mapping(record: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = record.get(key)
    return value if isinstance(value, Mapping) else {}


def _is_negative_feedback(record: Mapping[str, Any]) -> bool:
    text = " ".join(
        _first_text(record, keys)
        for keys in (
            ("event_type", "kind", "type"),
            ("feedback", "rating", "sentiment", "outcome", "status"),
        )
    ).lower()
    if any(
        marker in text for marker in ("negative", "thumbs_down", "downvote", "bad", "incorrect")
    ):
        return True
    rating = record.get("rating") or record.get("score")
    try:
        return rating is not None and float(rating) <= 2
    except (TypeError, ValueError):
        return False


def _merge_review_status(record: Mapping[str, Any]) -> str:
    return _first_text(record, ("status", "outcome", "action", "event_type", "kind")).lower()


def _is_merge_review(record: Mapping[str, Any]) -> bool:
    source_kind = _first_text(record, ("source_kind", "kind", "event_type", "type")).lower()
    return "merge_review" in source_kind or "agent_team_review" in source_kind


def _merge_review_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    applied = 0
    conflicts = 0
    rejected = 0
    errors = 0
    for record in records:
        status = _merge_review_status(record)
        if "conflict" in status:
            conflicts += 1
        elif "applied" in status or "apply_success" in status:
            applied += 1
        elif "reject" in status:
            rejected += 1
        elif "error" in status or "failed" in status:
            errors += 1
    attempts = applied + conflicts + errors
    return {
        "record_count": len(records),
        "apply_success_count": applied,
        "conflict_count": conflicts,
        "rejected_count": rejected,
        "error_count": errors,
        "apply_attempt_count": attempts,
        "apply_success_rate": round(applied / attempts, 4) if attempts else None,
    }


def _skill_confidence(record: Mapping[str, Any]) -> float | None:
    value = record.get("confidence")
    if value is None:
        summary = _nested_mapping(record, "selection")
        value = summary.get("confidence")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _has_user_override(record: Mapping[str, Any]) -> bool:
    override = record.get("user_override")
    if isinstance(override, Mapping):
        return bool(override)
    if isinstance(override, bool):
        return override
    text = _first_text(record, ("override", "feedback", "event_type", "kind")).lower()
    return "override" in text or "removed" in text or "pinned" in text or "disabled" in text


def _skill_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    low_confidence_threshold: float,
) -> dict[str, Any]:
    low_confidence = 0
    override = 0
    confidence_values: list[float] = []
    for record in records:
        confidence = _skill_confidence(record)
        if confidence is not None:
            confidence_values.append(confidence)
            if confidence < low_confidence_threshold:
                low_confidence += 1
        if _has_user_override(record):
            override += 1
    return {
        "record_count": len(records),
        "low_confidence_threshold": low_confidence_threshold,
        "low_confidence_count": low_confidence,
        "override_count": override,
        "override_rate": round(override / len(records), 4) if records else None,
        "min_confidence": min(confidence_values) if confidence_values else None,
        "avg_confidence": round(sum(confidence_values) / len(confidence_values), 4)
        if confidence_values
        else None,
    }


def _context_drift_report(record: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("drift_report", "context_compaction_drift_report"):
        value = record.get(key)
        if isinstance(value, Mapping):
            return value
    evidence = _nested_mapping(record, "evidence")
    for key in ("drift_report", "context_compaction_drift_report"):
        value = evidence.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _is_high_drift(record: Mapping[str, Any], *, high_drift_threshold: float) -> bool:
    risk_text = " ".join(
        str(item).lower()
        for item in (
            record.get("drift_risk"),
            record.get("risk"),
            *_listish(record.get("risk_flags")),
        )
        if item is not None
    )
    if "high" in risk_text or "critical" in risk_text:
        return True
    report = _context_drift_report(record)
    drift_risk = str(report.get("drift_risk") or "").lower()
    if drift_risk in {"high", "critical"}:
        return True
    try:
        return (
            float(report.get("overall_drift") or record.get("overall_drift") or 0.0)
            >= high_drift_threshold
        )
    except (TypeError, ValueError):
        return False


def _listish(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _context_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    high_drift_threshold: float,
) -> dict[str, Any]:
    high_drift = [
        record
        for record in records
        if _is_high_drift(record, high_drift_threshold=high_drift_threshold)
    ]
    return {
        "record_count": len(records),
        "high_drift_threshold": high_drift_threshold,
        "high_drift_count": len(high_drift),
    }


def _is_productivity_capture(record: Mapping[str, Any]) -> bool:
    text = " ".join(
        _first_text(record, keys)
        for keys in (
            ("source_kind", "captured_from", "kind", "event_type", "type"),
            ("target_kind", "entity_type"),
        )
    ).lower()
    return "productivity" in text or "capture" in text or "note" in text or "task" in text


def _productivity_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    note_count = 0
    task_count = 0
    for record in records:
        text = " ".join(
            _first_text(record, keys)
            for keys in (
                ("target_kind", "entity_type", "kind", "event_type", "source_kind"),
                ("note_id", "task_id"),
            )
        ).lower()
        if "note" in text:
            note_count += 1
        if "task" in text:
            task_count += 1
    return {
        "record_count": len(records),
        "capture_count": len(records),
        "note_capture_count": note_count,
        "task_capture_count": task_count,
    }


def _trajectory_failures_from_payload(
    payload: Any,
    *,
    path: Path,
    limit: int,
) -> list[dict[str, Any]]:
    if payload is None:
        return []
    records = _items_from_payload(payload)
    failures: list[dict[str, Any]] = []
    for record in records:
        passed = record.get("passed")
        status = str(record.get("status") or "").lower()
        failed = passed is False or status in {"failed", "error"} or bool(record.get("error"))
        if not failed:
            continue
        failures.append(
            {
                "case_id": str(record.get("case_id") or record.get("id") or "unknown"),
                "path": str(path),
                "status": status or ("failed" if passed is False else "error"),
                "error": record.get("error") or record.get("failure") or record.get("reason"),
            }
        )
        if len(failures) >= limit:
            break
    return failures


def _trajectory_summary(paths: Sequence[str | Path], *, limit: int) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for path in paths:
        target = _resolve(path)
        payload = _read_json(target)
        if payload is None:
            artifacts.append(
                {"kind": "trajectory_report", "path": str(target), "status": "missing", "failed": 0}
            )
            continue
        current_failures = _trajectory_failures_from_payload(
            payload, path=target, limit=max(limit - len(failures), 0)
        )
        failures.extend(current_failures)
        artifacts.append(
            {
                "kind": "trajectory_report",
                "path": str(target),
                "status": "available",
                "failed": len(current_failures),
            }
        )
    return {
        "artifacts": artifacts,
        "top_failing_samples": failures[:limit],
        "top_failing_sample_count": len(failures[:limit]),
    }


def _collect_records(
    paths: Sequence[str | Path],
    *,
    kind: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    artifacts: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for path in paths:
        artifact, current = _artifact_records(path, kind=kind)
        artifacts.append(artifact)
        records.extend(current)
    return artifacts, records


def _default_existing(paths: Sequence[Path]) -> list[Path]:
    existing = [_resolve(path) for path in paths if _resolve(path).exists()]
    return existing or list(paths)


def build_feedback_report(
    *,
    feedback_events_json: Sequence[str | Path] = (),
    merge_review_json: Sequence[str | Path] = (),
    skill_selection_json: Sequence[str | Path] = (),
    context_evidence_json: Sequence[str | Path] = (),
    productivity_capture_json: Sequence[str | Path] = (),
    trajectory_report_json: Sequence[str | Path] = (),
    low_confidence_threshold: float = DEFAULT_SKILL_LOW_CONFIDENCE_THRESHOLD,
    high_drift_threshold: float = DEFAULT_CONTEXT_HIGH_DRIFT_THRESHOLD,
    top_failure_limit: int = DEFAULT_TOP_FAILURE_LIMIT,
) -> dict[str, Any]:
    feedback_paths = list(feedback_events_json) or _default_existing(
        [DEFAULT_FEEDBACK_EVENTS_JSONL]
    )
    merge_paths = list(merge_review_json) or _default_existing([DEFAULT_MERGE_REVIEWS_JSON])
    skill_paths = list(skill_selection_json) or _default_existing([DEFAULT_SKILL_SELECTIONS_JSON])
    context_paths = list(context_evidence_json) or _default_existing(
        [DEFAULT_CONTEXT_EVIDENCE_JSON]
    )
    productivity_paths = list(productivity_capture_json) or _default_existing(
        [DEFAULT_PRODUCTIVITY_CAPTURES_JSON]
    )
    trajectory_paths = list(trajectory_report_json) or _default_existing(
        list(DEFAULT_TRAJECTORY_REPORTS)
    )

    feedback_artifacts, feedback_records = _collect_records(feedback_paths, kind="feedback_event")
    merge_artifacts, merge_records = _collect_records(merge_paths, kind="merge_review")
    skill_artifacts, skill_records = _collect_records(skill_paths, kind="skill_selection")
    context_artifacts, context_records = _collect_records(
        context_paths, kind="context_memory_evidence"
    )
    productivity_artifacts, productivity_records = _collect_records(
        productivity_paths, kind="productivity_capture"
    )

    merge_records.extend(record for record in feedback_records if _is_merge_review(record))
    skill_records.extend(
        record
        for record in feedback_records
        if "skill" in _first_text(record, ("source_kind", "kind", "event_type", "type")).lower()
    )
    context_records.extend(
        record
        for record in feedback_records
        if "context" in _first_text(record, ("source_kind", "kind", "event_type", "type")).lower()
        or "memory" in _first_text(record, ("source_kind", "kind", "event_type", "type")).lower()
    )
    productivity_records.extend(
        record for record in feedback_records if _is_productivity_capture(record)
    )

    negative_feedback = [record for record in feedback_records if _is_negative_feedback(record)]
    merge_review = _merge_review_summary(merge_records)
    skill_selection = _skill_summary(
        skill_records, low_confidence_threshold=low_confidence_threshold
    )
    context_memory = _context_summary(context_records, high_drift_threshold=high_drift_threshold)
    productivity_capture = _productivity_summary(productivity_records)
    trajectory_failures = _trajectory_summary(trajectory_paths, limit=top_failure_limit)

    alert_count = (
        len(negative_feedback)
        + merge_review["conflict_count"]
        + merge_review["error_count"]
        + skill_selection["low_confidence_count"]
        + skill_selection["override_count"]
        + context_memory["high_drift_count"]
        + trajectory_failures["top_failing_sample_count"]
    )
    status = "alert" if alert_count else "passed"
    summary = {
        "status": status,
        "negative_feedback_count": len(negative_feedback),
        "merge_review_apply_success_count": merge_review["apply_success_count"],
        "merge_review_conflict_count": merge_review["conflict_count"],
        "merge_review_apply_success_rate": merge_review["apply_success_rate"],
        "skill_low_confidence_count": skill_selection["low_confidence_count"],
        "skill_override_count": skill_selection["override_count"],
        "skill_override_rate": skill_selection["override_rate"],
        "context_high_drift_count": context_memory["high_drift_count"],
        "notes_tasks_capture_count": productivity_capture["capture_count"],
        "top_failing_trajectory_sample_count": trajectory_failures["top_failing_sample_count"],
    }
    feedback_pipeline = {
        "status": status,
        "negative_feedback": {
            "count": len(negative_feedback),
            "sample_ids": [
                str(
                    record.get("event_id")
                    or record.get("id")
                    or record.get("source_id")
                    or "unknown"
                )
                for record in negative_feedback[:top_failure_limit]
            ],
        },
        "merge_review": merge_review,
        "skill_selection": skill_selection,
        "context_memory": context_memory,
        "productivity_capture": productivity_capture,
        "trajectory_failures": {
            "top_failing_samples": trajectory_failures["top_failing_samples"],
            "top_failing_sample_count": trajectory_failures["top_failing_sample_count"],
        },
    }
    return {
        "meta": {
            "suite": "feedback_regression",
            "generated_at": _now_iso(),
            "root": str(REPO_ROOT),
            "low_confidence_threshold": low_confidence_threshold,
            "high_drift_threshold": high_drift_threshold,
        },
        "artifacts": {
            "feedback_events": feedback_artifacts,
            "merge_reviews": merge_artifacts,
            "skill_selections": skill_artifacts,
            "context_evidence": context_artifacts,
            "productivity_captures": productivity_artifacts,
            "trajectory_reports": trajectory_failures["artifacts"],
        },
        "feedback_pipeline": feedback_pipeline,
        "summary": summary,
    }


def write_feedback_report(path: str | Path, **kwargs: Any) -> Path:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_feedback_report(**kwargs)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--feedback-events-json", action="append", default=[])
    parser.add_argument("--merge-review-json", action="append", default=[])
    parser.add_argument("--skill-selection-json", action="append", default=[])
    parser.add_argument("--context-evidence-json", action="append", default=[])
    parser.add_argument("--productivity-capture-json", action="append", default=[])
    parser.add_argument("--trajectory-report-json", action="append", default=[])
    parser.add_argument(
        "--low-confidence-threshold", type=float, default=DEFAULT_SKILL_LOW_CONFIDENCE_THRESHOLD
    )
    parser.add_argument(
        "--high-drift-threshold", type=float, default=DEFAULT_CONTEXT_HIGH_DRIFT_THRESHOLD
    )
    parser.add_argument("--top-failure-limit", type=int, default=DEFAULT_TOP_FAILURE_LIMIT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        target = write_feedback_report(
            args.report_json,
            feedback_events_json=args.feedback_events_json,
            merge_review_json=args.merge_review_json,
            skill_selection_json=args.skill_selection_json,
            context_evidence_json=args.context_evidence_json,
            productivity_capture_json=args.productivity_capture_json,
            trajectory_report_json=args.trajectory_report_json,
            low_confidence_threshold=args.low_confidence_threshold,
            high_drift_threshold=args.high_drift_threshold,
            top_failure_limit=args.top_failure_limit,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[feedback-regression] {exc}", file=sys.stderr)
        return 2
    payload = json.loads(target.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "report_json": str(target),
                "status": payload["summary"]["status"],
                "negative_feedback_count": payload["summary"]["negative_feedback_count"],
                "merge_review_conflict_count": payload["summary"]["merge_review_conflict_count"],
                "context_high_drift_count": payload["summary"]["context_high_drift_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
