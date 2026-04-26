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
    assert report["summary"]["total"] == 5
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
