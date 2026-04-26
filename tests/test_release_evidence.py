from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import release_evidence


def _artifact_path(artifact: dict[str, object]) -> Path:
    assert artifact["exists"] is True
    assert isinstance(artifact["path"], str)
    assert artifact["sha256"]
    return Path(artifact["path"])


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def test_release_evidence_dry_run_writes_manifest_and_artifacts(tmp_path: Path) -> None:
    manifest = release_evidence.run_release_evidence(
        release_id="dry-run-release",
        dry_run=True,
        output_root=tmp_path,
    )
    manifest_path = Path(manifest["manifest_json"])
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))

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


def test_release_evidence_production_inputs_are_copied_and_gate_passes(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    manifest = release_evidence.run_release_evidence(
        release_id="prod-release",
        output_root=tmp_path / "packs",
        readyz_json=_readyz(source_dir / "readyz.json"),
        trajectory_stats_json=_trajectory_stats(source_dir / "trajectory.json"),
        replay_comparisons_json=_replay(source_dir / "replay.json"),
        alert_report_json=_alert_report(source_dir / "alert.json"),
        postgres_migration_report_json=_postgres_migration_report(source_dir / "postgres-migration.json"),
        eval_report_json=[_eval_report(source_dir / "eval.json")],
        baseline_eval_report_json=[_eval_report(source_dir / "baseline.json")],
        approval_id="approval-1",
        approval_status="approved",
    )
    saved = json.loads(Path(manifest["manifest_json"]).read_text(encoding="utf-8"))
    pack_dir = tmp_path / "packs" / "prod-release"

    assert saved["summary"]["status"] == "passed"
    assert saved["release_health"]["passed"] is True
    assert saved["production_validation"]["passed"] is True
    assert _artifact_path(saved["artifacts"]["readyz"]) == pack_dir / "inputs" / "readyz.json"
    assert _artifact_path(saved["artifacts"]["trajectory_stats"]) == pack_dir / "inputs" / "trajectory-stats.json"
    assert _artifact_path(saved["artifacts"]["replay_comparisons"]) == pack_dir / "inputs" / "replay-comparisons.json"
    assert _artifact_path(saved["artifacts"]["alert_report"]) == pack_dir / "inputs" / "alert-report.json"
    assert (
        _artifact_path(saved["artifacts"]["postgres_migration_report"])
        == pack_dir / "inputs" / "postgres-migration-report.json"
    )
    assert _artifact_path(saved["artifacts"]["eval_reports"][0]) == pack_dir / "inputs" / "eval-report-1.json"
    assert (
        _artifact_path(saved["artifacts"]["baseline_eval_reports"][0])
        == pack_dir / "inputs" / "baseline-eval-report-1.json"
    )


def test_release_evidence_missing_production_inputs_fails_closed(tmp_path: Path) -> None:
    manifest = release_evidence.run_release_evidence(
        release_id="missing-inputs",
        output_root=tmp_path,
    )
    saved = json.loads(Path(manifest["manifest_json"]).read_text(encoding="utf-8"))

    assert saved["summary"]["status"] == "failed"
    assert saved["commands"][0]["exit_code"] == 1
    assert saved["release_health"]["status"] == "failed"
    assert saved["production_validation"]["passed"] is False
    failed_keys = {signal["key"] for signal in saved["release_health"]["failed_signals"]}
    assert "release_health_required_input_missing" in failed_keys


def test_release_evidence_requires_baseline_eval_report_for_production_pack(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    manifest = release_evidence.run_release_evidence(
        release_id="missing-baseline",
        output_root=tmp_path / "packs",
        readyz_json=_readyz(source_dir / "readyz.json"),
        trajectory_stats_json=_trajectory_stats(source_dir / "trajectory.json"),
        replay_comparisons_json=_replay(source_dir / "replay.json"),
        eval_report_json=[_eval_report(source_dir / "eval.json")],
    )
    saved = json.loads(Path(manifest["manifest_json"]).read_text(encoding="utf-8"))

    assert saved["summary"]["status"] == "failed"
    assert saved["summary"]["missing_required_artifacts"] == ["baseline_eval_reports"]
    assert saved["commands"][0]["status"] == "passed"
    assert saved["release_health"]["passed"] is True


def test_release_evidence_requires_approval_for_production_pack(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    manifest = release_evidence.run_release_evidence(
        release_id="missing-approval",
        output_root=tmp_path / "packs",
        readyz_json=_readyz(source_dir / "readyz.json"),
        trajectory_stats_json=_trajectory_stats(source_dir / "trajectory.json"),
        replay_comparisons_json=_replay(source_dir / "replay.json"),
        eval_report_json=[_eval_report(source_dir / "eval.json")],
        baseline_eval_report_json=[_eval_report(source_dir / "baseline.json")],
    )
    saved = json.loads(Path(manifest["manifest_json"]).read_text(encoding="utf-8"))

    assert saved["summary"]["status"] == "failed"
    assert saved["approval"]["status"] == "missing"
    assert saved["production_validation"]["approval_approved"] is False
    assert "release_approval_missing" in {
        reason["kind"] for reason in saved["failure_summary"]["reasons"]
    }


def test_release_evidence_requires_release_id_for_production_pack(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--release-id is required"):
        release_evidence.run_release_evidence(output_root=tmp_path)


def test_release_evidence_writes_summary_and_copies_pack_to_storage(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    manifest = release_evidence.run_release_evidence(
        release_id="prod-release",
        output_root=tmp_path / "packs",
        retention_days=7,
        storage_dir=tmp_path / "storage",
        readyz_json=_readyz(source_dir / "readyz.json"),
        trajectory_stats_json=_trajectory_stats(source_dir / "trajectory.json"),
        replay_comparisons_json=_replay(source_dir / "replay.json"),
        eval_report_json=[_eval_report(source_dir / "eval.json")],
        baseline_eval_report_json=[_eval_report(source_dir / "baseline.json")],
        approval_id="approval-1",
        approval_status="approved",
    )
    saved = json.loads(Path(manifest["manifest_json"]).read_text(encoding="utf-8"))
    summary = json.loads(Path(saved["summary"]["summary_json"]).read_text(encoding="utf-8"))
    stored_pack_dir = Path(saved["storage"]["stored_pack_dir"])

    assert saved["summary"]["status"] == "passed"
    assert saved["retention"]["days"] == 7
    assert saved["storage"]["enabled"] is True
    assert saved["storage"]["status"] == "stored"
    assert saved["storage"]["verification"]["status"] == "verified"
    assert summary["release_id"] == "prod-release"
    assert summary["status"] == "passed"
    assert summary["approval"]["approved"] is True
    assert summary["artifact_summary"]["total"] == saved["artifact_summary"]["total"]
    assert stored_pack_dir.exists()
    assert (stored_pack_dir / "manifest.json").exists()
    assert (stored_pack_dir / "summary.json").exists()
