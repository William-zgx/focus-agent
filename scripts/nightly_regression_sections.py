"""Section builders for the nightly regression dashboard."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts import memory_context_eval

_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


def _active_repo_root() -> Path:
    module = sys.modules.get("scripts.nightly_regression") or sys.modules.get("__main__")
    if module is not None and str(getattr(module, "__file__", "")).endswith("nightly_regression.py"):
        return Path(getattr(module, "REPO_ROOT", _DEFAULT_REPO_ROOT))
    return _DEFAULT_REPO_ROOT


def _resolve(path: str | Path) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = _active_repo_root() / target
    return target


def _read_json(path: str | Path) -> dict[str, Any] | None:
    target = _resolve(path)
    if not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target} must contain a JSON object")
    return payload

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
