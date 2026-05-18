#!/usr/bin/env python3
"""Build the nightly regression dashboard report."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import feedback_regression, memory_context_eval  # noqa: E402

DEFAULT_REPORT_JSON = Path("reports/nightly/latest.json")
DEFAULT_HISTORY_DIR = Path("reports/nightly/history")
DEFAULT_MEMORY_EVAL_JSON = Path("reports/release-gate/memory-context-eval.json")
DEFAULT_MEMORY_TREND_JSON = Path("reports/release-gate/memory-context-trend.json")
DEFAULT_REPLAY_JSON = Path("reports/nightly/trajectory-replay.json")
DEFAULT_ALERT_JSON = Path("reports/nightly/alerts.json")
DEFAULT_FEEDBACK_REGRESSION_JSON = feedback_regression.DEFAULT_REPORT_JSON
DEFAULT_CANDIDATE_JSONL = memory_context_eval.DEFAULT_CANDIDATE_JSONL
DEFAULT_REVIEWED_JSONL = memory_context_eval.DEFAULT_REVIEWED_JSONL
DEFAULT_PROMOTED_JSONL = memory_context_eval.DEFAULT_PROMOTED_JSONL
DELTA_NUMERIC_SUMMARY_KEYS = (
    "alert_count",
    "candidate_pending",
    "candidate_promoted",
    "candidate_reviewed",
    "candidate_sla_overdue",
    "candidate_total",
    "context_compaction_overall_drift_bp",
    "failed_replay_cases",
    "feedback_context_high_drift",
    "feedback_merge_review_conflicts",
    "feedback_negative",
    "feedback_notes_tasks_captures",
    "feedback_skill_low_confidence",
    "feedback_skill_overrides",
    "feedback_top_failing_trajectories",
    "memory_review_approved",
    "memory_review_pending",
    "memory_review_rejected",
    "missing_artifacts",
)
DELTA_STATUS_SUMMARY_KEYS = ("memory_eval_status", "memory_trend_status", "status")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve(path: str | Path) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = REPO_ROOT / target
    return target


def _command_text(command: Sequence[str]) -> str:
    return shlex.join(tuple(command))


def _read_json(path: str | Path) -> dict[str, Any] | None:
    target = _resolve(path)
    if not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target} must contain a JSON object")
    return payload


def _history_entry_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def _history_generated_at(payload: dict[str, Any]) -> str | None:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    generated_at = meta.get("generated_at") or payload.get("generated_at")
    return str(generated_at) if generated_at else None


def _history_record(path: str | Path, *, source: str) -> dict[str, Any]:
    target = _resolve(path)
    payload = _read_json(target)
    if payload is None:
        return {
            "generated_at": None,
            "path": str(target),
            "source": source,
            "status": "missing",
            "summary": {},
        }
    summary = _history_entry_summary(payload)
    return {
        "generated_at": _history_generated_at(payload),
        "path": str(target),
        "source": source,
        "status": "available" if summary else "invalid",
        "summary": summary,
    }


def _history_paths(history_dir: str | Path | None) -> list[Path]:
    if history_dir is None:
        return []
    target = _resolve(history_dir)
    if not target.exists():
        return []
    return sorted(path for path in target.glob("*.json") if path.is_file())


def _history_metadata(
    *,
    previous_report_json: str | Path | None,
    history_json: Sequence[str | Path],
    history_dir: str | Path | None,
) -> dict[str, Any]:
    explicit_history = [_resolve(path) for path in history_json]
    history_dir_path = _resolve(history_dir) if history_dir is not None else None
    records: list[dict[str, Any]]
    if previous_report_json is not None:
        records = [_history_record(previous_report_json, source="previous")]
    else:
        records = [_history_record(path, source="explicit_history") for path in explicit_history]
        records.extend(
            _history_record(path, source="history_dir") for path in _history_paths(history_dir)
        )

    available = [record for record in records if record.get("status") == "available"]
    baseline = None
    if available:
        baseline = max(
            available,
            key=lambda record: (
                str(record.get("generated_at") or ""),
                str(record.get("path") or ""),
            ),
        )
    return {
        "baseline": baseline,
        "baseline_status": "available" if baseline is not None else "missing",
        "explicit_history_json": [str(path) for path in explicit_history],
        "history_dir": str(history_dir_path) if history_dir_path is not None else None,
        "previous_report_json": str(_resolve(previous_report_json))
        if previous_report_json is not None
        else None,
        "source_count": len(records),
        "sources": [
            {
                "generated_at": record.get("generated_at"),
                "path": record.get("path"),
                "source": record.get("source"),
                "status": record.get("status"),
            }
            for record in records
        ],
    }


def _delta_value(current: Any, previous: Any) -> dict[str, Any]:
    return {
        "current": current,
        "delta": current - previous,
        "previous": previous,
    }


def _summary_delta(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any] | None,
    baseline_generated_at: str | None = None,
) -> dict[str, Any]:
    if baseline is None:
        return {
            "baseline_status": "missing",
            "numeric": {},
            "status": {},
        }

    numeric: dict[str, dict[str, Any]] = {}
    for key in DELTA_NUMERIC_SUMMARY_KEYS:
        current_value = int(current.get(key) or 0)
        previous_value = int(baseline.get(key) or 0)
        numeric[key] = _delta_value(current_value, previous_value)

    status: dict[str, dict[str, Any]] = {}
    for key in DELTA_STATUS_SUMMARY_KEYS:
        current_value = current.get(key)
        previous_value = baseline.get(key)
        status[key] = {
            "changed": current_value != previous_value,
            "current": current_value,
            "previous": previous_value,
        }

    return {
        "baseline_generated_at": baseline_generated_at,
        "baseline_status": "available",
        "numeric": numeric,
        "status": status,
    }


def _history_filename(generated_at: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in generated_at).strip(
        "-"
    )
    return f"{safe or 'nightly'}.json"


def _write_history_entry(
    *,
    history_dir: str | Path,
    payload: dict[str, Any],
    report_json: Path,
) -> Path:
    target_dir = _resolve(history_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    generated_at = str(payload["meta"]["generated_at"])
    target = target_dir / _history_filename(generated_at)
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        index = 2
        while target.exists():
            target = target_dir / f"{stem}-{index}{suffix}"
            index += 1
    memory_context_eval._reject_golden_dataset_output(target, operation="nightly history")
    entry = {
        "baseline_status": payload["baseline_status"],
        "delta": payload["delta"],
        "meta": {
            "generated_at": generated_at,
            "root": str(REPO_ROOT),
            "source_report_json": str(report_json),
            "suite": "nightly_regression_history",
        },
        "summary": payload["summary"],
    }
    target.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def _artifact_summary(path: str | Path, *, kind: str) -> dict[str, Any]:
    target = _resolve(path)
    payload = _read_json(target)
    if payload is None:
        return {"kind": kind, "path": str(target), "status": "missing"}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
    return {
        "kind": kind,
        "path": str(target),
        "status": str(payload.get("status") or _status_from_summary(summary, comparison)),
        "suite": _suite_name(payload),
        "summary": summary,
        "regressions": list(comparison.get("regressions") or []),
    }


def _suite_name(payload: dict[str, Any]) -> str | None:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    suite = meta.get("suite") or payload.get("suite")
    return str(suite) if suite else None


def _status_from_summary(summary: dict[str, Any], comparison: dict[str, Any]) -> str:
    if comparison.get("regressions"):
        return "failed"
    if int(summary.get("failed") or 0) > 0 or int(summary.get("errors") or 0) > 0:
        return "failed"
    if int(summary.get("total") or 0) > 0:
        return "passed"
    return "unknown"


def _trend_summary(path: str | Path) -> dict[str, Any]:
    target = _resolve(path)
    payload = _read_json(target)
    if payload is None:
        return {"kind": "memory_trend", "path": str(target), "status": "missing"}
    alerts = list(payload.get("pollution_alerts") or [])
    promotion = (
        payload.get("promotion_history")
        if isinstance(payload.get("promotion_history"), dict)
        else {}
    )
    drift_report = _trend_drift_report(payload)
    return {
        "kind": "memory_trend",
        "path": str(target),
        "status": str(payload.get("status") or ("alert" if alerts else "ok")),
        "suite": _suite_name(payload),
        "trend": list(payload.get("trend") or []),
        "context_compaction_drift_report": drift_report,
        "promotion_history": promotion,
        "pollution_alerts": alerts,
    }


def _trend_drift_report(payload: dict[str, Any]) -> dict[str, Any]:
    stages = payload.get("stages") if isinstance(payload.get("stages"), dict) else {}
    reports = [
        stage.get("context_compaction_drift_report")
        for stage in stages.values()
        if isinstance(stage, dict)
        and isinstance(stage.get("context_compaction_drift_report"), dict)
    ]
    if not reports:
        for item in list(payload.get("trend") or []):
            if not isinstance(item, dict):
                continue
            report = item.get("context_compaction_drift_report")
            if isinstance(report, dict):
                reports.append(report)
    if not reports:
        return {
            "recall": 1.0,
            "precision": 1.0,
            "grounding": 1.0,
            "answerability": 1.0,
            "overall_drift": 0.0,
            "drift_risk": "low",
            "case_count": 0,
        }
    worst = max(reports, key=lambda report: float(report.get("overall_drift") or 0.0))
    return dict(worst)


def _replay_summary(path: str | Path) -> dict[str, Any]:
    artifact = _artifact_summary(path, kind="replay")
    payload = _read_json(path)
    if payload is None:
        return artifact
    records = payload.get("results") if isinstance(payload.get("results"), list) else []
    failed_case_ids = [
        str(record.get("case_id") or record.get("id"))
        for record in records
        if isinstance(record, dict) and not bool(record.get("passed", True))
    ]
    artifact["failed_case_ids"] = [case_id for case_id in failed_case_ids if case_id]
    artifact["failed"] = len(artifact["failed_case_ids"])
    return artifact


def _alert_summary(path: str | Path) -> dict[str, Any]:
    target = _resolve(path)
    payload = _read_json(target)
    if payload is None:
        return {"kind": "alert", "path": str(target), "status": "missing", "alerts": []}
    alerts = payload.get("alerts")
    if not isinstance(alerts, list):
        alerts = payload.get("pollution_alerts")
    if not isinstance(alerts, list):
        alerts = payload.get("regressions")
    if not isinstance(alerts, list):
        alerts = []
    return {
        "kind": "alert",
        "path": str(target),
        "status": str(payload.get("status") or ("alert" if alerts else "ok")),
        "alerts": alerts,
        "alert_count": len(alerts),
    }


def _feedback_report_summary(path: str | Path) -> dict[str, Any]:
    target = _resolve(path)
    payload = _read_json(target)
    if payload is None:
        return {
            "kind": "feedback_regression",
            "path": str(target),
            "status": "not_configured",
            "summary": {
                "negative_feedback_count": 0,
                "merge_review_conflict_count": 0,
                "skill_low_confidence_count": 0,
                "skill_override_count": 0,
                "context_high_drift_count": 0,
                "notes_tasks_capture_count": 0,
                "top_failing_trajectory_sample_count": 0,
            },
            "feedback_pipeline": {
                "status": "not_configured",
                "negative_feedback": {"count": 0, "sample_ids": []},
                "merge_review": {
                    "record_count": 0,
                    "apply_success_count": 0,
                    "conflict_count": 0,
                    "rejected_count": 0,
                    "error_count": 0,
                    "apply_attempt_count": 0,
                    "apply_success_rate": None,
                },
                "skill_selection": {
                    "record_count": 0,
                    "low_confidence_count": 0,
                    "override_count": 0,
                    "override_rate": None,
                },
                "context_memory": {"record_count": 0, "high_drift_count": 0},
                "productivity_capture": {"record_count": 0, "capture_count": 0},
                "trajectory_failures": {"top_failing_samples": [], "top_failing_sample_count": 0},
            },
        }
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    pipeline = (
        payload.get("feedback_pipeline")
        if isinstance(payload.get("feedback_pipeline"), dict)
        else {}
    )
    return {
        "kind": "feedback_regression",
        "path": str(target),
        "status": str(summary.get("status") or pipeline.get("status") or "unknown"),
        "summary": summary,
        "feedback_pipeline": pipeline,
    }


def _existing_default_artifacts(*paths: Path) -> list[Path]:
    return [_resolve(path) for path in paths if _resolve(path).exists()]


def _load_jsonl_cases(path: str | Path) -> list[dict[str, Any]]:
    target = _resolve(path)
    if not target.exists():
        return []
    return memory_context_eval.load_dataset(target)


def _candidate_artifact_summary(path: str | Path, *, kind: str) -> dict[str, Any]:
    target = _resolve(path)
    if not target.exists():
        return {"kind": kind, "path": str(target), "status": "missing", "total": 0}
    cases = _load_jsonl_cases(target)
    review_status_counts: dict[str, int] = {}
    for case in cases:
        review = (
            case.get("promotion_review") if isinstance(case.get("promotion_review"), dict) else {}
        )
        status = str(review.get("status") or "")
        if status:
            review_status_counts[status] = review_status_counts.get(status, 0) + 1
    return {
        "kind": kind,
        "path": str(target),
        "status": "available",
        "total": len(cases),
        "case_ids": [str(case.get("id") or "unknown") for case in cases],
        "review_status_counts": review_status_counts,
        "promotion_sla_summary": memory_context_eval._promotion_sla_summary(cases),
    }


def _candidate_pipeline_summary(
    *,
    candidate_jsonl: Sequence[str | Path],
    reviewed_jsonl: Sequence[str | Path],
    promoted_jsonl: Sequence[str | Path],
    memory_review: dict[str, Any],
) -> dict[str, Any]:
    candidate_artifacts = [
        _candidate_artifact_summary(path, kind="candidate") for path in candidate_jsonl
    ]
    reviewed_artifacts = [
        _candidate_artifact_summary(path, kind="reviewed") for path in reviewed_jsonl
    ]
    promoted_artifacts = [
        _candidate_artifact_summary(path, kind="promoted") for path in promoted_jsonl
    ]
    candidate_total = sum(int(item.get("total") or 0) for item in candidate_artifacts)
    reviewed_total = sum(int(item.get("total") or 0) for item in reviewed_artifacts)
    promoted_count = sum(int(item.get("total") or 0) for item in promoted_artifacts)

    review_counts: dict[str, int] = {}
    sla_overdue = 0
    pending_sla_overdue = 0
    for artifact in reviewed_artifacts:
        for status, count in (artifact.get("review_status_counts") or {}).items():
            review_counts[str(status)] = review_counts.get(str(status), 0) + int(count)
        sla = (
            artifact.get("promotion_sla_summary")
            if isinstance(artifact.get("promotion_sla_summary"), dict)
            else {}
        )
        sla_overdue += int(sla.get("overdue") or 0)
        pending_sla_overdue += int(sla.get("pending_overdue") or 0)

    queue = memory_review.get("queue") if isinstance(memory_review.get("queue"), dict) else {}
    review_payload = (
        memory_review.get("review") if isinstance(memory_review.get("review"), dict) else {}
    )
    review_sla = (
        review_payload.get("promotion_sla_summary")
        if isinstance(review_payload.get("promotion_sla_summary"), dict)
        else {}
    )
    if not candidate_total:
        candidate_total = int(queue.get("records") or 0)
    if not reviewed_total and memory_review.get("status") == "ready":
        reviewed_total = int(
            review_payload.get("reviewed")
            if "reviewed" in review_payload
            else queue.get("records") or 0
        )
    if not review_counts:
        review_counts = {
            key: int(queue.get(key) or 0)
            for key in ("approved", "rejected", "pending")
            if int(queue.get(key) or 0)
        }
    if not promoted_count:
        promoted_count = len(memory_review.get("promoted_case_ids") or [])
    if not sla_overdue:
        sla_overdue = int(review_sla.get("overdue") or 0)
    if not pending_sla_overdue:
        pending_sla_overdue = int(review_sla.get("pending_overdue") or 0)

    return {
        "status": "ready"
        if candidate_total or reviewed_total or promoted_count
        else "not_configured",
        "candidate_total": candidate_total,
        "reviewed_total": reviewed_total,
        "pending": int(review_counts.get("pending") or queue.get("pending") or 0),
        "approved": int(review_counts.get("approved") or queue.get("approved") or 0),
        "rejected": int(review_counts.get("rejected") or queue.get("rejected") or 0),
        "sla_overdue": sla_overdue,
        "pending_sla_overdue": pending_sla_overdue,
        "promoted_count": promoted_count,
        "artifacts": {
            "candidate": candidate_artifacts,
            "reviewed": reviewed_artifacts,
            "promoted": promoted_artifacts,
        },
        "baseline_delta": {},
    }


def _replay_pipeline_summary(replay: Sequence[dict[str, Any]]) -> dict[str, Any]:
    failed_case_ids = [
        str(case_id) for artifact in replay for case_id in (artifact.get("failed_case_ids") or [])
    ]
    return {
        "status": "ready" if replay else "not_configured",
        "report_count": len(replay),
        "total_cases": sum(int((item.get("summary") or {}).get("total") or 0) for item in replay),
        "failed_replay_cases": len(failed_case_ids),
        "failed_case_ids": failed_case_ids,
        "alert_count": 0,
        "baseline_delta": {},
    }


def _build_memory_review(
    *,
    candidate_jsonl: Sequence[str | Path],
    approved_ids: Sequence[str],
    rejected_ids: Sequence[str],
    approve_all: bool,
    reviewer: str | None,
    note: str | None,
) -> dict[str, Any]:
    if not candidate_jsonl:
        return {
            "status": "not_configured",
            "queue": {"sources": 0, "records": 0, "pending": 0},
            "review": None,
        }
    result = memory_context_eval.review_candidate_cases(
        candidate_jsonl,
        approved_ids=approved_ids,
        rejected_ids=rejected_ids,
        approve_all=approve_all,
        reviewer=reviewer,
        note=note,
    )
    return {
        "status": "ready",
        "queue": {
            "sources": result.source_count,
            "records": result.record_count,
            "pending": result.pending_count,
            "approved": result.approved_count,
            "rejected": result.rejected_count,
            "skipped_no_assertions": result.skipped_no_assertions,
            "skipped_duplicates": result.skipped_duplicates,
        },
        "review": result.to_dict(),
        "pending_case_ids": [
            str(case.get("id"))
            for case in result.reviewed_cases
            if (case.get("promotion_review") or {}).get("status") == "pending"
        ],
        "promoted_case_ids": [str(case.get("id")) for case in result.promoted_cases],
    }


def build_nightly_report(
    *,
    memory_eval_json: str | Path = DEFAULT_MEMORY_EVAL_JSON,
    memory_trend_json: str | Path = DEFAULT_MEMORY_TREND_JSON,
    previous_report_json: str | Path | None = None,
    history_json: Sequence[str | Path] = (),
    history_dir: str | Path | None = DEFAULT_HISTORY_DIR,
    replay_json: Sequence[str | Path] | None = None,
    alert_json: Sequence[str | Path] | None = None,
    candidate_jsonl: Sequence[str | Path] | None = None,
    candidate_review_jsonl: Sequence[str | Path] | None = None,
    candidate_reviewed_jsonl: Sequence[str | Path] | None = None,
    candidate_promoted_jsonl: Sequence[str | Path] | None = None,
    candidate_approve_id: Sequence[str] = (),
    candidate_reject_id: Sequence[str] = (),
    candidate_approve_all: bool = False,
    candidate_reviewer: str | None = None,
    candidate_review_note: str | None = None,
    feedback_report_json: str | Path = DEFAULT_FEEDBACK_REGRESSION_JSON,
) -> dict[str, Any]:
    memory_eval = _artifact_summary(memory_eval_json, kind="memory_eval")
    memory_trend = _trend_summary(memory_trend_json)
    replay_inputs = (
        _existing_default_artifacts(DEFAULT_REPLAY_JSON)
        if replay_json is None
        else list(replay_json)
    )
    alert_inputs = (
        _existing_default_artifacts(DEFAULT_ALERT_JSON) if alert_json is None else list(alert_json)
    )
    candidate_inputs = (
        _existing_default_artifacts(DEFAULT_CANDIDATE_JSONL)
        if candidate_jsonl is None
        else list(candidate_jsonl)
    )
    if candidate_jsonl is None and candidate_review_jsonl is not None:
        candidate_inputs = list(candidate_review_jsonl)
    candidate_review_inputs = (
        list(candidate_review_jsonl)
        if candidate_review_jsonl is not None
        else list(candidate_inputs)
    )
    reviewed_inputs = (
        _existing_default_artifacts(DEFAULT_REVIEWED_JSONL)
        if candidate_reviewed_jsonl is None
        else list(candidate_reviewed_jsonl)
    )
    promoted_inputs = (
        _existing_default_artifacts(DEFAULT_PROMOTED_JSONL)
        if candidate_promoted_jsonl is None
        else list(candidate_promoted_jsonl)
    )
    replay = [_replay_summary(path) for path in replay_inputs]
    alerts = [_alert_summary(path) for path in alert_inputs]
    feedback_report = _feedback_report_summary(feedback_report_json)
    feedback_summary = (
        feedback_report.get("summary") if isinstance(feedback_report.get("summary"), dict) else {}
    )
    feedback_pipeline = (
        feedback_report.get("feedback_pipeline")
        if isinstance(feedback_report.get("feedback_pipeline"), dict)
        else {}
    )
    memory_review = _build_memory_review(
        candidate_jsonl=candidate_review_inputs,
        approved_ids=candidate_approve_id,
        rejected_ids=candidate_reject_id,
        approve_all=candidate_approve_all,
        reviewer=candidate_reviewer,
        note=candidate_review_note,
    )
    candidate_pipeline = _candidate_pipeline_summary(
        candidate_jsonl=candidate_inputs,
        reviewed_jsonl=reviewed_inputs,
        promoted_jsonl=promoted_inputs,
        memory_review=memory_review,
    )
    replay_pipeline = _replay_pipeline_summary(replay)
    alert_count = len(memory_trend.get("pollution_alerts") or []) + sum(
        int(item.get("alert_count") or 0) for item in alerts
    )
    failed_replays = sum(int(item.get("failed") or 0) for item in replay)
    replay_pipeline["failed_replay_cases"] = failed_replays
    replay_pipeline["alert_count"] = sum(int(item.get("alert_count") or 0) for item in alerts)
    candidate_pipeline["alert_count"] = len(memory_trend.get("pollution_alerts") or [])
    compaction_drift_report = (
        memory_trend.get("context_compaction_drift_report")
        if isinstance(memory_trend.get("context_compaction_drift_report"), dict)
        else {}
    )
    context_compaction_overall_drift = float(compaction_drift_report.get("overall_drift") or 0.0)
    missing_artifacts = [
        item["path"]
        for item in [memory_eval, memory_trend, *replay, *alerts]
        if item.get("status") == "missing"
    ]
    has_failed_eval = memory_eval.get("status") == "failed"
    has_feedback_alert = feedback_report.get("status") == "alert"
    status = (
        "failed"
        if has_failed_eval or failed_replays or missing_artifacts
        else "alert"
        if alert_count or has_feedback_alert
        else "passed"
    )
    regressions = _build_regressions(
        memory_eval=memory_eval,
        memory_trend=memory_trend,
        replay=replay,
        alerts=alerts,
    )
    candidate_outputs = {
        "golden_write": "disabled",
        "sources": [str(_resolve(path)) for path in candidate_inputs],
        "review_sources": [str(_resolve(path)) for path in candidate_review_inputs],
        "reviewed_outputs": [str(_resolve(path)) for path in reviewed_inputs],
        "promoted_outputs": [str(_resolve(path)) for path in promoted_inputs],
        "review_status": memory_review["status"],
        "pending_case_ids": list(memory_review.get("pending_case_ids") or []),
        "promoted_case_ids": list(memory_review.get("promoted_case_ids") or []),
        "review_summary": memory_review["queue"],
        "candidate_pipeline": candidate_pipeline,
    }
    commands = [
        {
            "label": "memory-context-eval",
            "command": _command_text(
                (
                    "uv",
                    "run",
                    "python",
                    "scripts/memory_context_eval.py",
                    "--report-json",
                    str(memory_eval_json),
                )
            ),
            "artifact": str(_resolve(memory_eval_json)),
            "status": "available" if memory_eval.get("status") != "missing" else "missing",
        },
        {
            "label": "memory-context-trend",
            "command": _command_text(
                (
                    "uv",
                    "run",
                    "python",
                    "scripts/memory_context_eval.py",
                    "--trend-report-json",
                    str(memory_trend_json),
                )
            ),
            "artifact": str(_resolve(memory_trend_json)),
            "status": "available" if memory_trend.get("status") != "missing" else "missing",
        },
        {
            "label": "trajectory-replay",
            "command": _command_text(
                (
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "tests.eval",
                    "replay",
                    "--trajectory-input",
                    "--run",
                    "--report-json",
                    str(replay_inputs[0] if replay_inputs else DEFAULT_REPLAY_JSON),
                )
            ),
            "artifact": [str(_resolve(path)) for path in (replay_inputs or [DEFAULT_REPLAY_JSON])],
            "status": "available" if replay_inputs else "not_configured",
        },
        {
            "label": "nightly-alerts",
            "command": _command_text(
                (
                    "uv",
                    "run",
                    "python",
                    "scripts/nightly_regression.py",
                    "--alert-json",
                    str(alert_inputs[0] if alert_inputs else DEFAULT_ALERT_JSON),
                )
            ),
            "artifact": [str(_resolve(path)) for path in (alert_inputs or [DEFAULT_ALERT_JSON])],
            "status": "available" if alert_inputs else "not_configured",
        },
        {
            "label": "feedback-regression",
            "command": _command_text(
                (
                    "uv",
                    "run",
                    "python",
                    "scripts/feedback_regression.py",
                    "--report-json",
                    str(feedback_report_json),
                )
            ),
            "artifact": str(_resolve(feedback_report_json)),
            "status": "available"
            if feedback_report.get("status") != "not_configured"
            else "not_configured",
        },
    ]
    summary = {
        "status": status,
        "memory_eval_status": memory_eval.get("status"),
        "memory_trend_status": memory_trend.get("status"),
        "alert_count": alert_count,
        "failed_replay_cases": failed_replays,
        "missing_artifacts": len(missing_artifacts),
        "missing_artifact_paths": missing_artifacts,
        "candidate_total": candidate_pipeline["candidate_total"],
        "candidate_reviewed": candidate_pipeline["reviewed_total"],
        "candidate_pending": candidate_pipeline["pending"],
        "candidate_sla_overdue": candidate_pipeline["sla_overdue"],
        "candidate_promoted": candidate_pipeline["promoted_count"],
        "context_compaction_drift_report": compaction_drift_report,
        "context_compaction_overall_drift": context_compaction_overall_drift,
        "context_compaction_overall_drift_bp": int(round(context_compaction_overall_drift * 10000)),
        "memory_review_pending": memory_review["queue"]["pending"],
        "memory_review_approved": memory_review["queue"].get("approved", 0),
        "memory_review_rejected": memory_review["queue"].get("rejected", 0),
        "candidate_pipeline": candidate_pipeline,
        "replay_pipeline": replay_pipeline,
        "feedback_pipeline": feedback_pipeline,
        "feedback_negative": int(feedback_summary.get("negative_feedback_count") or 0),
        "feedback_merge_review_conflicts": int(
            feedback_summary.get("merge_review_conflict_count") or 0
        ),
        "feedback_skill_low_confidence": int(
            feedback_summary.get("skill_low_confidence_count") or 0
        ),
        "feedback_skill_overrides": int(feedback_summary.get("skill_override_count") or 0),
        "feedback_context_high_drift": int(feedback_summary.get("context_high_drift_count") or 0),
        "feedback_notes_tasks_captures": int(
            feedback_summary.get("notes_tasks_capture_count") or 0
        ),
        "feedback_top_failing_trajectories": int(
            feedback_summary.get("top_failing_trajectory_sample_count") or 0
        ),
    }
    history = _history_metadata(
        previous_report_json=previous_report_json,
        history_json=history_json,
        history_dir=history_dir,
    )
    baseline = history.pop("baseline")
    baseline_summary = baseline.get("summary") if isinstance(baseline, dict) else None
    baseline_generated_at = baseline.get("generated_at") if isinstance(baseline, dict) else None
    if not isinstance(baseline_summary, dict):
        baseline_summary = None
    delta = _summary_delta(
        current=summary,
        baseline=baseline_summary,
        baseline_generated_at=str(baseline_generated_at) if baseline_generated_at else None,
    )
    baseline_status = str(delta["baseline_status"])
    summary["baseline_status"] = baseline_status
    baseline_delta = {
        key: int(value.get("delta") or 0)
        for key, value in (delta.get("numeric") or {}).items()
        if isinstance(value, dict)
    }
    summary["baseline_delta"] = baseline_delta
    candidate_pipeline["baseline_delta"] = {
        key: baseline_delta[key]
        for key in (
            "candidate_total",
            "candidate_reviewed",
            "candidate_pending",
            "candidate_sla_overdue",
            "candidate_promoted",
        )
        if key in baseline_delta
    }
    replay_pipeline["baseline_delta"] = {
        key: baseline_delta[key]
        for key in ("failed_replay_cases", "alert_count")
        if key in baseline_delta
    }

    return {
        "baseline_status": baseline_status,
        "meta": {
            "suite": "nightly_regression",
            "generated_at": _now_iso(),
            "root": str(REPO_ROOT),
            "golden_write": "disabled",
        },
        "commands": commands,
        "delta": delta,
        "history": history,
        "artifacts": {
            "memory_eval": memory_eval,
            "memory_trend": memory_trend,
            "replay": replay,
            "alerts": alerts,
            "feedback_regression": feedback_report,
            "candidate_pipeline": candidate_pipeline["artifacts"],
        },
        "memory_review": memory_review,
        "regressions": regressions,
        "candidate_outputs": candidate_outputs,
        "summary": summary,
    }


def _build_regressions(
    *,
    memory_eval: dict[str, Any],
    memory_trend: dict[str, Any],
    replay: Sequence[dict[str, Any]],
    alerts: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    regressions: list[dict[str, Any]] = []
    for item in memory_eval.get("regressions") or []:
        regressions.append({"kind": "memory_eval_regression", "detail": item})
    for item in memory_trend.get("pollution_alerts") or []:
        regressions.append({"kind": "memory_pollution_alert", "detail": item})
    for artifact in replay:
        for case_id in artifact.get("failed_case_ids") or []:
            regressions.append(
                {
                    "kind": "trajectory_replay_failure",
                    "case_id": case_id,
                    "path": artifact.get("path"),
                }
            )
    for artifact in alerts:
        for item in artifact.get("alerts") or []:
            regressions.append(
                {"kind": "alert_report_signal", "detail": item, "path": artifact.get("path")}
            )
    return regressions


def write_nightly_report(
    path: str | Path,
    *,
    append_history: bool = True,
    history_dir: str | Path | None = DEFAULT_HISTORY_DIR,
    **kwargs: Any,
) -> Path:
    target = _resolve(path)
    memory_context_eval._reject_golden_dataset_output(target, operation="nightly reports")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_nightly_report(history_dir=history_dir, **kwargs)
    history_append = {
        "enabled": bool(append_history and history_dir is not None),
        "path": None,
        "status": "disabled",
    }
    if append_history and history_dir is not None:
        history_path = _write_history_entry(
            history_dir=history_dir,
            payload=payload,
            report_json=target,
        )
        history_append = {
            "enabled": True,
            "path": str(history_path),
            "status": "written",
        }
    payload["history"]["append"] = history_append
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR))
    parser.add_argument("--history-json", action="append", default=[])
    parser.add_argument("--memory-eval-json", default=str(DEFAULT_MEMORY_EVAL_JSON))
    parser.add_argument("--memory-trend-json", default=str(DEFAULT_MEMORY_TREND_JSON))
    parser.add_argument("--previous-report-json")
    parser.add_argument("--replay-json", action="append", default=[])
    parser.add_argument("--alert-json", action="append", default=[])
    parser.add_argument("--candidate-jsonl", action="append", default=None)
    parser.add_argument("--candidate-review-jsonl", action="append", default=None)
    parser.add_argument("--candidate-reviewed-jsonl", action="append", default=None)
    parser.add_argument("--candidate-promoted-jsonl", action="append", default=None)
    parser.add_argument("--candidate-approve-id", action="append", default=[])
    parser.add_argument("--candidate-reject-id", action="append", default=[])
    parser.add_argument("--candidate-approve-all", action="store_true")
    parser.add_argument("--candidate-reviewer")
    parser.add_argument("--candidate-review-note")
    parser.add_argument("--feedback-report-json", default=str(DEFAULT_FEEDBACK_REGRESSION_JSON))
    parser.add_argument("--skip-history-append", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        target = write_nightly_report(
            args.report_json,
            append_history=not bool(args.skip_history_append),
            history_dir=args.history_dir,
            previous_report_json=args.previous_report_json,
            history_json=args.history_json,
            memory_eval_json=args.memory_eval_json,
            memory_trend_json=args.memory_trend_json,
            replay_json=args.replay_json,
            alert_json=args.alert_json,
            candidate_jsonl=args.candidate_jsonl,
            candidate_review_jsonl=args.candidate_review_jsonl,
            candidate_reviewed_jsonl=args.candidate_reviewed_jsonl,
            candidate_promoted_jsonl=args.candidate_promoted_jsonl,
            candidate_approve_id=args.candidate_approve_id,
            candidate_reject_id=args.candidate_reject_id,
            candidate_approve_all=bool(args.candidate_approve_all),
            candidate_reviewer=args.candidate_reviewer,
            candidate_review_note=args.candidate_review_note,
            feedback_report_json=args.feedback_report_json,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[nightly-regression] {exc}", file=sys.stderr)
        return 2
    payload = json.loads(target.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "baseline_status": payload["baseline_status"],
                "report_json": str(target),
                "status": payload["summary"]["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if payload["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
