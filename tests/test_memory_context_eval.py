from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import memory_context_eval

RELEASE_ENV = {
    "RELEASE_COMMIT_SHA": "0123456789abcdef0123456789abcdef01234567",
    "RELEASE_DEPLOYMENT_ID": "focus-agent-prod-20260712",
    "RELEASE_DEPLOYMENT_VERSION": "1.4.0",
    "RELEASE_ENVIRONMENT": "production",
}
EXPECTED_RELEASE_BINDING = {
    "commit_sha": RELEASE_ENV["RELEASE_COMMIT_SHA"],
    "deployment_id": RELEASE_ENV["RELEASE_DEPLOYMENT_ID"],
    "deployment_version": RELEASE_ENV["RELEASE_DEPLOYMENT_VERSION"],
    "environment": RELEASE_ENV["RELEASE_ENVIRONMENT"],
}


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def _write_cases(path: Path, *records: dict) -> None:
    _write_jsonl(path, list(records))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _memory_case(
    case_id: str,
    *,
    rendered_context: str,
    answer: str,
    expected: dict,
    tags: list[str] | None = None,
    **extra: object,
) -> dict:
    return {
        "id": case_id,
        "tags": tags or ["memory_context"],
        "input": {"rendered_context": rendered_context, "answer": answer},
        "expected": expected,
        **extra,
    }


def _candidate_case(
    case_id: str,
    *,
    rendered_context: str,
    answer: str,
    expected: dict,
    baseline: str | None = None,
    tags: list[str] | None = None,
    origin: dict | None = None,
    origin_extra: dict | None = None,
    **extra: object,
) -> dict:
    baseline_marker = f"baseline:{baseline}" if baseline else None
    case = _memory_case(
        case_id,
        rendered_context=rendered_context,
        answer=answer,
        expected=expected,
        tags=tags
        or [
            "memory_context",
            "candidate_import",
            *([baseline_marker] if baseline_marker else []),
        ],
        **extra,
    )
    if origin is not None:
        case["origin"] = dict(origin)
    elif baseline is not None:
        case["origin"] = {
            "type": "candidate_import",
            "baseline_label": baseline,
            "baseline_marker": baseline_marker,
            **(origin_extra or {}),
        }
    return case


def _run_cli(args: list[str], capsys) -> tuple[int, dict, str]:
    exit_code = memory_context_eval.main(args)
    output = capsys.readouterr()
    return exit_code, json.loads(output.out) if output.out else {}, output.err


def _write_quality_report(path: Path) -> None:
    memory_context_eval.write_report(path, dataset=Path("memory-context.jsonl"), results=[])


def _write_trend_report(path: Path) -> None:
    memory_context_eval.write_trend_report(path, golden_jsonl=())


REPORT_WRITERS = (
    pytest.param(_write_quality_report, id="quality"),
    pytest.param(_write_trend_report, id="trend"),
)


def _clear_release_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in RELEASE_ENV:
        monkeypatch.delenv(env_name, raising=False)


def _assert_timezone_aware(value: object) -> None:
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


@pytest.mark.parametrize("writer", REPORT_WRITERS)
def test_memory_context_report_attests_complete_release_identity(
    writer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_release_env(monkeypatch)
    for env_name, value in RELEASE_ENV.items():
        monkeypatch.setenv(env_name, value)
    report_path = tmp_path / "report.json"

    writer(report_path)

    report = _read_json(report_path)
    assert report["release_binding"] == EXPECTED_RELEASE_BINDING
    _assert_timezone_aware(report["generated_at"])


@pytest.mark.parametrize("writer", REPORT_WRITERS)
@pytest.mark.parametrize("missing_env_name", RELEASE_ENV)
def test_memory_context_report_rejects_partial_release_identity_before_write(
    writer,
    missing_env_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_release_env(monkeypatch)
    for env_name, value in RELEASE_ENV.items():
        if env_name != missing_env_name:
            monkeypatch.setenv(env_name, value)
    report_path = tmp_path / "report.json"

    with pytest.raises(ValueError, match=missing_env_name):
        writer(report_path)

    assert not report_path.exists()


@pytest.mark.parametrize("writer", REPORT_WRITERS)
@pytest.mark.parametrize("generic_ci", (False, True), ids=("local", "generic-ci"))
def test_memory_context_report_preserves_no_identity_compatibility(
    writer,
    generic_ci: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_release_env(monkeypatch)
    if generic_ci:
        monkeypatch.setenv("CI", "true")
    else:
        monkeypatch.delenv("CI", raising=False)
    report_path = tmp_path / "report.json"

    writer(report_path)

    report = _read_json(report_path)
    assert "release_binding" not in report
    assert "release_binding" not in report.get("meta", {})
    _assert_timezone_aware(report["generated_at"])


def test_memory_context_report_replaces_caller_supplied_release_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for env_name, value in RELEASE_ENV.items():
        monkeypatch.setenv(env_name, value)
    monkeypatch.setattr(
        memory_context_eval,
        "build_memory_regression_trend_report",
        lambda **_: {
            "generated_at": "2026-07-12T08:30:00Z",
            "release_binding": {"commit_sha": "caller-supplied"},
            "meta": {
                "release_binding": {"commit_sha": "caller-supplied"},
                "suite": "memory_context_regression_trend",
            },
            "pollution_alerts": [],
            "status": "ok",
        },
    )
    report_path = tmp_path / "trend.json"

    memory_context_eval.write_trend_report(report_path, golden_jsonl=())

    report = _read_json(report_path)
    assert report["release_binding"] == EXPECTED_RELEASE_BINDING
    assert "release_binding" not in report["meta"]
    assert report["generated_at"] == "2026-07-12T08:30:00Z"


def test_memory_context_quality_dataset_passes(tmp_path: Path) -> None:
    report_path = tmp_path / "memory-context.json"

    result = memory_context_eval.run(report_json=report_path)
    report = _read_json(report_path)

    assert result["status"] == "passed"
    assert report["meta"]["suite"] == "memory_context_quality"
    assert 15 <= report["summary"]["total"] <= 20
    assert report["summary"]["failed"] == 0
    assert report["summary"]["key_fact_recall"] == 1.0
    assert report["summary"]["irrelevant_memory_pollution"] == 0.0


def test_memory_context_quality_reports_failures(tmp_path: Path) -> None:
    dataset = tmp_path / "memory-context.jsonl"
    _write_cases(
        dataset,
        _memory_case(
            "bad-memory-context",
            rendered_context="Context contains stale sqlite migration path.",
            answer="Use sqlite migration path.",
            expected={
                "required_facts": ["postgres migration path"],
                "forbidden_facts": ["sqlite migration path"],
            },
        ),
    )
    report_path = tmp_path / "report.json"

    result = memory_context_eval.run(dataset=dataset, report_json=report_path)
    report = _read_json(report_path)

    assert result["status"] == "failed"
    assert report["summary"]["failed_case_ids"] == ["bad-memory-context"]
    assert "forbidden facts leaked" in report["results"][0]["verdicts"][0]["reasoning"]


def test_memory_context_quality_fails_missing_artifact_refs(tmp_path: Path) -> None:
    dataset = tmp_path / "memory-context.jsonl"
    _write_cases(
        dataset,
        _memory_case(
            "missing-artifact",
            tags=["artifact_ref"],
            rendered_context="Context has the decision but no evidence ref.",
            answer="Use the approved Postgres decision.",
            expected={
                "required_facts": ["approved Postgres decision"],
                "artifact_refs": ["artifact://missing/postgres-decision"],
            },
        ),
    )

    result = memory_context_eval.run(dataset=dataset, report_json=tmp_path / "report.json")

    assert result["status"] == "failed"
    assert result["summary"]["failed_case_ids"] == ["missing-artifact"]
    assert result["summary"]["artifact_refs_present"] == 0.0


def test_memory_context_quality_fails_unmarked_conflict(tmp_path: Path) -> None:
    dataset = tmp_path / "memory-context.jsonl"
    _write_cases(
        dataset,
        _memory_case(
            "unmarked-conflict",
            tags=["conflict"],
            rendered_context=(
                "Old memory says provider is Anthropic. Current config says Moonshot."
            ),
            answer="Use Moonshot from the current config.",
            expected={
                "required_facts": ["Anthropic", "Moonshot"],
                "conflict_markers": ["CONFLICT", "resolve"],
            },
        ),
    )

    result = memory_context_eval.run(dataset=dataset, report_json=tmp_path / "report.json")

    assert result["status"] == "failed"
    assert result["summary"]["failed_case_ids"] == ["unmarked-conflict"]
    assert result["summary"]["conflict_memory_marked"] == 0.0


def test_memory_context_failure_conversion_from_replay_report(tmp_path: Path) -> None:
    replay_report = tmp_path / "replay-report.json"
    _write_json(
        replay_report,
        {
            "meta": {"suite": "trajectory_replay"},
            "results": [
                {
                    "case_id": "ctx-reg-7",
                    "passed": False,
                    "input": {
                        "rendered_context": "Replay context omitted artifact refs.",
                        "answer": "Use the Postgres migration plan.",
                    },
                    "expected": {
                        "required_facts": ["Postgres migration plan"],
                        "artifact_refs": ["artifact://trajectory/ctx-reg-7/postgres-plan"],
                    },
                    "replay_error": "missing artifact refs",
                },
                {
                    "case_id": "ctx-reg-8",
                    "passed": True,
                    "input": {"rendered_context": "ok", "answer": "ok"},
                },
            ],
        },
    )

    cases = memory_context_eval.convert_failure_report_to_cases(replay_report)

    assert len(cases) == 1
    assert cases[0]["id"] == "mc_replay_ctx-reg-7"
    assert cases[0]["tags"] == ["memory_context", "converted_failure", "trajectory_replay"]
    assert cases[0]["expected"]["artifact_refs"] == [
        "artifact://trajectory/ctx-reg-7/postgres-plan"
    ]
    assert cases[0]["origin"]["replay_error"] == "missing artifact refs"


def test_memory_context_failure_conversion_skips_records_without_assertions(
    tmp_path: Path,
) -> None:
    replay_report = tmp_path / "replay-report.json"
    _write_json(
        replay_report,
        {
            "results": [
                {
                    "case_id": "metadata-only",
                    "passed": False,
                    "replay_error": "tool timeout",
                }
            ]
        },
    )

    cases = memory_context_eval.convert_failure_report_to_cases(replay_report)

    assert cases == []


def test_memory_context_candidate_import_multiple_sources_sanitizes_and_dedupes(
    tmp_path: Path,
) -> None:
    replay_source = tmp_path / "replay-report.json"
    duplicate_input = {
        "rendered_context": (
            "Use the Postgres migration plan. Contact alice@example.com, phone "
            "+1 (415) 555-2671, auth Bearer abcdefghij12345, api_key=sk-1234567890abcdef."
        ),
        "answer": "Use the Postgres migration plan.",
    }
    duplicate_expected = {
        "required_facts": ["Postgres migration plan"],
        "artifact_refs": ["artifact://candidate/postgres-plan"],
    }
    _write_json(
        replay_source,
        {
            "meta": {"suite": "trajectory_replay"},
            "results": [
                {
                    "case_id": "alice@example.com",
                    "input": duplicate_input,
                    "expected": duplicate_expected,
                },
                {
                    "case_id": "metadata-only",
                    "input": {"rendered_context": "No assertions here."},
                },
            ],
        },
    )
    trajectory_source = tmp_path / "trajectory.jsonl"
    _write_cases(
        trajectory_source,
        {
            "id": "artifact-secret-duplicate",
            "input": duplicate_input,
            "expected": duplicate_expected,
        },
        {
            "id": "context-freshness",
            "bucket": "context",
            "rendered_context": "Current route is BranchTree.",
            "answer": "Use the BranchTree route.",
            "expected": {
                "required_context_markers": ["Current route"],
                "answer_contains_all": ["BranchTree route"],
            },
        },
    )

    result = memory_context_eval.import_candidate_cases([replay_source, trajectory_source])
    repeated = memory_context_eval.import_candidate_cases([replay_source, trajectory_source])
    serialized = json.dumps(result.cases, ensure_ascii=False, sort_keys=True)

    result_summary = result.to_dict()
    assert {
        key: result_summary[key]
        for key in (
            "imported",
            "sources",
            "records",
            "skipped_no_assertions",
            "skipped_duplicates",
        )
    } == {
        "imported": 2,
        "sources": 2,
        "records": 4,
        "skipped_no_assertions": 1,
        "skipped_duplicates": 1,
    }
    assert result_summary["pii_redaction_summary"]["total"] >= 4
    assert result_summary["duplicate_reasons"][0]["duplicate_of"] == result.cases[0]["id"]
    assert (
        result_summary["duplicate_reasons"][0]["reason"]
        == "same sanitized input and expected assertions"
    )
    assert result_summary["candidate_first_invariant"]["golden_dataset_unchanged"] is True
    assert [case["id"] for case in result.cases] == [case["id"] for case in repeated.cases]
    assert result.cases[0]["tags"][:5] == [
        "memory_context",
        "candidate_import",
        "source:replay",
        "bucket:artifact_ref",
        "baseline:candidate",
    ]
    assert result.cases[0]["origin"]["baseline_label"] == "candidate"
    assert result.cases[0]["origin"]["baseline_marker"] == "baseline:candidate"
    assert result.cases[0]["origin"]["source_explanation"]["assertion_fields"] == [
        "required_facts",
        "artifact_refs",
    ]
    assert result.cases[0]["candidate_ops"]["promotion_review_sla"]["status"] in {
        "within_sla",
        "overdue",
    }
    assert result.cases[0]["privacy"]["redaction_summary"]["total"] >= 4
    assert "source:trajectory" in result.cases[1]["tags"]
    assert "bucket:context" in result.cases[1]["tags"]
    assert "alice@example.com" not in serialized
    assert "alice-example-com" not in serialized
    assert "+1 (415) 555-2671" not in serialized
    assert "555-2671" not in serialized
    assert "abcdefghi" not in serialized
    assert "sk-1234567890abcdef" not in serialized
    assert "[REDACTED_EMAIL]" in serialized
    assert "[REDACTED_PHONE]" in serialized
    assert "[REDACTED_TOKEN]" in serialized
    assert "[REDACTED_SECRET]" in serialized


def test_memory_context_candidate_import_cli_writes_jsonl(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "memory-context-report.json"
    _write_json(
        source,
        {
            "meta": {"suite": "memory_context_quality"},
            "results": [
                {
                    "case_id": "mctx-1",
                    "case": {
                        "tags": ["regression"],
                        "input": {
                            "rendered_context": "Context mentions the compaction summary.",
                            "answer": "Use the compaction summary.",
                        },
                        "expected": {
                            "required_facts": ["compaction summary"],
                        },
                    },
                }
            ],
        },
    )
    dataset_out = tmp_path / "candidates.jsonl"

    exit_code, stdout, _ = _run_cli(
        [
            "--candidate-source-json",
            str(source),
            "--candidate-dataset-out",
            str(dataset_out),
            "--candidate-baseline-label",
            "nightly",
        ],
        capsys,
    )
    imported = _read_jsonl(dataset_out)

    assert exit_code == 0
    assert stdout["imported"] == 1
    assert stdout["dataset"] == str(dataset_out)
    assert imported[0]["origin"]["baseline_label"] == "nightly"
    assert imported[0]["origin"]["source_type"] == "memory-context"
    assert "source:memory-context" in imported[0]["tags"]
    assert "baseline:nightly" in imported[0]["tags"]


def test_memory_context_candidate_import_cli_refuses_golden_dataset_output(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "memory-context-report.json"
    _write_json(
        source,
        {
            "results": [
                {
                    "case_id": "mctx-1",
                    "input": {
                        "rendered_context": "Context mentions the compaction summary.",
                        "answer": "Use the compaction summary.",
                    },
                    "expected": {"required_facts": ["compaction summary"]},
                }
            ],
        },
    )

    exit_code, _, stderr = _run_cli(
        [
            "--candidate-source-json",
            str(source),
            "--candidate-dataset-out",
            str(memory_context_eval.DEFAULT_DATASET),
        ],
        capsys,
    )

    assert exit_code == 2
    assert "must not target the golden memory/context dataset" in stderr


def test_memory_context_candidate_import_reports_age_and_review_sla(
    tmp_path: Path,
) -> None:
    source = tmp_path / "trajectory.jsonl"
    _write_cases(
        source,
        {
            "id": "old-candidate",
            "created_at": "2026-04-20T00:00:00Z",
            "rendered_context": "Context mentions the BranchTree route.",
            "answer": "Use the BranchTree route.",
            "expected": {"required_facts": ["BranchTree route"]},
        },
    )

    result = memory_context_eval.import_candidate_cases(
        [source],
        now=datetime(2026, 4, 26, tzinfo=UTC),
        promotion_review_sla_days=3,
    )
    case = result.cases[0]
    summary = result.to_dict()

    assert case["candidate_ops"]["candidate_age_days"] == 6.0
    assert case["candidate_ops"]["candidate_age_bucket"] == "over_sla"
    assert case["candidate_ops"]["promotion_review_sla"]["overdue"] is True
    assert summary["candidate_age_summary"]["max_age_days"] == 6.0
    assert summary["candidate_age_summary"]["promotion_review_overdue"] == 1


def test_memory_context_candidate_review_promotes_only_explicit_approval(
    tmp_path: Path,
) -> None:
    candidate_jsonl = tmp_path / "candidates.jsonl"
    approved_case = _candidate_case(
        "mc_candidate_approved",
        baseline="nightly",
        rendered_context="Contact alice@example.com with Bearer abcdefghij12345.",
        answer="Use the Postgres migration plan.",
        expected={"required_facts": ["Postgres migration plan"]},
        origin_extra={
            "source_type": "replay",
            "source_record_id": "alice@example.com",
        },
    )
    rejected_case = _candidate_case(
        "mc_candidate_rejected",
        baseline="nightly",
        rendered_context="Rejected context.",
        answer="Rejected answer.",
        expected={"required_context_markers": ["Rejected context"]},
    )
    pending_case = _candidate_case(
        "mc_candidate_pending",
        baseline="nightly",
        rendered_context="Pending context.",
        answer="Pending answer.",
        expected={"answer_contains_all": ["Pending answer"]},
    )
    no_assertion_case = {
        "id": "mc_candidate_no_assertions",
        "input": {"rendered_context": "Metadata only.", "answer": ""},
        "expected": {},
    }
    _write_cases(
        candidate_jsonl,
        approved_case,
        rejected_case,
        pending_case,
        {**approved_case, "id": "mc_candidate_duplicate"},
        no_assertion_case,
    )

    result = memory_context_eval.review_candidate_cases(
        [candidate_jsonl],
        approved_ids=["mc_candidate_approved"],
        rejected_ids=["mc_candidate_rejected"],
        reviewer="qa@example.com",
        note="approved with token=sk-1234567890abcdef",
    )
    serialized = json.dumps(
        {"reviewed": result.reviewed_cases, "promoted": result.promoted_cases},
        ensure_ascii=False,
        sort_keys=True,
    )

    result_summary = result.to_dict()
    assert {
        key: result_summary[key]
        for key in (
            "reviewed",
            "promoted",
            "sources",
            "records",
            "skipped_no_assertions",
            "skipped_duplicates",
            "approved",
            "rejected",
            "pending",
        )
    } == {
        "reviewed": 3,
        "promoted": 1,
        "sources": 1,
        "records": 5,
        "skipped_no_assertions": 1,
        "skipped_duplicates": 1,
        "approved": 1,
        "rejected": 1,
        "pending": 1,
    }
    assert result_summary["duplicate_reasons"][0]["operation"] == "candidate_review"
    assert result_summary["pii_redaction_summary"]["total"] >= 3
    assert result_summary["promotion_sla_summary"]["reviewed"] == 3
    assert (
        result_summary["candidate_first_invariant"]["promoted_dataset_requires_explicit_approval"]
        is True
    )
    assert [case["id"] for case in result.promoted_cases] == ["mc_candidate_approved"]
    assert result.promoted_cases[0]["origin"]["baseline_label"] == "nightly"
    assert result.promoted_cases[0]["origin"]["baseline_marker"] == "baseline:nightly"
    assert "baseline:nightly" in result.promoted_cases[0]["tags"]
    assert result.promoted_cases[0]["promotion_review"]["status"] == "approved"
    assert result.reviewed_cases[1]["promotion_review"]["status"] == "rejected"
    assert result.reviewed_cases[2]["promotion_review"]["status"] == "pending"
    assert "alice@example.com" not in serialized
    assert "abcdefghi" not in serialized
    assert "sk-1234567890abcdef" not in serialized
    assert "[REDACTED_EMAIL]" in serialized
    assert "[REDACTED_TOKEN]" in serialized
    assert "[REDACTED_SECRET]" in serialized


def test_memory_context_candidate_review_marks_promotion_sla_overdue(
    tmp_path: Path,
) -> None:
    candidate_jsonl = tmp_path / "candidates.jsonl"
    _write_cases(
        candidate_jsonl,
        _candidate_case(
            "mc_candidate_old_pending",
            rendered_context="Context includes the Postgres path.",
            answer="Use the Postgres path.",
            expected={"required_facts": ["Postgres path"]},
            candidate_ops={
                "candidate_created_at": "2026-04-20T00:00:00Z",
                "candidate_age_days": 6.0,
                "candidate_age_bucket": "over_sla",
                "promotion_review_sla": {
                    "sla_days": 3,
                    "candidate_created_at": "2026-04-20T00:00:00Z",
                    "review_due_at": "2026-04-23T00:00:00Z",
                    "age_days": 6.0,
                    "overdue": True,
                    "status": "overdue",
                },
            },
        ),
    )

    result = memory_context_eval.review_candidate_cases(
        [candidate_jsonl],
        now=datetime(2026, 4, 26, tzinfo=UTC),
        promotion_review_sla_days=3,
    )
    review = result.reviewed_cases[0]["promotion_review"]

    assert review["status"] == "pending"
    assert review["sla"]["overdue"] is True
    assert review["sla"]["reviewed_after_due"] is True
    assert result.to_dict()["promotion_sla_summary"] == {
        "reviewed": 1,
        "overdue": 1,
        "pending_overdue": 1,
    }


def test_memory_context_candidate_review_cli_writes_review_and_promotion(
    tmp_path: Path,
    capsys,
) -> None:
    candidate_jsonl = tmp_path / "candidates.jsonl"
    _write_cases(
        candidate_jsonl,
        _candidate_case(
            "mc_candidate_approved",
            baseline="candidate",
            rendered_context="Context mentions the compaction summary.",
            answer="Use the compaction summary.",
            expected={"required_facts": ["compaction summary"]},
        ),
        _candidate_case(
            "mc_candidate_pending",
            baseline="candidate",
            rendered_context="Context mentions the branch tree.",
            answer="Use the branch tree.",
            expected={"required_facts": ["branch tree"]},
        ),
    )
    reviewed_out = tmp_path / "reviewed.jsonl"
    promoted_out = tmp_path / "promoted.jsonl"

    exit_code, stdout, _ = _run_cli(
        [
            "--candidate-review-jsonl",
            str(candidate_jsonl),
            "--candidate-reviewed-out",
            str(reviewed_out),
            "--candidate-promoted-out",
            str(promoted_out),
            "--candidate-approve-id",
            "mc_candidate_approved",
        ],
        capsys,
    )
    reviewed = _read_jsonl(reviewed_out)
    promoted = _read_jsonl(promoted_out)

    assert exit_code == 0
    assert stdout["reviewed"] == 2
    assert stdout["promoted"] == 1
    assert stdout["reviewed_dataset"] == str(reviewed_out)
    assert stdout["promoted_dataset"] == str(promoted_out)
    assert [case["promotion_review"]["status"] for case in reviewed] == ["approved", "pending"]
    assert [case["id"] for case in promoted] == ["mc_candidate_approved"]

    no_approval_reviewed_out = tmp_path / "reviewed-no-approval.jsonl"
    no_approval_promoted_out = tmp_path / "empty-promoted.jsonl"
    no_approval_exit_code, no_approval_stdout, _ = _run_cli(
        [
            "--candidate-review-jsonl",
            str(candidate_jsonl),
            "--candidate-reviewed-out",
            str(no_approval_reviewed_out),
            "--candidate-promoted-out",
            str(no_approval_promoted_out),
        ],
        capsys,
    )

    assert no_approval_exit_code == 0
    assert no_approval_stdout["promoted"] == 0
    assert no_approval_stdout["promoted_dataset"] == str(no_approval_promoted_out)
    assert _read_jsonl(no_approval_promoted_out) == []


def test_memory_context_candidate_cli_uses_default_pipeline_paths(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    source = tmp_path / "replay-report.json"
    candidate_out = tmp_path / "reports" / "nightly" / "memory-context-candidates.jsonl"
    reviewed_out = tmp_path / "reports" / "nightly" / "memory-context-reviewed.jsonl"
    promoted_out = tmp_path / "reports" / "nightly" / "memory-context-promoted.jsonl"
    _write_json(
        source,
        {
            "meta": {"suite": "trajectory_replay"},
            "results": [
                {
                    "case_id": "ctx-reg-9",
                    "passed": False,
                    "input": {
                        "rendered_context": "Context mentions the Postgres fix.",
                        "answer": "Use the Postgres fix.",
                    },
                    "expected": {"required_facts": ["Postgres fix"]},
                }
            ],
        },
    )
    monkeypatch.setattr(memory_context_eval, "DEFAULT_CANDIDATE_JSONL", candidate_out)
    monkeypatch.setattr(memory_context_eval, "DEFAULT_REVIEWED_JSONL", reviewed_out)
    monkeypatch.setattr(memory_context_eval, "DEFAULT_PROMOTED_JSONL", promoted_out)

    import_exit_code, import_stdout, _ = _run_cli(
        ["--candidate-source-json", str(source), "--candidate-source-type", "replay"],
        capsys,
    )
    review_exit_code, review_stdout, _ = _run_cli(
        ["--candidate-review-jsonl", str(candidate_out)],
        capsys,
    )

    assert import_exit_code == 0
    assert import_stdout["dataset"] == str(candidate_out)
    assert review_exit_code == 0
    assert review_stdout["reviewed_dataset"] == str(reviewed_out)
    assert review_stdout["promoted_dataset"] == str(promoted_out)
    assert len(_read_jsonl(candidate_out)) == 1
    assert len(_read_jsonl(reviewed_out)) == 1
    assert _read_jsonl(promoted_out) == []


def test_memory_context_compaction_semantic_metrics_report_drift(tmp_path: Path) -> None:
    dataset = tmp_path / "compaction.jsonl"
    _write_cases(
        dataset,
        _memory_case(
            "context-compaction-drift",
            tags=["memory_context", "context_compaction"],
            rendered_context="rolling_summary says old sqlite path is approved.",
            answer="Use the sqlite path.",
            expected={
                "required_facts": ["Postgres path"],
                "forbidden_facts": ["sqlite path"],
                "required_context_markers": ["Postgres path"],
                "answer_contains_all": ["Postgres path"],
            },
        ),
    )

    result = memory_context_eval.run(dataset=dataset, report_json=tmp_path / "report.json")

    assert result["status"] == "failed"
    assert result["summary"]["context_compaction_semantic_recall"] == 0.0
    assert result["summary"]["context_compaction_semantic_precision"] == 0.0
    assert result["summary"]["context_compaction_semantic_grounding"] == 0.0
    assert result["summary"]["context_compaction_semantic_answerability"] == 0.0
    assert result["summary"]["context_compaction_semantic_quality"] == 0.0
    assert result["summary"]["context_compaction_semantic_drift"] == 1.0
    assert result["summary"]["context_compaction_drift_report"] == {
        "answerability": 0.0,
        "case_count": 1,
        "drift_risk": "high",
        "grounding": 0.0,
        "overall_drift": 1.0,
        "precision": 0.0,
        "recall": 0.0,
    }


def test_memory_regression_trend_report_summarizes_stages_and_alerts(
    tmp_path: Path,
) -> None:
    candidate_jsonl = tmp_path / "candidate.jsonl"
    reviewed_jsonl = tmp_path / "reviewed.jsonl"
    promoted_jsonl = tmp_path / "promoted.jsonl"
    golden_jsonl = tmp_path / "golden.jsonl"
    polluted_candidate = _candidate_case(
        "candidate-polluted",
        rendered_context="Context includes stale sqlite path.",
        answer="Use the Postgres path.",
        expected={
            "required_facts": ["Postgres path"],
            "forbidden_facts": ["sqlite path"],
        },
    )
    reviewed_case = _candidate_case(
        "reviewed-approved",
        rendered_context="Context includes Postgres path.",
        answer="Use the Postgres path.",
        expected={"required_facts": ["Postgres path"]},
        promotion_review={"status": "approved", "approved": True},
    )
    golden_case = _memory_case(
        "golden-compaction",
        tags=["memory_context", "context_compaction"],
        rendered_context="rolling_summary keeps Postgres path.",
        answer="Use the Postgres path.",
        expected={
            "required_facts": ["Postgres path"],
            "required_context_markers": ["Postgres path"],
            "answer_contains_all": ["Postgres path"],
        },
    )
    for path, cases in (
        (candidate_jsonl, [polluted_candidate]),
        (reviewed_jsonl, [reviewed_case]),
        (promoted_jsonl, [reviewed_case]),
        (golden_jsonl, [golden_case]),
    ):
        _write_jsonl(path, cases)

    report = memory_context_eval.build_memory_regression_trend_report(
        candidate_jsonl=[candidate_jsonl],
        reviewed_jsonl=[reviewed_jsonl],
        promoted_jsonl=[promoted_jsonl],
        golden_jsonl=[golden_jsonl],
    )

    assert report["status"] == "alert"
    assert report["stages"]["candidate"]["pollution_rate"] == 1.0
    assert report["stages"]["candidate"]["pollution_case_ids"] == ["candidate-polluted"]
    assert report["stages"]["reviewed"]["review_status_counts"] == {"approved": 1}
    assert report["promotion_history"]["promoted_case_ids"] == ["reviewed-approved"]
    assert report["stages"]["golden"]["context_compaction_drift_report"]["overall_drift"] == 0.0
    assert report["trend"][3]["context_compaction_drift_report"]["drift_risk"] == "low"
    assert report["stages"]["golden"]["context_compaction_semantic_quality"] == 1.0
    assert report["pollution_alerts"][0]["kind"] == "irrelevant_memory_pollution"


def test_memory_regression_trend_cli_writes_report(tmp_path: Path, capsys) -> None:
    candidate_jsonl = tmp_path / "candidate.jsonl"
    golden_jsonl = tmp_path / "golden.jsonl"
    report_json = tmp_path / "trend.json"
    case = _memory_case(
        "candidate-ok",
        rendered_context="Context includes the branch tree.",
        answer="Use the branch tree.",
        expected={"required_facts": ["branch tree"]},
    )
    for path in (candidate_jsonl, golden_jsonl):
        _write_cases(path, case)

    exit_code, stdout, _ = _run_cli(
        [
            "--trend-report-json",
            str(report_json),
            "--trend-candidate-jsonl",
            str(candidate_jsonl),
            "--trend-golden-jsonl",
            str(golden_jsonl),
        ],
        capsys,
    )
    report = _read_json(report_json)

    assert exit_code == 0
    assert stdout["status"] == "ok"
    assert stdout["trend_report_json"] == str(report_json)
    assert stdout["pollution_alerts"] == 0
    assert report["meta"]["suite"] == "memory_context_regression_trend"
    assert report["stages"]["candidate"]["total"] == 1
