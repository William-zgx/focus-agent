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
