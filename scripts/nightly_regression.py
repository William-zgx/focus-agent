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
DEFAULT_HISTORY_DIR = Path("reports/nightly/history")
DEFAULT_MEMORY_EVAL_JSON = Path("reports/release-gate/memory-context-eval.json")
DEFAULT_MEMORY_TREND_JSON = Path("reports/release-gate/memory-context-trend.json")
DELTA_NUMERIC_SUMMARY_KEYS = (
    "alert_count",
    "failed_replay_cases",
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
        records.extend(_history_record(path, source="history_dir") for path in _history_paths(history_dir))

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
        "previous_report_json": str(_resolve(previous_report_json)) if previous_report_json is not None else None,
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
    safe = "".join(character if character.isalnum() else "-" for character in generated_at).strip("-")
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
    target.write_text(json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
    previous_report_json: str | Path | None = None,
    history_json: Sequence[str | Path] = (),
    history_dir: str | Path | None = DEFAULT_HISTORY_DIR,
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
    summary = {
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
            regressions.append({"kind": "alert_report_signal", "detail": item, "path": artifact.get("path")})
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
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
    parser.add_argument("--candidate-review-jsonl", action="append", default=[])
    parser.add_argument("--candidate-approve-id", action="append", default=[])
    parser.add_argument("--candidate-reject-id", action="append", default=[])
    parser.add_argument("--candidate-approve-all", action="store_true")
    parser.add_argument("--candidate-reviewer")
    parser.add_argument("--candidate-review-note")
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
