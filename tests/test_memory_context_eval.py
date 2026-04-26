from __future__ import annotations

import json
from pathlib import Path

from scripts import memory_context_eval


def test_memory_context_quality_dataset_passes(tmp_path: Path) -> None:
    report_path = tmp_path / "memory-context.json"

    result = memory_context_eval.run(report_json=report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert result["status"] == "passed"
    assert report["meta"]["suite"] == "memory_context_quality"
    assert 15 <= report["summary"]["total"] <= 20
    assert report["summary"]["failed"] == 0
    assert report["summary"]["key_fact_recall"] == 1.0
    assert report["summary"]["irrelevant_memory_pollution"] == 0.0


def test_memory_context_quality_reports_failures(tmp_path: Path) -> None:
    dataset = tmp_path / "memory-context.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "bad-memory-context",
                "tags": ["memory_context"],
                "input": {
                    "rendered_context": "Context contains stale sqlite migration path.",
                    "answer": "Use sqlite migration path.",
                },
                "expected": {
                    "required_facts": ["postgres migration path"],
                    "forbidden_facts": ["sqlite migration path"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    result = memory_context_eval.run(dataset=dataset, report_json=report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert result["status"] == "failed"
    assert report["summary"]["failed_case_ids"] == ["bad-memory-context"]
    assert "forbidden facts leaked" in report["results"][0]["verdicts"][0]["reasoning"]


def test_memory_context_quality_fails_missing_artifact_refs(tmp_path: Path) -> None:
    dataset = tmp_path / "memory-context.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "missing-artifact",
                "tags": ["artifact_ref"],
                "input": {
                    "rendered_context": "Context has the decision but no evidence ref.",
                    "answer": "Use the approved Postgres decision.",
                },
                "expected": {
                    "required_facts": ["approved Postgres decision"],
                    "artifact_refs": ["artifact://missing/postgres-decision"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = memory_context_eval.run(dataset=dataset, report_json=tmp_path / "report.json")

    assert result["status"] == "failed"
    assert result["summary"]["failed_case_ids"] == ["missing-artifact"]
    assert result["summary"]["artifact_refs_present"] == 0.0


def test_memory_context_quality_fails_unmarked_conflict(tmp_path: Path) -> None:
    dataset = tmp_path / "memory-context.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "unmarked-conflict",
                "tags": ["conflict"],
                "input": {
                    "rendered_context": "Old memory says provider is Anthropic. Current config says Moonshot.",
                    "answer": "Use Moonshot from the current config.",
                },
                "expected": {
                    "required_facts": ["Anthropic", "Moonshot"],
                    "conflict_markers": ["CONFLICT", "resolve"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = memory_context_eval.run(dataset=dataset, report_json=tmp_path / "report.json")

    assert result["status"] == "failed"
    assert result["summary"]["failed_case_ids"] == ["unmarked-conflict"]
    assert result["summary"]["conflict_memory_marked"] == 0.0


def test_memory_context_failure_conversion_from_replay_report(tmp_path: Path) -> None:
    replay_report = tmp_path / "replay-report.json"
    replay_report.write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )

    cases = memory_context_eval.convert_failure_report_to_cases(replay_report)

    assert len(cases) == 1
    assert cases[0]["id"] == "mc_replay_ctx-reg-7"
    assert cases[0]["tags"] == ["memory_context", "converted_failure", "trajectory_replay"]
    assert cases[0]["expected"]["artifact_refs"] == ["artifact://trajectory/ctx-reg-7/postgres-plan"]
    assert cases[0]["origin"]["replay_error"] == "missing artifact refs"


def test_memory_context_failure_conversion_skips_records_without_assertions(
    tmp_path: Path,
) -> None:
    replay_report = tmp_path / "replay-report.json"
    replay_report.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "case_id": "metadata-only",
                        "passed": False,
                        "replay_error": "tool timeout",
                    }
                ]
            }
        ),
        encoding="utf-8",
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
    replay_source.write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )
    trajectory_source = tmp_path / "trajectory.jsonl"
    trajectory_source.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "artifact-secret-duplicate",
                        "input": duplicate_input,
                        "expected": duplicate_expected,
                    }
                ),
                json.dumps(
                    {
                        "id": "context-freshness",
                        "bucket": "context",
                        "rendered_context": "Current route is BranchTree.",
                        "answer": "Use the BranchTree route.",
                        "expected": {
                            "required_context_markers": ["Current route"],
                            "answer_contains_all": ["BranchTree route"],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = memory_context_eval.import_candidate_cases([replay_source, trajectory_source])
    repeated = memory_context_eval.import_candidate_cases([replay_source, trajectory_source])
    serialized = json.dumps(result.cases, ensure_ascii=False, sort_keys=True)

    assert result.to_dict() == {
        "imported": 2,
        "sources": 2,
        "records": 4,
        "skipped_no_assertions": 1,
        "skipped_duplicates": 1,
    }
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
    assert "source:trajectory" in result.cases[1]["tags"]
    assert "bucket:context" in result.cases[1]["tags"]
    assert "alice@example.com" not in serialized
    assert "alice-example-com" not in serialized
    assert "415" not in serialized
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
    source.write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )
    dataset_out = tmp_path / "candidates.jsonl"

    exit_code = memory_context_eval.main(
        [
            "--candidate-source-json",
            str(source),
            "--candidate-dataset-out",
            str(dataset_out),
            "--candidate-baseline-label",
            "nightly",
        ]
    )
    stdout = json.loads(capsys.readouterr().out)
    imported = [json.loads(line) for line in dataset_out.read_text(encoding="utf-8").splitlines()]

    assert exit_code == 0
    assert stdout["imported"] == 1
    assert stdout["dataset"] == str(dataset_out)
    assert imported[0]["origin"]["baseline_label"] == "nightly"
    assert imported[0]["origin"]["source_type"] == "memory-context"
    assert "source:memory-context" in imported[0]["tags"]
    assert "baseline:nightly" in imported[0]["tags"]


def test_memory_context_candidate_review_promotes_only_explicit_approval(
    tmp_path: Path,
) -> None:
    candidate_jsonl = tmp_path / "candidates.jsonl"
    approved_case = {
        "id": "mc_candidate_approved",
        "tags": ["memory_context", "candidate_import", "baseline:nightly"],
        "input": {
            "rendered_context": "Contact alice@example.com with Bearer abcdefghij12345.",
            "answer": "Use the Postgres migration plan.",
        },
        "expected": {"required_facts": ["Postgres migration plan"]},
        "origin": {
            "type": "candidate_import",
            "baseline_label": "nightly",
            "baseline_marker": "baseline:nightly",
            "source_type": "replay",
            "source_record_id": "alice@example.com",
        },
    }
    rejected_case = {
        "id": "mc_candidate_rejected",
        "tags": ["memory_context", "candidate_import", "baseline:nightly"],
        "input": {"rendered_context": "Rejected context.", "answer": "Rejected answer."},
        "expected": {"required_context_markers": ["Rejected context"]},
        "origin": {
            "type": "candidate_import",
            "baseline_label": "nightly",
            "baseline_marker": "baseline:nightly",
        },
    }
    pending_case = {
        "id": "mc_candidate_pending",
        "tags": ["memory_context", "candidate_import", "baseline:nightly"],
        "input": {"rendered_context": "Pending context.", "answer": "Pending answer."},
        "expected": {"answer_contains_all": ["Pending answer"]},
        "origin": {
            "type": "candidate_import",
            "baseline_label": "nightly",
            "baseline_marker": "baseline:nightly",
        },
    }
    no_assertion_case = {
        "id": "mc_candidate_no_assertions",
        "input": {"rendered_context": "Metadata only.", "answer": ""},
        "expected": {},
    }
    candidate_jsonl.write_text(
        "\n".join(
            json.dumps(case)
            for case in [
                approved_case,
                rejected_case,
                pending_case,
                {**approved_case, "id": "mc_candidate_duplicate"},
                no_assertion_case,
            ]
        )
        + "\n",
        encoding="utf-8",
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

    assert result.to_dict() == {
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


def test_memory_context_candidate_review_cli_writes_review_and_promotion(
    tmp_path: Path,
    capsys,
) -> None:
    candidate_jsonl = tmp_path / "candidates.jsonl"
    candidate_jsonl.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "mc_candidate_approved",
                        "tags": ["memory_context", "candidate_import", "baseline:candidate"],
                        "input": {
                            "rendered_context": "Context mentions the compaction summary.",
                            "answer": "Use the compaction summary.",
                        },
                        "expected": {"required_facts": ["compaction summary"]},
                        "origin": {
                            "type": "candidate_import",
                            "baseline_label": "candidate",
                            "baseline_marker": "baseline:candidate",
                        },
                    }
                ),
                json.dumps(
                    {
                        "id": "mc_candidate_pending",
                        "tags": ["memory_context", "candidate_import", "baseline:candidate"],
                        "input": {
                            "rendered_context": "Context mentions the branch tree.",
                            "answer": "Use the branch tree.",
                        },
                        "expected": {"required_facts": ["branch tree"]},
                        "origin": {
                            "type": "candidate_import",
                            "baseline_label": "candidate",
                            "baseline_marker": "baseline:candidate",
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    reviewed_out = tmp_path / "reviewed.jsonl"
    promoted_out = tmp_path / "promoted.jsonl"

    exit_code = memory_context_eval.main(
        [
            "--candidate-review-jsonl",
            str(candidate_jsonl),
            "--candidate-reviewed-out",
            str(reviewed_out),
            "--candidate-promoted-out",
            str(promoted_out),
            "--candidate-approve-id",
            "mc_candidate_approved",
        ]
    )
    stdout = json.loads(capsys.readouterr().out)
    reviewed = [json.loads(line) for line in reviewed_out.read_text(encoding="utf-8").splitlines()]
    promoted = [json.loads(line) for line in promoted_out.read_text(encoding="utf-8").splitlines()]

    assert exit_code == 0
    assert stdout["reviewed"] == 2
    assert stdout["promoted"] == 1
    assert stdout["reviewed_dataset"] == str(reviewed_out)
    assert stdout["promoted_dataset"] == str(promoted_out)
    assert [case["promotion_review"]["status"] for case in reviewed] == ["approved", "pending"]
    assert [case["id"] for case in promoted] == ["mc_candidate_approved"]

    blocked_out = tmp_path / "blocked.jsonl"
    blocked_exit_code = memory_context_eval.main(
        [
            "--candidate-review-jsonl",
            str(candidate_jsonl),
            "--candidate-promoted-out",
            str(blocked_out),
        ]
    )
    blocked_output = capsys.readouterr()

    assert blocked_exit_code == 2
    assert "--candidate-promoted-out requires" in blocked_output.err
    assert not blocked_out.exists()
