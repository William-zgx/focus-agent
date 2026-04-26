#!/usr/bin/env python3
"""Build the Agent Governance quality report."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_JSON = Path("reports/agent-governance/latest.json")
DEFAULT_EVAL_REPORTS: tuple[tuple[str, Path], ...] = (
    ("delegation", Path("reports/release-gate/eval-agent-delegation.json")),
    ("governance", Path("reports/release-gate/eval-agent-governance.json")),
    ("task-ledger", Path("reports/release-gate/eval-agent-task-ledger.json")),
    ("agent-team", Path("reports/release-gate/eval-agent-team.json")),
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve(path: str | Path) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = REPO_ROOT / target
    return target


def _read_json(path: str | Path) -> dict[str, Any] | None:
    target = _resolve(path)
    if not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target} must contain a JSON object")
    return payload


def _command_text(command: Sequence[str]) -> str:
    return shlex.join(tuple(command))


def _status_from_summary(summary: dict[str, Any], comparison: dict[str, Any]) -> str:
    if comparison.get("regressions"):
        return "failed"
    if int(summary.get("failed") or 0) > 0 or int(summary.get("errors") or 0) > 0:
        return "failed"
    if int(summary.get("total") or 0) > 0:
        return "passed"
    return "unknown"


def _split_eval_report(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError("--eval-report must use LABEL=PATH")
    label, path = value.split("=", 1)
    label = label.strip()
    if not label:
        raise ValueError("--eval-report label cannot be empty")
    return label, Path(path)


def _artifact(label: str, path: str | Path) -> dict[str, Any]:
    target = _resolve(path)
    payload = _read_json(target)
    if payload is None:
        return {"label": label, "path": str(target), "status": "missing"}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return {
        "label": label,
        "path": str(target),
        "status": str(payload.get("status") or _status_from_summary(summary, comparison)),
        "suite": str(meta.get("suite") or label),
        "summary": summary,
        "regressions": list(comparison.get("regressions") or []),
    }


def _tag_success(artifacts: Sequence[dict[str, Any]], tags: Sequence[str]) -> dict[str, Any]:
    matched: dict[str, float] = {}
    for artifact in artifacts:
        summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
        per_tag = summary.get("per_tag_success") if isinstance(summary.get("per_tag_success"), dict) else {}
        for tag in tags:
            if tag in per_tag:
                matched[tag] = float(per_tag[tag])
    if not matched:
        return {"status": "missing", "task_success": 0.0, "tags": {}}
    return {
        "status": "passed" if min(matched.values()) >= 1.0 else "attention",
        "task_success": round(sum(matched.values()) / len(matched), 4),
        "tags": matched,
    }


def _cost_quality(artifacts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    present = [
        artifact.get("summary")
        for artifact in artifacts
        if artifact.get("status") != "missing" and isinstance(artifact.get("summary"), dict)
    ]
    if not present:
        return {"status": "missing", "avg_cost_usd": 0.0, "avg_input_tokens": 0.0, "avg_output_tokens": 0.0}
    total_cases = sum(int(summary.get("total") or 0) for summary in present) or len(present)

    def weighted(name: str) -> float:
        numerator = sum(float(summary.get(name) or 0.0) * int(summary.get("total") or 1) for summary in present)
        return round(numerator / total_cases, 5 if name == "avg_cost_usd" else 1)

    return {
        "status": "passed",
        "avg_cost_usd": weighted("avg_cost_usd"),
        "avg_input_tokens": weighted("avg_input_tokens"),
        "avg_output_tokens": weighted("avg_output_tokens"),
        "avg_tool_calls": round(
            sum(float(summary.get("avg_tool_calls") or 0.0) for summary in present) / len(present),
            3,
        ),
    }


def build_governance_report(
    *,
    eval_reports: Sequence[tuple[str, str | Path]] = DEFAULT_EVAL_REPORTS,
) -> dict[str, Any]:
    artifacts = [_artifact(label, path) for label, path in eval_reports]
    missing = [artifact["path"] for artifact in artifacts if artifact.get("status") == "missing"]
    failed = [artifact["label"] for artifact in artifacts if artifact.get("status") == "failed"]
    quality = {
        "delegation": _tag_success(artifacts, ("agent_delegation", "agent_task_ledger", "agent_team")),
        "critic": _tag_success(artifacts, ("critic", "critic_gate", "reviewer")),
        "review": _tag_success(artifacts, ("review_queue", "merge_review", "memory_curator")),
        "cost": _cost_quality(artifacts),
    }
    quality_attention = [
        name
        for name, item in quality.items()
        if isinstance(item, dict) and item.get("status") in {"attention", "missing"}
    ]
    status = "failed" if failed else "incomplete" if missing else "passed"
    commands = [
        {
            "label": f"eval-{label}",
            "command": _command_text(
                (
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "tests.eval",
                    "--suite",
                    label.replace("-", "_"),
                    "--concurrency",
                    "1",
                    "--report-json",
                    str(path),
                )
            ),
            "artifact": str(_resolve(path)),
            "status": "available" if str(_resolve(path)) not in missing else "missing",
        }
        for label, path in eval_reports
    ]
    return {
        "meta": {
            "suite": "agent_governance_quality",
            "generated_at": _now_iso(),
            "root": str(REPO_ROOT),
        },
        "commands": commands,
        "artifacts": artifacts,
        "quality": quality,
        "summary": {
            "status": status,
            "reports": len(artifacts),
            "present_reports": len(artifacts) - len(missing),
            "missing_reports": len(missing),
            "missing_report_paths": missing,
            "failed_reports": failed,
            "quality_attention": quality_attention,
        },
    }


def write_governance_report(path: str | Path, **kwargs: Any) -> Path:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_governance_report(**kwargs)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument(
        "--eval-report",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="Eval JSON report to aggregate. Repeat to override defaults.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        eval_reports = [_split_eval_report(value) for value in args.eval_report] or DEFAULT_EVAL_REPORTS
        target = write_governance_report(args.report_json, eval_reports=eval_reports)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[agent-governance-report] {exc}", file=sys.stderr)
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
