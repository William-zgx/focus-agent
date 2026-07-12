from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from scripts import agent_governance_report, otel_smoke, postgres_ops, production_smoke
from tests.eval import reporting as eval_reporting
from tests.eval.metrics import MetricSummary

RELEASE_ENV_VARS = (
    "RELEASE_COMMIT_SHA",
    "RELEASE_DEPLOYMENT_ID",
    "RELEASE_DEPLOYMENT_VERSION",
    "RELEASE_ENVIRONMENT",
)
FIXED_GENERATED_AT = "2026-07-12T08:30:00Z"
EXPECTED_BINDING = {
    "commit_sha": "0123456789abcdef0123456789abcdef01234567",
    "deployment_id": "focus-agent-prod-20260712",
    "deployment_version": "1.4.0",
    "environment": "production",
}

ReportWriter = Callable[[Path], None]


def _write_production_smoke(path: Path) -> None:
    production_smoke.write_report(
        path,
        {
            "dry_run": False,
            "generated_at": FIXED_GENERATED_AT,
            "release_binding": {"commit_sha": "caller-supplied"},
            "report_type": "production_smoke",
        },
    )


def _write_postgres_ops(path: Path) -> None:
    postgres_ops.write_report(
        path,
        {
            "dry_run": False,
            "generated_at": FIXED_GENERATED_AT,
            "report_type": "postgres_ops",
        },
    )


def _write_otel_smoke(path: Path) -> None:
    otel_smoke.write_report(
        path,
        {
            "dry_run": False,
            "generated_at": FIXED_GENERATED_AT,
            "report_type": "otel_smoke",
        },
    )


def _write_agent_governance(path: Path) -> None:
    agent_governance_report.write_governance_report(path, eval_reports=[])


def _write_eval_report(path: Path) -> None:
    eval_reporting.write_json_report(
        path,
        summary=MetricSummary(),
        results=[],
        meta={
            "generated_at": FIXED_GENERATED_AT,
            "release_binding": {"commit_sha": "caller-supplied"},
            "suite": "release_identity",
        },
    )


REPORT_WRITERS: tuple[tuple[str, ReportWriter], ...] = (
    ("production_smoke", _write_production_smoke),
    ("postgres_ops", _write_postgres_ops),
    ("otel_smoke", _write_otel_smoke),
    ("agent_governance", _write_agent_governance),
    ("eval", _write_eval_report),
)


@pytest.fixture(autouse=True)
def _clear_release_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*RELEASE_ENV_VARS, "CI"):
        monkeypatch.delenv(name, raising=False)


def _load_report(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_timezone_aware(value: object) -> None:
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


@pytest.mark.parametrize(
    ("name", "writer"), REPORT_WRITERS, ids=[item[0] for item in REPORT_WRITERS]
)
def test_evidence_writer_attests_complete_release_identity(
    name: str,
    writer: ReportWriter,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del name
    for env_name, value in zip(RELEASE_ENV_VARS, EXPECTED_BINDING.values(), strict=True):
        monkeypatch.setenv(env_name, value)
    report_path = tmp_path / "report.json"

    writer(report_path)

    report = _load_report(report_path)
    assert report["release_binding"] == EXPECTED_BINDING
    _assert_timezone_aware(report["generated_at"])


@pytest.mark.parametrize(
    ("name", "writer"), REPORT_WRITERS, ids=[item[0] for item in REPORT_WRITERS]
)
@pytest.mark.parametrize("missing_env_name", RELEASE_ENV_VARS)
def test_evidence_writer_rejects_partial_release_identity(
    name: str,
    writer: ReportWriter,
    missing_env_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del name
    monkeypatch.setenv("CI", "true")
    for env_name, value in zip(RELEASE_ENV_VARS, EXPECTED_BINDING.values(), strict=True):
        if env_name != missing_env_name:
            monkeypatch.setenv(env_name, value)
    report_path = tmp_path / "report.json"

    with pytest.raises(ValueError, match=missing_env_name):
        writer(report_path)

    assert not report_path.exists()


@pytest.mark.parametrize(
    ("name", "writer"), REPORT_WRITERS, ids=[item[0] for item in REPORT_WRITERS]
)
def test_evidence_writer_preserves_generic_ci_without_release_identity(
    name: str,
    writer: ReportWriter,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del name
    monkeypatch.setenv("CI", "true")
    report_path = tmp_path / "report.json"

    writer(report_path)

    report = _load_report(report_path)
    assert "release_binding" not in report
    assert "release_binding" not in report.get("meta", {})
    _assert_timezone_aware(report["generated_at"])


@pytest.mark.parametrize(
    ("name", "writer"), REPORT_WRITERS, ids=[item[0] for item in REPORT_WRITERS]
)
def test_evidence_writer_preserves_local_no_identity_compatibility(
    name: str,
    writer: ReportWriter,
    tmp_path: Path,
) -> None:
    del name
    report_path = tmp_path / "report.json"

    writer(report_path)

    report = _load_report(report_path)
    assert "release_binding" not in report
    _assert_timezone_aware(report["generated_at"])


@pytest.mark.parametrize(
    "writer",
    (_write_production_smoke, _write_postgres_ops, _write_otel_smoke),
    ids=("production_smoke", "postgres_ops", "otel_smoke"),
)
def test_evidence_writer_preserves_existing_generated_at(
    writer: ReportWriter,
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.json"

    writer(report_path)

    assert _load_report(report_path)["generated_at"] == FIXED_GENERATED_AT
