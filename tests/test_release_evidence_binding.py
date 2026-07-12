from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import release_evidence, release_evidence_capture
from scripts._report_io import load_json, write_json_report


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _write(path: Path, payload: object) -> Path:
    return write_json_report(path, payload, ensure_ascii=True, indent=None, sort_keys=True)


def _binding(
    commit_sha: str,
    *,
    deployment_id: str = "focus-agent-prod-a",
    deployment_version: str = "2026.07.12.1",
    environment: str = "production",
) -> dict[str, str]:
    return {
        "commit_sha": commit_sha,
        "deployment_id": deployment_id,
        "deployment_version": deployment_version,
        "environment": environment,
    }


def _report(
    payload: dict[str, Any],
    binding: dict[str, str],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        **payload,
        "generated_at": generated_at or _now(),
        "release_binding": binding,
    }


def _head(root: Path) -> str:
    return subprocess.check_output(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        text=True,
    ).strip()


def _production_inputs(
    source_dir: Path,
    binding: dict[str, str],
    *,
    stale_artifact: str | None = None,
    mismatched_artifact: str | None = None,
) -> dict[str, object]:
    source_dir.mkdir(parents=True)
    stale_timestamp = (datetime.now(UTC) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    def metadata(artifact: str) -> tuple[dict[str, str], str | None]:
        artifact_binding = dict(binding)
        if artifact == mismatched_artifact:
            artifact_binding["deployment_version"] = "wrong-version"
        return artifact_binding, stale_timestamp if artifact == stale_artifact else None

    readyz_binding, readyz_timestamp = metadata("readyz")
    readyz = _report(
        {
            "app_version": readyz_binding["deployment_version"],
            "checks": [{"detail": "", "name": "trajectory_recorder", "ready": True}],
            "deployment": readyz_binding["deployment_id"],
            "environment": readyz_binding["environment"],
            "ready": True,
            "status": "ok",
        },
        readyz_binding,
        generated_at=readyz_timestamp,
    )
    trajectory_binding, trajectory_timestamp = metadata("trajectory_stats")
    trajectory = _report(
        {
            "overview": {
                "non_succeeded_count": 0,
                "total_fallback_uses": 0,
                "total_tool_calls": 40,
                "turn_count": 40,
            }
        },
        trajectory_binding,
        generated_at=trajectory_timestamp,
    )
    replay_binding, replay_timestamp = metadata("replay_comparisons")
    replay = _report(
        {
            "comparisons": [
                {
                    "case_id": "release-binding-case",
                    "replay_passed": True,
                    "tool_path_changed": False,
                }
            ]
        },
        replay_binding,
        generated_at=replay_timestamp,
    )
    smoke_binding, smoke_timestamp = metadata("production_smoke_report")
    smoke_checks = [
        {"category": "api", "name": "api_readyz", "passed": True, "status": "passed"},
        {"category": "sdk", "name": "sdk_client_healthz", "passed": True, "status": "passed"},
        {"category": "web", "name": "web_app", "passed": True, "status": "passed"},
        {
            "category": "graph",
            "name": "graph_min_chat_turn",
            "passed": True,
            "status": "passed",
        },
        {
            "category": "security",
            "name": "security_wrong_jwt_denied",
            "passed": True,
            "status": "passed",
        },
        {
            "category": "rate-limit",
            "name": "rate_limit_probe",
            "passed": True,
            "status": "passed",
        },
    ]
    production_smoke = _report(
        {"checks": smoke_checks, "passed": True, "status": "passed"},
        smoke_binding,
        generated_at=smoke_timestamp,
    )
    postgres_binding, postgres_timestamp = metadata("postgres_ops_report")
    postgres_operations = [
        {"name": "connectivity", "passed": True, "status": "passed"},
        {"name": "backup_restore_runbook", "passed": True, "status": "passed"},
    ]
    postgres_ops = _report(
        {
            "artifacts": [],
            "checks": postgres_operations,
            "command": "uv run python scripts/postgres_ops.py --database-uri <redacted>",
            "errors": [],
            "operations": postgres_operations,
            "passed": True,
            "status": "passed",
        },
        postgres_binding,
        generated_at=postgres_timestamp,
    )
    otel_binding, otel_timestamp = metadata("otel_smoke_report")
    otel_smoke = _report(
        {
            "checks": [{"name": "span_export", "passed": True, "status": "passed"}],
            "passed": True,
            "spans": [{"name": "focus_agent.release.otel_smoke"}],
            "status": "passed",
        },
        otel_binding,
        generated_at=otel_timestamp,
    )
    governance_binding, governance_timestamp = metadata("governance_report")
    governance = _report(
        {
            "signals": [],
            "status": "passed",
            "summary": {"blocking_signals": [], "status": "passed", "warning_signals": []},
            "thresholds": {},
        },
        governance_binding,
        generated_at=governance_timestamp,
    )
    eval_binding, eval_timestamp = metadata("eval_reports[0]")
    eval_report = _report(
        {
            "comparison": {"regressions": []},
            "summary": {"errors": 0, "failed": 0, "passed": 2, "total": 2},
        },
        eval_binding,
        generated_at=eval_timestamp,
    )
    baseline_binding, baseline_timestamp = metadata("baseline_eval_reports[0]")
    baseline = _report(
        {
            "comparison": {"regressions": []},
            "summary": {"errors": 0, "failed": 0, "passed": 2, "total": 2},
        },
        baseline_binding,
        generated_at=baseline_timestamp,
    )
    return {
        "baseline_eval_report_json": [_write(source_dir / "baseline.json", baseline)],
        "eval_report_json": [_write(source_dir / "eval.json", eval_report)],
        "governance_report_json": _write(source_dir / "governance.json", governance),
        "otel_smoke_report_json": _write(source_dir / "otel-smoke.json", otel_smoke),
        "postgres_ops_report_json": _write(source_dir / "postgres-ops.json", postgres_ops),
        "production_smoke_report_json": _write(
            source_dir / "production-smoke.json", production_smoke
        ),
        "readyz_json": _write(source_dir / "readyz.json", readyz),
        "replay_comparisons_json": _write(source_dir / "replay.json", replay),
        "trajectory_stats_json": _write(source_dir / "trajectory.json", trajectory),
    }


def _run_production(
    tmp_path: Path,
    *,
    binding: dict[str, str],
    commit_sha: str | None = None,
    max_evidence_age_seconds: int = 3600,
    stale_artifact: str | None = None,
    mismatched_artifact: str | None = None,
) -> dict[str, Any]:
    manifest = release_evidence.run_release_evidence(
        release_id="bound-production-release",
        commit_sha=commit_sha if commit_sha is not None else binding["commit_sha"],
        deployment_id=binding["deployment_id"],
        deployment_version=binding["deployment_version"],
        environment=binding["environment"],
        max_evidence_age_seconds=max_evidence_age_seconds,
        output_root=tmp_path / "packs",
        storage_dir=tmp_path / "storage",
        approval_id="approval-1",
        approval_status="approved",
        approval_url="https://github.example/actions/runs/1",
        **_production_inputs(
            tmp_path / "sources",
            binding,
            stale_artifact=stale_artifact,
            mismatched_artifact=mismatched_artifact,
        ),
    )
    payload = load_json(manifest["manifest_json"])
    assert isinstance(payload, dict)
    return payload


def test_production_evidence_binds_current_release_identity_and_fresh_inputs(
    tmp_path: Path,
) -> None:
    binding = _binding(_head(Path.cwd()))

    manifest = _run_production(tmp_path, binding=binding)

    assert manifest["summary"]["status"] == "passed"
    assert manifest["meta"]["schema_version"] == 2
    assert manifest["release_binding"]["commit_sha"] == binding["commit_sha"]
    assert manifest["release_binding"]["deployment_id"] == binding["deployment_id"]
    assert manifest["release_binding"]["deployment_version"] == binding["deployment_version"]
    assert manifest["release_binding"]["environment"] == "production"
    assert manifest["release_binding"]["status"] == "passed"
    assert manifest["evidence_validation"]["passed"] is True
    assert manifest["production_validation"]["release_binding_passed"] is True
    assert manifest["production_validation"]["evidence_inputs_passed"] is True
    assert all(
        record["status"] == "passed"
        for record in manifest["evidence_validation"]["artifact_records"]
        if record["required"]
    )


def test_trusted_capture_outputs_pass_schema_v2_evidence_pack(tmp_path: Path) -> None:
    binding = _binding(_head(Path.cwd()))
    inputs = _production_inputs(tmp_path / "sources", binding)
    env = {
        "RELEASE_COMMIT_SHA": binding["commit_sha"],
        "RELEASE_DEPLOYMENT_ID": binding["deployment_id"],
        "RELEASE_DEPLOYMENT_VERSION": binding["deployment_version"],
        "RELEASE_ENVIRONMENT": binding["environment"],
    }
    raw_inputs = (
        (inputs["readyz_json"], True, True),
        (inputs["trajectory_stats_json"], True, False),
        (inputs["replay_comparisons_json"], False, False),
        (inputs["baseline_eval_report_json"][0], False, False),
    )
    for raw_path, captured_now, readyz in raw_inputs:
        assert isinstance(raw_path, Path)
        payload = load_json(raw_path)
        assert isinstance(payload, dict)
        payload.pop("release_binding")
        if captured_now:
            payload.pop("generated_at")
        write_json_report(raw_path, payload)
        release_evidence_capture.capture_json_files(
            [raw_path],
            in_place=True,
            readyz_paths=[raw_path] if readyz else (),
            captured_now=captured_now,
            env=env,
        )

    manifest = release_evidence.run_release_evidence(
        release_id="trusted-capture-production-release",
        commit_sha=binding["commit_sha"],
        deployment_id=binding["deployment_id"],
        deployment_version=binding["deployment_version"],
        environment=binding["environment"],
        output_root=tmp_path / "packs",
        storage_dir=tmp_path / "storage",
        approval_id="approval-1",
        approval_status="approved",
        approval_url="https://github.example/actions/runs/1",
        **inputs,
    )
    saved = load_json(manifest["manifest_json"])
    assert isinstance(saved, dict)
    assert saved["meta"]["schema_version"] == 2
    assert saved["summary"]["status"] == "passed"
    assert saved["release_binding"]["status"] == "passed"
    assert saved["evidence_validation"]["passed"] is True


def test_production_evidence_rejects_wrong_deployment_version_in_input(
    tmp_path: Path,
) -> None:
    binding = _binding(_head(Path.cwd()))

    manifest = _run_production(
        tmp_path,
        binding=binding,
        mismatched_artifact="production_smoke_report",
    )

    assert manifest["summary"]["status"] == "failed"
    errors = manifest["evidence_validation"]["errors"]
    assert any(
        error["code"] == "evidence_input_binding_mismatch"
        and error["field"] == "deployment_version"
        for error in errors
    )
    assert "evidence_inputs_invalid" in {
        reason["kind"] for reason in manifest["failure_summary"]["reasons"]
    }


def test_production_evidence_rejects_input_without_binding_or_timestamp(
    tmp_path: Path,
) -> None:
    binding = _binding(_head(Path.cwd()))
    inputs = _production_inputs(tmp_path / "sources", binding)
    trajectory_path = inputs["trajectory_stats_json"]
    assert isinstance(trajectory_path, Path)
    payload = load_json(trajectory_path)
    assert isinstance(payload, dict)
    payload.pop("generated_at")
    payload.pop("release_binding")
    _write(trajectory_path, payload)

    manifest = release_evidence.run_release_evidence(
        release_id="unbound-input-release",
        commit_sha=binding["commit_sha"],
        deployment_id=binding["deployment_id"],
        deployment_version=binding["deployment_version"],
        environment=binding["environment"],
        output_root=tmp_path / "packs",
        storage_dir=tmp_path / "storage",
        approval_id="approval-1",
        approval_status="approved",
        approval_url="https://github.example/actions/runs/1",
        **inputs,
    )
    saved = load_json(manifest["manifest_json"])
    assert isinstance(saved, dict)

    codes = {error["code"] for error in saved["evidence_validation"]["errors"]}
    assert saved["summary"]["status"] == "failed"
    assert "evidence_input_binding_missing" in codes
    assert "evidence_input_timestamp_missing" in codes


def test_production_evidence_rejects_commit_other_than_checked_out_head(
    tmp_path: Path,
) -> None:
    root = Path.cwd()
    parent = subprocess.check_output(
        ("git", "rev-parse", "HEAD^"),
        cwd=root,
        text=True,
    ).strip()
    if not parent:
        pytest.skip("repository has no parent commit")
    binding = _binding(parent)

    manifest = _run_production(tmp_path, binding=binding, commit_sha=parent)

    assert manifest["summary"]["status"] == "failed"
    assert manifest["release_binding"]["status"] == "failed"
    assert any(
        error["code"] == "release_commit_not_current"
        for error in manifest["evidence_validation"]["errors"]
    )
    assert "release_binding_invalid" in {
        reason["kind"] for reason in manifest["failure_summary"]["reasons"]
    }


def test_production_evidence_rejects_symbolic_commit_reference(tmp_path: Path) -> None:
    binding = _binding(_head(Path.cwd()))

    manifest = _run_production(tmp_path, binding=binding, commit_sha="HEAD")

    assert manifest["summary"]["status"] == "failed"
    assert any(
        error["code"] == "release_commit_invalid"
        for error in manifest["evidence_validation"]["errors"]
    )


def test_production_evidence_rejects_stale_required_input(tmp_path: Path) -> None:
    binding = _binding(_head(Path.cwd()))

    manifest = _run_production(
        tmp_path,
        binding=binding,
        max_evidence_age_seconds=300,
        stale_artifact="otel_smoke_report",
    )

    assert manifest["summary"]["status"] == "failed"
    stale = [
        error
        for error in manifest["evidence_validation"]["errors"]
        if error["code"] == "evidence_input_stale"
    ]
    assert stale
    assert stale[0]["field"] == "otel_smoke_report"
    assert stale[0]["max_age_seconds"] == 300


def test_production_evidence_requires_all_explicit_binding_fields(tmp_path: Path) -> None:
    binding = _binding(_head(Path.cwd()))
    manifest = release_evidence.run_release_evidence(
        release_id="missing-production-binding",
        output_root=tmp_path / "packs",
        **_production_inputs(tmp_path / "sources", binding),
    )
    payload = load_json(manifest["manifest_json"])
    assert isinstance(payload, dict)

    assert payload["summary"]["status"] == "failed"
    missing_fields = {
        error["field"]
        for error in payload["evidence_validation"]["errors"]
        if error["code"] == "release_binding_missing"
    }
    assert missing_fields == {
        "commit_sha",
        "deployment_id",
        "deployment_version",
        "environment",
    }


def test_production_evidence_rejects_non_production_environment(tmp_path: Path) -> None:
    binding = _binding(_head(Path.cwd()), environment="staging")

    manifest = _run_production(tmp_path, binding=binding)

    assert manifest["summary"]["status"] == "failed"
    assert any(
        error["code"] == "release_environment_invalid"
        for error in manifest["evidence_validation"]["errors"]
    )


def test_dry_run_uses_deterministic_sample_binding_without_production_inputs(
    tmp_path: Path,
) -> None:
    manifest = release_evidence.run_release_evidence(
        dry_run=True,
        release_id="dry-run-binding",
        output_root=tmp_path,
    )
    payload = load_json(manifest["manifest_json"])
    assert isinstance(payload, dict)

    assert payload["summary"]["status"] == "passed"
    assert payload["release_binding"] == {
        "commit_sha": "dry-run-commit",
        "deployment_id": "dry-run-deployment",
        "deployment_version": "dry-run-version",
        "environment": "dry-run",
        "release_id": "dry-run-binding",
        "required": False,
        "sources": {"mode": "deterministic_sample"},
        "status": "sample",
    }
    assert payload["evidence_validation"]["status"] == "sample"


def test_production_evidence_accepts_standard_ci_and_deployment_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path.cwd()
    binding = _binding(_head(root))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", binding["commit_sha"])
    monkeypatch.setenv("ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("RELEASE_DEPLOYMENT_ID", binding["deployment_id"])
    monkeypatch.setenv("RELEASE_DEPLOYMENT_VERSION", binding["deployment_version"])

    manifest = release_evidence.run_release_evidence(
        release_id="environment-bound-release",
        output_root=tmp_path / "packs",
        storage_dir=tmp_path / "storage",
        approval_id="approval-1",
        approval_status="approved",
        approval_url="https://github.example/actions/runs/1",
        **_production_inputs(tmp_path / "sources", binding),
    )
    payload = load_json(manifest["manifest_json"])
    assert isinstance(payload, dict)

    assert payload["summary"]["status"] == "passed"
    assert payload["release_binding"]["sources"] == {
        "commit_sha": "ci.commit_sha",
        "deployment_id": "RELEASE_DEPLOYMENT_ID",
        "deployment_version": "RELEASE_DEPLOYMENT_VERSION",
        "environment": "ci.environment_name",
    }
