#!/usr/bin/env python3
"""Build the nightly regression dashboard report."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import memory_context_eval  # noqa: E402

DEFAULT_REPORT_JSON = Path("reports/nightly/latest.json")
DEFAULT_MEMORY_EVAL_JSON = Path("reports/release-gate/memory-context-eval.json")
DEFAULT_MEMORY_TREND_JSON = Path("reports/release-gate/memory-context-trend.json")


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
    promotion = payload.get("promotion_history") if isinstance(payload.get("promotion_history"), dict) else {}
    return {
        "kind": "memory_trend",
        "path": str(target),
        "status": str(payload.get("status") or ("alert" if alerts else "ok")),
        "suite": _suite_name(payload),
        "trend": list(payload.get("trend") or []),
        "promotion_history": promotion,
        "pollution_alerts": alerts,
    }


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
    replay_json: Sequence[str | Path] = (),
    alert_json: Sequence[str | Path] = (),
    candidate_review_jsonl: Sequence[str | Path] = (),
    candidate_approve_id: Sequence[str] = (),
    candidate_reject_id: Sequence[str] = (),
    candidate_approve_all: bool = False,
    candidate_reviewer: str | None = None,
    candidate_review_note: str | None = None,
) -> dict[str, Any]:
    memory_eval = _artifact_summary(memory_eval_json, kind="memory_eval")
    memory_trend = _trend_summary(memory_trend_json)
    replay = [_replay_summary(path) for path in replay_json]
    alerts = [_alert_summary(path) for path in alert_json]
    memory_review = _build_memory_review(
        candidate_jsonl=candidate_review_jsonl,
        approved_ids=candidate_approve_id,
        rejected_ids=candidate_reject_id,
        approve_all=candidate_approve_all,
        reviewer=candidate_reviewer,
        note=candidate_review_note,
    )
    alert_count = len(memory_trend.get("pollution_alerts") or []) + sum(
        int(item.get("alert_count") or 0) for item in alerts
    )
    failed_replays = sum(int(item.get("failed") or 0) for item in replay)
    missing_artifacts = [
        item["path"]
        for item in [memory_eval, memory_trend, *replay, *alerts]
        if item.get("status") == "missing"
    ]
    has_failed_eval = memory_eval.get("status") == "failed"
    status = (
        "failed"
        if has_failed_eval or failed_replays or missing_artifacts
        else "alert"
        if alert_count
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
        "sources": [str(_resolve(path)) for path in candidate_review_jsonl],
        "review_status": memory_review["status"],
        "pending_case_ids": list(memory_review.get("pending_case_ids") or []),
        "promoted_case_ids": list(memory_review.get("promoted_case_ids") or []),
        "review_summary": memory_review["queue"],
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
    ]

    return {
        "meta": {
            "suite": "nightly_regression",
            "generated_at": _now_iso(),
            "root": str(REPO_ROOT),
            "golden_write": "disabled",
        },
        "commands": commands,
        "artifacts": {
            "memory_eval": memory_eval,
            "memory_trend": memory_trend,
            "replay": replay,
            "alerts": alerts,
        },
        "memory_review": memory_review,
        "regressions": regressions,
        "candidate_outputs": candidate_outputs,
        "summary": {
            "status": status,
            "memory_eval_status": memory_eval.get("status"),
            "memory_trend_status": memory_trend.get("status"),
            "alert_count": alert_count,
            "failed_replay_cases": failed_replays,
            "missing_artifacts": len(missing_artifacts),
            "missing_artifact_paths": missing_artifacts,
            "memory_review_pending": memory_review["queue"]["pending"],
            "memory_review_approved": memory_review["queue"].get("approved", 0),
            "memory_review_rejected": memory_review["queue"].get("rejected", 0),
        },
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
            regressions.append({"kind": "alert_report_signal", "detail": item, "path": artifact.get("path")})
    return regressions


def write_nightly_report(path: str | Path, **kwargs: Any) -> Path:
    target = _resolve(path)
    memory_context_eval._reject_golden_dataset_output(target, operation="nightly reports")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_nightly_report(**kwargs)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--memory-eval-json", default=str(DEFAULT_MEMORY_EVAL_JSON))
    parser.add_argument("--memory-trend-json", default=str(DEFAULT_MEMORY_TREND_JSON))
    parser.add_argument("--replay-json", action="append", default=[])
    parser.add_argument("--alert-json", action="append", default=[])
    parser.add_argument("--candidate-review-jsonl", action="append", default=[])
    parser.add_argument("--candidate-approve-id", action="append", default=[])
    parser.add_argument("--candidate-reject-id", action="append", default=[])
    parser.add_argument("--candidate-approve-all", action="store_true")
    parser.add_argument("--candidate-reviewer")
    parser.add_argument("--candidate-review-note")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        target = write_nightly_report(
            args.report_json,
            memory_eval_json=args.memory_eval_json,
            memory_trend_json=args.memory_trend_json,
            replay_json=args.replay_json,
            alert_json=args.alert_json,
            candidate_review_jsonl=args.candidate_review_jsonl,
            candidate_approve_id=args.candidate_approve_id,
            candidate_reject_id=args.candidate_reject_id,
            candidate_approve_all=bool(args.candidate_approve_all),
            candidate_reviewer=args.candidate_reviewer,
            candidate_review_note=args.candidate_review_note,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[nightly-regression] {exc}", file=sys.stderr)
        return 2
    payload = json.loads(target.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {"status": payload["summary"]["status"], "report_json": str(target)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if payload["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
