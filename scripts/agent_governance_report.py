#!/usr/bin/env python3
"""Build the Agent Governance quality report."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class GovernanceThresholds:
    delegation_success_warn: float = 0.98
    delegation_success_block: float = 0.95
    critic_precision_warn: float = 0.9
    critic_precision_block: float = 0.85
    critic_recall_warn: float = 0.9
    critic_recall_block: float = 0.85
    review_queue_backlog_warn: int = 5
    review_queue_backlog_block: int = 10
    avg_cost_usd_warn: float = 0.03
    avg_cost_usd_block: float = 0.05
    avg_input_tokens_warn: float = 6000.0
    avg_input_tokens_block: float = 8000.0
    avg_output_tokens_warn: float = 3000.0
    avg_output_tokens_block: float = 4000.0
    avg_tool_calls_warn: float = 4.0
    avg_tool_calls_block: float = 6.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "delegation_success": {
                "warning_min": self.delegation_success_warn,
                "blocking_min": self.delegation_success_block,
            },
            "critic_precision": {
                "warning_min": self.critic_precision_warn,
                "blocking_min": self.critic_precision_block,
            },
            "critic_recall": {
                "warning_min": self.critic_recall_warn,
                "blocking_min": self.critic_recall_block,
            },
            "review_queue_backlog": {
                "warning_max": self.review_queue_backlog_warn,
                "blocking_max": self.review_queue_backlog_block,
            },
            "budget": {
                "avg_cost_usd": {
                    "warning_max": self.avg_cost_usd_warn,
                    "blocking_max": self.avg_cost_usd_block,
                },
                "avg_input_tokens": {
                    "warning_max": self.avg_input_tokens_warn,
                    "blocking_max": self.avg_input_tokens_block,
                },
                "avg_output_tokens": {
                    "warning_max": self.avg_output_tokens_warn,
                    "blocking_max": self.avg_output_tokens_block,
                },
                "avg_tool_calls": {
                    "warning_max": self.avg_tool_calls_warn,
                    "blocking_max": self.avg_tool_calls_block,
                },
            },
        }


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


def _governance_threshold_signals(
    artifacts: Sequence[dict[str, Any]],
    quality: dict[str, dict[str, Any]],
    *,
    thresholds: GovernanceThresholds,
) -> list[dict[str, Any]]:
    critic = _critic_metrics(artifacts, quality)
    return [
        _min_threshold_signal(
            key="delegation_success",
            summary="delegation success rate",
            value=None
            if quality["delegation"].get("status") == "missing"
            else _optional_float(quality["delegation"].get("task_success")),
            warning_threshold=thresholds.delegation_success_warn,
            blocking_threshold=thresholds.delegation_success_block,
            unit="ratio",
        ),
        _min_threshold_signal(
            key="critic_precision",
            summary="critic precision or proxy success",
            value=critic["precision"],
            warning_threshold=thresholds.critic_precision_warn,
            blocking_threshold=thresholds.critic_precision_block,
            unit="ratio",
            details={"source": critic["source"]},
        ),
        _min_threshold_signal(
            key="critic_recall",
            summary="critic recall or proxy success",
            value=critic["recall"],
            warning_threshold=thresholds.critic_recall_warn,
            blocking_threshold=thresholds.critic_recall_block,
            unit="ratio",
            details={"source": critic["source"]},
        ),
        _max_threshold_signal(
            key="review_queue_backlog",
            summary="review queue backlog",
            value=_review_queue_backlog(artifacts),
            warning_threshold=float(thresholds.review_queue_backlog_warn),
            blocking_threshold=float(thresholds.review_queue_backlog_block),
            unit="items",
        ),
        _budget_signal(quality["cost"], thresholds=thresholds),
    ]


def _critic_metrics(
    artifacts: Sequence[dict[str, Any]],
    quality: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    precision = _average_summary_metric(artifacts, ("critic_precision", "critic_proxy_precision"))
    recall = _average_summary_metric(artifacts, ("critic_recall", "critic_proxy_recall"))
    if precision is not None and recall is not None:
        return {"precision": precision, "recall": recall, "source": "summary"}
    proxy = (
        None
        if quality["critic"].get("status") == "missing"
        else _optional_float(quality["critic"].get("task_success"))
    )
    return {
        "precision": precision if precision is not None else proxy,
        "recall": recall if recall is not None else proxy,
        "source": "per_tag_success_proxy" if proxy is not None else "missing",
    }


def _average_summary_metric(
    artifacts: Sequence[dict[str, Any]],
    names: Sequence[str],
) -> float | None:
    values: list[float] = []
    for artifact in artifacts:
        summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
        for name in names:
            if name in summary:
                values.append(float(summary.get(name) or 0.0))
                break
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _review_queue_backlog(artifacts: Sequence[dict[str, Any]]) -> float:
    metric_names = (
        "review_queue_backlog",
        "agent_review_queue_backlog",
        "pending_review_queue",
        "pending_review_items",
        "review_backlog",
    )
    values: list[float] = []
    for artifact in artifacts:
        summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
        for name in metric_names:
            if name in summary:
                values.append(float(summary.get(name) or 0.0))
                break
    return max(values) if values else 0.0


def _min_threshold_signal(
    *,
    key: str,
    summary: str,
    value: float | None,
    warning_threshold: float,
    blocking_threshold: float,
    unit: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _base_signal(
        key=key,
        summary=summary,
        value=value,
        warning_threshold=warning_threshold,
        blocking_threshold=blocking_threshold,
        unit=unit,
        direction="min",
        details=details,
    )
    if value is None:
        return {**payload, "status": "warn", "severity": "warning", "reason": "metric missing"}
    if value < blocking_threshold:
        return {**payload, "status": "block", "severity": "blocking", "reason": "below blocking minimum"}
    if value < warning_threshold:
        return {**payload, "status": "warn", "severity": "warning", "reason": "below warning minimum"}
    return {**payload, "status": "pass", "severity": "none", "reason": "within threshold"}


def _max_threshold_signal(
    *,
    key: str,
    summary: str,
    value: float | None,
    warning_threshold: float,
    blocking_threshold: float,
    unit: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _base_signal(
        key=key,
        summary=summary,
        value=value,
        warning_threshold=warning_threshold,
        blocking_threshold=blocking_threshold,
        unit=unit,
        direction="max",
        details=details,
    )
    if value is None:
        return {**payload, "status": "warn", "severity": "warning", "reason": "metric missing"}
    if value > blocking_threshold:
        return {**payload, "status": "block", "severity": "blocking", "reason": "above blocking maximum"}
    if value > warning_threshold:
        return {**payload, "status": "warn", "severity": "warning", "reason": "above warning maximum"}
    return {**payload, "status": "pass", "severity": "none", "reason": "within threshold"}


def _base_signal(
    *,
    key: str,
    summary: str,
    value: float | None,
    warning_threshold: float,
    blocking_threshold: float,
    unit: str,
    direction: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "summary": summary,
        "value": value,
        "unit": unit,
        "direction": direction,
        "thresholds": {
            "warning": warning_threshold,
            "blocking": blocking_threshold,
        },
        "details": details or {},
    }


def _budget_signal(cost: dict[str, Any], *, thresholds: GovernanceThresholds) -> dict[str, Any]:
    budget_thresholds = {
        "avg_cost_usd": (thresholds.avg_cost_usd_warn, thresholds.avg_cost_usd_block, "usd"),
        "avg_input_tokens": (thresholds.avg_input_tokens_warn, thresholds.avg_input_tokens_block, "tokens"),
        "avg_output_tokens": (thresholds.avg_output_tokens_warn, thresholds.avg_output_tokens_block, "tokens"),
        "avg_tool_calls": (thresholds.avg_tool_calls_warn, thresholds.avg_tool_calls_block, "calls"),
    }
    checks: list[dict[str, Any]] = []
    has_blocking = False
    has_warning = False
    for metric, (warn_threshold, block_threshold, unit) in budget_thresholds.items():
        value = None if cost.get("status") == "missing" else _optional_float(cost.get(metric))
        signal = _max_threshold_signal(
            key=metric,
            summary=f"{metric} budget",
            value=value,
            warning_threshold=warn_threshold,
            blocking_threshold=block_threshold,
            unit=unit,
        )
        checks.append(signal)
        has_blocking = has_blocking or signal["status"] == "block"
        has_warning = has_warning or signal["status"] == "warn"
    status = "block" if has_blocking else "warn" if has_warning else "pass"
    return {
        "key": "cost_token_tool_budget",
        "summary": "cost, token, and tool-call budget",
        "status": status,
        "severity": "blocking" if has_blocking else "warning" if has_warning else "none",
        "reason": "budget violation" if has_blocking else "budget warning" if has_warning else "within threshold",
        "details": {"checks": checks},
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_governance_report(
    *,
    eval_reports: Sequence[tuple[str, str | Path]] = DEFAULT_EVAL_REPORTS,
    thresholds: GovernanceThresholds | None = None,
) -> dict[str, Any]:
    policy = thresholds or GovernanceThresholds()
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
    threshold_signals = _governance_threshold_signals(artifacts, quality, thresholds=policy)
    blocking_signals = [
        signal["key"] for signal in threshold_signals if signal.get("status") == "block"
    ]
    warning_signals = [
        signal["key"] for signal in threshold_signals if signal.get("status") == "warn"
    ]
    status = "failed" if failed or blocking_signals else "incomplete" if missing else "passed"
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
        "thresholds": policy.to_dict(),
        "signals": threshold_signals,
        "summary": {
            "status": status,
            "reports": len(artifacts),
            "present_reports": len(artifacts) - len(missing),
            "missing_reports": len(missing),
            "missing_report_paths": missing,
            "failed_reports": failed,
            "quality_attention": quality_attention,
            "blocking_signals": blocking_signals,
            "warning_signals": warning_signals,
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
    parser.add_argument("--min-delegation-success", type=float)
    parser.add_argument("--min-critic-precision", type=float)
    parser.add_argument("--min-critic-recall", type=float)
    parser.add_argument("--max-review-queue-backlog", type=int)
    parser.add_argument("--max-avg-cost-usd", type=float)
    parser.add_argument("--max-avg-input-tokens", type=float)
    parser.add_argument("--max-avg-output-tokens", type=float)
    parser.add_argument("--max-avg-tool-calls", type=float)
    return parser.parse_args(argv)


def _thresholds_from_args(args: argparse.Namespace) -> GovernanceThresholds:
    defaults = GovernanceThresholds()
    delegation_block = args.min_delegation_success
    critic_precision_block = args.min_critic_precision
    critic_recall_block = args.min_critic_recall
    backlog_block = args.max_review_queue_backlog
    cost_block = args.max_avg_cost_usd
    input_block = args.max_avg_input_tokens
    output_block = args.max_avg_output_tokens
    tool_block = args.max_avg_tool_calls
    return GovernanceThresholds(
        delegation_success_block=delegation_block
        if delegation_block is not None
        else defaults.delegation_success_block,
        delegation_success_warn=max(
            defaults.delegation_success_warn,
            delegation_block if delegation_block is not None else defaults.delegation_success_warn,
        ),
        critic_precision_block=critic_precision_block
        if critic_precision_block is not None
        else defaults.critic_precision_block,
        critic_precision_warn=max(
            defaults.critic_precision_warn,
            critic_precision_block if critic_precision_block is not None else defaults.critic_precision_warn,
        ),
        critic_recall_block=critic_recall_block
        if critic_recall_block is not None
        else defaults.critic_recall_block,
        critic_recall_warn=max(
            defaults.critic_recall_warn,
            critic_recall_block if critic_recall_block is not None else defaults.critic_recall_warn,
        ),
        review_queue_backlog_block=backlog_block
        if backlog_block is not None
        else defaults.review_queue_backlog_block,
        review_queue_backlog_warn=min(
            defaults.review_queue_backlog_warn,
            backlog_block if backlog_block is not None else defaults.review_queue_backlog_warn,
        ),
        avg_cost_usd_block=cost_block if cost_block is not None else defaults.avg_cost_usd_block,
        avg_cost_usd_warn=min(
            defaults.avg_cost_usd_warn,
            cost_block if cost_block is not None else defaults.avg_cost_usd_warn,
        ),
        avg_input_tokens_block=input_block
        if input_block is not None
        else defaults.avg_input_tokens_block,
        avg_input_tokens_warn=min(
            defaults.avg_input_tokens_warn,
            input_block if input_block is not None else defaults.avg_input_tokens_warn,
        ),
        avg_output_tokens_block=output_block
        if output_block is not None
        else defaults.avg_output_tokens_block,
        avg_output_tokens_warn=min(
            defaults.avg_output_tokens_warn,
            output_block if output_block is not None else defaults.avg_output_tokens_warn,
        ),
        avg_tool_calls_block=tool_block
        if tool_block is not None
        else defaults.avg_tool_calls_block,
        avg_tool_calls_warn=min(
            defaults.avg_tool_calls_warn,
            tool_block if tool_block is not None else defaults.avg_tool_calls_warn,
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        eval_reports = [_split_eval_report(value) for value in args.eval_report] or DEFAULT_EVAL_REPORTS
        target = write_governance_report(
            args.report_json,
            eval_reports=eval_reports,
            thresholds=_thresholds_from_args(args),
        )
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
