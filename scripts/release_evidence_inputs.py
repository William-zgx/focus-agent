"""Input builders for release evidence reports."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

EvidenceInputFactory = Callable[[str, Path | None, Path | None, bool, str], Any]
JsonWriter = Callable[[Path, object], Path]


def _sample_readyz() -> dict[str, Any]:
    return {
        "checks": [{"detail": "dry-run sample", "name": "trajectory_recorder", "ready": True}],
        "ready": True,
        "status": "ok",
    }


def _sample_trajectory_stats() -> dict[str, Any]:
    return {
        "overview": {
            "non_succeeded_count": 0,
            "total_fallback_uses": 0,
            "total_tool_calls": 40,
            "turn_count": 40,
        }
    }


def _sample_replay_comparisons() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "dry-run-trajectory",
            "replay_passed": True,
            "tool_path_changed": False,
        }
    ]


def _sample_eval_report() -> dict[str, Any]:
    return {
        "comparison": {"regressions": []},
        "results": [],
        "summary": {
            "avg_cost_usd": 0.01,
            "avg_input_tokens": 1200,
            "avg_llm_calls": 1,
            "avg_output_tokens": 240,
            "avg_tool_calls": 2,
            "errors": 0,
            "failed": 0,
            "forbidden_tool_violation_rate": 0.0,
            "passed": 2,
            "p95_latency_ms": 800,
            "task_success": 1.0,
            "total": 2,
        },
    }


def _sample_alert_report() -> dict[str, Any]:
    return {
        "alerts": [],
        "passed": True,
        "rules": [
            {"name": "focus_agent_runtime_ready", "query": "focus_agent_runtime_ready == 0"},
            {
                "name": "focus_agent_trajectory_recorder_ready",
                "query": 'focus_agent_runtime_component_ready{component="trajectory_recorder"} == 0',
            },
        ],
        "status": "passed",
        "summary": {"rules_checked": 2},
    }


def _sample_postgres_migration_report() -> dict[str, Any]:
    return {
        "command": (
            "uv run python -m focus_agent.migrate_local_state --database-uri "
            "<postgres-uri> --artifact-scan --report-path reports/release-gate/postgres-migration.json"
        ),
        "errors": [],
        "migrations": [{"name": "schema_migrations", "status": "verified"}],
        "passed": True,
        "status": "passed",
    }


def _sample_production_smoke_report() -> dict[str, Any]:
    return {
        "checks": [
            {"category": "api", "name": "api_readyz", "status": "dry-run"},
            {"category": "sdk", "name": "sdk_client_healthz", "status": "dry-run"},
            {"category": "web", "name": "web_app", "status": "dry-run"},
            {"category": "graph", "name": "graph_min_chat_turn", "status": "dry-run"},
            {"category": "security", "name": "security_wrong_jwt_denied", "status": "dry-run"},
            {"category": "rate-limit", "name": "rate_limit_probe", "status": "dry-run"},
        ],
        "passed": True,
        "report_type": "production_smoke",
        "status": "dry-run",
        "summary": {"failed": 0, "passed": 6, "total": 6},
    }


def _sample_postgres_ops_report() -> dict[str, Any]:
    checks = [
        {"name": "connectivity", "status": "dry-run"},
        {"name": "migration_table", "status": "dry-run"},
        {"name": "backup_restore_runbook", "status": "dry-run"},
    ]
    return {
        "artifacts": [],
        "checks": checks,
        "command": "uv run python scripts/postgres_ops.py --dry-run",
        "errors": [],
        "operations": checks,
        "passed": True,
        "report_type": "postgres_ops",
        "status": "dry-run",
        "summary": {"failed": 0, "passed": len(checks), "total": len(checks)},
    }


def _sample_otel_smoke_report() -> dict[str, Any]:
    return {
        "checks": [{"name": "span_export", "status": "dry-run"}],
        "passed": True,
        "report_type": "otel_smoke",
        "spans": [{"name": "focus_agent.release.otel_smoke", "status": "dry-run"}],
        "status": "dry-run",
        "summary": {"failed": 0, "passed": 1, "spans": 1, "total": 1},
    }


def _sample_governance_report() -> dict[str, Any]:
    return {
        "report_type": "agent_governance_quality",
        "signals": [],
        "status": "passed",
        "summary": {
            "blocking_signals": [],
            "status": "passed",
            "warning_signals": [],
        },
        "thresholds": {},
    }


def prepare_dry_run_inputs(
    pack_dir: Path,
    *,
    evidence_input: EvidenceInputFactory,
    write_json: JsonWriter,
) -> dict[str, list[Any] | Any]:
    inputs_dir = pack_dir / "inputs"
    readyz = write_json(inputs_dir / "readyz.json", _sample_readyz())
    trajectory_stats = write_json(inputs_dir / "trajectory-stats.json", _sample_trajectory_stats())
    replay_comparisons = write_json(
        inputs_dir / "replay-comparisons.json", _sample_replay_comparisons()
    )
    eval_report = write_json(inputs_dir / "eval-sample.json", _sample_eval_report())
    baseline_eval_report = write_json(
        inputs_dir / "baseline-eval-sample.json", _sample_eval_report()
    )
    alert_report = write_json(inputs_dir / "alert-report.json", _sample_alert_report())
    postgres_migration_report = write_json(
        inputs_dir / "postgres-migration-report.json",
        _sample_postgres_migration_report(),
    )
    production_smoke_report = write_json(
        inputs_dir / "production-smoke-report.json",
        _sample_production_smoke_report(),
    )
    postgres_ops_report = write_json(
        inputs_dir / "postgres-ops-report.json", _sample_postgres_ops_report()
    )
    otel_smoke_report = write_json(
        inputs_dir / "otel-smoke-report.json", _sample_otel_smoke_report()
    )
    governance_report = write_json(
        inputs_dir / "governance-report.json", _sample_governance_report()
    )
    return {
        "alert_report": evidence_input("alert_report", alert_report, None, False, "generated"),
        "production_smoke_report": evidence_input(
            "production_smoke_report",
            production_smoke_report,
            None,
            True,
            "generated",
        ),
        "postgres_ops_report": evidence_input(
            "postgres_ops_report", postgres_ops_report, None, True, "generated"
        ),
        "otel_smoke_report": evidence_input(
            "otel_smoke_report", otel_smoke_report, None, True, "generated"
        ),
        "governance_report": evidence_input(
            "governance_report", governance_report, None, True, "generated"
        ),
        "readyz": evidence_input("readyz", readyz, None, True, "generated"),
        "trajectory_stats": evidence_input(
            "trajectory_stats", trajectory_stats, None, True, "generated"
        ),
        "replay_comparisons": evidence_input(
            "replay_comparisons", replay_comparisons, None, True, "generated"
        ),
        "eval_reports": [evidence_input("eval_report", eval_report, None, True, "generated")],
        "baseline_eval_reports": [
            evidence_input("baseline_eval_report", baseline_eval_report, None, True, "generated")
        ],
        "postgres_migration_report": evidence_input(
            "postgres_migration_report",
            postgres_migration_report,
            None,
            False,
            "generated",
        ),
    }
