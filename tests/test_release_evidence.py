from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts import release_evidence
from scripts._report_io import load_json, write_json_report


def _artifact_path(artifact: dict[str, object]) -> Path:
    assert artifact["exists"] is True
    assert isinstance(artifact["path"], str)
    assert artifact["sha256"]
    return Path(artifact["path"])


def _write_json(path: Path, payload: object) -> Path:
    return write_json_report(path, payload, ensure_ascii=True, indent=None, sort_keys=False)


def _read_report(path: str | Path) -> dict[str, Any]:
    report = load_json(path)
    assert isinstance(report, dict)
    return report


def _readyz(path: Path) -> Path:
    return _write_json(
        path,
        {
            "ready": True,
            "status": "ok",
            "checks": [{"name": "trajectory_recorder", "ready": True, "detail": ""}],
        },
    )


def _trajectory_stats(path: Path) -> Path:
    return _write_json(
        path,
        {
            "overview": {
                "turn_count": 40,
                "non_succeeded_count": 0,
                "total_tool_calls": 40,
                "total_fallback_uses": 0,
            }
        },
    )


def _replay(path: Path) -> Path:
    return _write_json(path, [{"case_id": "traj-1", "replay_passed": True}])


def _eval_report(path: Path) -> Path:
    return _write_json(
        path,
        {
            "summary": {"total": 2, "passed": 2, "failed": 0, "errors": 0},
            "comparison": {"regressions": []},
        },
    )


def _alert_report(path: Path) -> Path:
    return _write_json(
        path,
        {
            "alerts": [],
            "passed": True,
            "rules": [{"name": "runtime-ready", "query": "focus_agent_runtime_ready == 0"}],
            "status": "passed",
        },
    )


def _postgres_migration_report(path: Path) -> Path:
    return _write_json(
        path,
        {
            "command": "uv run python -m focus_agent.migrate_local_state --report-path reports/pg.json",
            "errors": [],
            "migrations": [{"name": "schema", "status": "verified"}],
            "passed": True,
            "status": "passed",
        },
    )


def _production_smoke_report(path: Path) -> Path:
    return _write_json(
        path,
        {
            "checks": [
                {"category": "api", "name": "api_readyz", "status": "passed", "passed": True},
                {
                    "category": "sdk",
                    "name": "sdk_client_healthz",
                    "status": "passed",
                    "passed": True,
                },
                {"category": "web", "name": "web_app", "status": "passed", "passed": True},
                {
                    "category": "graph",
                    "name": "graph_min_chat_turn",
                    "status": "passed",
                    "passed": True,
                },
                {
                    "category": "security",
                    "name": "security_wrong_jwt_denied",
                    "status": "passed",
                    "passed": True,
                },
                {
                    "category": "rate-limit",
                    "name": "rate_limit_probe",
                    "status": "passed",
                    "passed": True,
                },
            ],
            "passed": True,
            "status": "passed",
        },
    )


def _postgres_ops_report(path: Path) -> Path:
    operations = [
        {"name": "connectivity", "status": "passed", "passed": True},
        {"name": "backup_restore_runbook", "status": "passed", "passed": True},
    ]
    return _write_json(
        path,
        {
            "artifacts": [],
            "checks": operations,
            "command": "uv run python scripts/postgres_ops.py --dry-run",
            "errors": [],
            "operations": operations,
            "passed": True,
            "status": "passed",
        },
    )


def _otel_smoke_report(path: Path) -> Path:
    return _write_json(
        path,
        {
            "checks": [{"name": "span_export", "status": "passed", "passed": True}],
            "passed": True,
            "spans": [{"name": "focus_agent.release.otel_smoke"}],
            "status": "passed",
        },
    )


def _governance_report(path: Path) -> Path:
    return _write_json(
        path,
        {
            "summary": {"status": "passed", "blocking_signals": [], "warning_signals": []},
            "signals": [],
            "status": "passed",
            "thresholds": {},
        },
    )


def _source_dir(tmp_path: Path) -> Path:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    return source_dir


def _production_inputs(
    source_dir: Path,
    *,
    include_baseline: bool = True,
    include_optional_reports: bool = False,
) -> dict[str, object]:
    inputs: dict[str, object] = {
        "readyz_json": _readyz(source_dir / "readyz.json"),
        "trajectory_stats_json": _trajectory_stats(source_dir / "trajectory.json"),
        "replay_comparisons_json": _replay(source_dir / "replay.json"),
        "production_smoke_report_json": _production_smoke_report(
            source_dir / "production-smoke.json"
        ),
        "postgres_ops_report_json": _postgres_ops_report(source_dir / "postgres-ops.json"),
        "otel_smoke_report_json": _otel_smoke_report(source_dir / "otel-smoke.json"),
        "governance_report_json": _governance_report(source_dir / "governance.json"),
        "eval_report_json": [_eval_report(source_dir / "eval.json")],
    }
    if include_baseline:
        inputs["baseline_eval_report_json"] = [_eval_report(source_dir / "baseline.json")]
    if include_optional_reports:
        inputs["alert_report_json"] = _alert_report(source_dir / "alert.json")
        inputs["postgres_migration_report_json"] = _postgres_migration_report(
            source_dir / "postgres-migration.json"
        )
    return inputs


def test_release_evidence_dry_run_writes_manifest_and_artifacts(tmp_path: Path) -> None:
    manifest = release_evidence.run_release_evidence(
        release_id="dry-run-release",
        dry_run=True,
        output_root=tmp_path,
    )
    manifest_path = Path(manifest["manifest_json"])
    saved = _read_report(manifest_path)

    assert saved["summary"]["status"] == "passed"
    assert saved["meta"]["release_id"] == "dry-run-release"
    assert saved["meta"]["dry_run"] is True
    assert _artifact_path(saved["artifacts"]["readyz"]).exists()
    assert _artifact_path(saved["artifacts"]["trajectory_stats"]).exists()
    assert _artifact_path(saved["artifacts"]["replay_comparisons"]).exists()
    assert _artifact_path(saved["artifacts"]["eval_reports"][0]).exists()
    assert _artifact_path(saved["artifacts"]["baseline_eval_reports"][0]).exists()
    assert _artifact_path(saved["artifacts"]["alert_report"]).exists()
    assert _artifact_path(saved["artifacts"]["postgres_migration_report"]).exists()
    assert _artifact_path(saved["artifacts"]["production_smoke_report"]).exists()
    assert _artifact_path(saved["artifacts"]["postgres_ops_report"]).exists()
    assert _artifact_path(saved["artifacts"]["otel_smoke_report"]).exists()
    assert _artifact_path(saved["artifacts"]["governance_report"]).exists()
    assert _artifact_path(saved["artifacts"]["release_health_report"]).exists()
    assert saved["approval"]["approved"] is True
    assert saved["release_health"]["status"] == "passed"
    assert saved["commands"][0]["status"] == "passed"
    assert saved["artifact_summary"]["total"] == saved["summary"]["artifact_count"]
    assert saved["failure_summary"]["failed"] is False
    assert saved["meta"]["release_id_source"] == "explicit"
    assert saved["retention"]["days"] == 90
    assert saved["storage"]["enabled"] is False
    assert Path(saved["summary"]["summary_json"]).exists()


def test_release_evidence_manifest_records_github_actions_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv(
        "GITHUB_WORKFLOW_REF", "owner/repo/.github/workflows/release-gate.yml@refs/tags/v1"
    )
    monkeypatch.setenv("RELEASE_GATE_ARTIFACT_NAME", "release-gate-reports-12345-3")

    manifest = release_evidence.run_release_evidence(
        release_id="dry-run-gha",
        dry_run=True,
        output_root=tmp_path / "packs",
        storage_dir=tmp_path / "storage",
    )
    saved = _read_report(manifest["manifest_json"])

    assert saved["meta"]["ci"]["environment_name"] == "production"
    assert saved["meta"]["ci"]["run_attempt"] == "3"
    assert saved["meta"]["ci"]["run_id"] == "12345"
    assert (
        saved["meta"]["ci"]["workflow_ref"]
        == "owner/repo/.github/workflows/release-gate.yml@refs/tags/v1"
    )
    assert saved["artifact_storage"]["artifact_name"] == "release-gate-reports-12345-3"


def test_release_evidence_production_inputs_are_copied_and_gate_passes(tmp_path: Path) -> None:
    source_dir = _source_dir(tmp_path)
    manifest = release_evidence.run_release_evidence(
        release_id="prod-release",
        output_root=tmp_path / "packs",
        storage_dir=tmp_path / "storage",
        **_production_inputs(source_dir, include_optional_reports=True),
        approval_id="approval-1",
        approval_status="approved",
        approval_url="https://github.example/actions/runs/1",
    )
    saved = _read_report(manifest["manifest_json"])
    pack_dir = tmp_path / "packs" / "prod-release"

    assert saved["summary"]["status"] == "passed"
    assert saved["artifact_storage"]["enabled"] is True
    assert saved["artifact_storage"]["retention_days"] == 90
    assert saved["artifact_storage"]["stored_manifest_normalized_sha256"]
    assert saved["approval"]["approval_url"] == "https://github.example/actions/runs/1"
    assert saved["release_health"]["passed"] is True
    assert saved["production_validation"]["passed"] is True
    assert _artifact_path(saved["artifacts"]["readyz"]) == pack_dir / "inputs" / "readyz.json"
    assert (
        _artifact_path(saved["artifacts"]["trajectory_stats"])
        == pack_dir / "inputs" / "trajectory-stats.json"
    )
    assert (
        _artifact_path(saved["artifacts"]["replay_comparisons"])
        == pack_dir / "inputs" / "replay-comparisons.json"
    )
    assert (
        _artifact_path(saved["artifacts"]["alert_report"])
        == pack_dir / "inputs" / "alert-report.json"
    )
    assert (
        _artifact_path(saved["artifacts"]["postgres_migration_report"])
        == pack_dir / "inputs" / "postgres-migration-report.json"
    )
    assert (
        _artifact_path(saved["artifacts"]["production_smoke_report"])
        == pack_dir / "inputs" / "production-smoke-report.json"
    )
    assert (
        _artifact_path(saved["artifacts"]["postgres_ops_report"])
        == pack_dir / "inputs" / "postgres-ops-report.json"
    )
    assert (
        _artifact_path(saved["artifacts"]["otel_smoke_report"])
        == pack_dir / "inputs" / "otel-smoke-report.json"
    )
    assert (
        _artifact_path(saved["artifacts"]["governance_report"])
        == pack_dir / "inputs" / "governance-report.json"
    )
    assert (
        _artifact_path(saved["artifacts"]["eval_reports"][0])
        == pack_dir / "inputs" / "eval-report-1.json"
    )
    assert (
        _artifact_path(saved["artifacts"]["baseline_eval_reports"][0])
        == pack_dir / "inputs" / "baseline-eval-report-1.json"
    )


def test_release_evidence_missing_production_inputs_fails_closed(tmp_path: Path) -> None:
    manifest = release_evidence.run_release_evidence(
        release_id="missing-inputs",
        output_root=tmp_path,
    )
    saved = _read_report(manifest["manifest_json"])

    assert saved["summary"]["status"] == "failed"
    assert saved["commands"][0]["exit_code"] == 1
    assert saved["release_health"]["status"] == "failed"
    assert saved["production_validation"]["passed"] is False
    failed_keys = {signal["key"] for signal in saved["release_health"]["failed_signals"]}
    assert "release_health_required_input_missing" in failed_keys


def test_release_evidence_requires_baseline_eval_report_for_production_pack(tmp_path: Path) -> None:
    source_dir = _source_dir(tmp_path)
    manifest = release_evidence.run_release_evidence(
        release_id="missing-baseline",
        output_root=tmp_path / "packs",
        storage_dir=tmp_path / "storage",
        **_production_inputs(source_dir, include_baseline=False),
        approval_id="approval-1",
        approval_status="approved",
        approval_url="https://github.example/actions/runs/1",
    )
    saved = _read_report(manifest["manifest_json"])

    assert saved["summary"]["status"] == "failed"
    assert saved["summary"]["missing_required_artifacts"] == ["baseline_eval_reports"]
    assert saved["commands"][0]["status"] == "passed"
    assert saved["release_health"]["passed"] is True


def test_release_evidence_requires_approval_for_production_pack(tmp_path: Path) -> None:
    source_dir = _source_dir(tmp_path)
    manifest = release_evidence.run_release_evidence(
        release_id="missing-approval",
        output_root=tmp_path / "packs",
        **_production_inputs(source_dir),
    )
    saved = _read_report(manifest["manifest_json"])

    assert saved["summary"]["status"] == "failed"
    assert saved["approval"]["status"] == "missing"
    assert saved["production_validation"]["approval_approved"] is False
    assert "release_approval_missing" in {
        reason["kind"] for reason in saved["failure_summary"]["reasons"]
    }


def test_release_evidence_requires_release_id_for_production_pack(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--release-id is required"):
        release_evidence.run_release_evidence(output_root=tmp_path)


def test_release_evidence_writes_summary_and_copies_pack_to_storage(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("RELEASE_GATE_ARTIFACT_NAME", raising=False)

    source_dir = _source_dir(tmp_path)
    manifest = release_evidence.run_release_evidence(
        release_id="prod-release",
        output_root=tmp_path / "packs",
        retention_days=7,
        storage_dir=tmp_path / "storage",
        **_production_inputs(source_dir),
        approval_id="approval-1",
        approval_status="approved",
        approval_url="https://github.example/actions/runs/1",
    )
    saved = _read_report(manifest["manifest_json"])
    summary = _read_report(saved["summary"]["summary_json"])
    stored_pack_dir = Path(saved["storage"]["stored_pack_dir"])

    assert saved["summary"]["status"] == "passed"
    assert saved["retention"]["days"] == 7
    assert saved["storage"]["enabled"] is True
    assert saved["storage"]["status"] == "stored"
    assert saved["storage"]["verification"]["status"] == "verified"
    assert saved["artifact_storage"]["artifact_name"] is None
    assert saved["artifact_storage"]["retention"]["days"] == 7
    assert saved["artifact_storage"]["stored_manifest_normalized_sha256"]
    assert summary["release_id"] == "prod-release"
    assert summary["status"] == "passed"
    assert summary["artifact_storage"]["stored_manifest_normalized_sha256"]
    assert summary["approval"]["approved"] is True
    assert summary["artifact_summary"]["total"] == saved["artifact_summary"]["total"]
    assert stored_pack_dir.exists()
    assert (stored_pack_dir / "manifest.json").exists()
    assert (stored_pack_dir / "summary.json").exists()
