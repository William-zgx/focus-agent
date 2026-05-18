from __future__ import annotations

import json
from pathlib import Path

from scripts import feedback_regression


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_feedback_report_aggregates_governance_and_adoption_signals(tmp_path: Path) -> None:
    feedback_events = tmp_path / "feedback-events.jsonl"
    merge_reviews = tmp_path / "merge-reviews.json"
    skill_events = tmp_path / "skill-events.json"
    context_evidence = tmp_path / "context-evidence.json"
    productivity_captures = tmp_path / "captures.json"
    trajectory_report = tmp_path / "trajectory.json"

    _write_jsonl(
        feedback_events,
        [
            {
                "event_id": "fb-negative",
                "event_type": "chat_answer_feedback",
                "sentiment": "negative",
                "source_kind": "chat",
            },
            {
                "event_id": "fb-merge-conflict",
                "event_type": "agent_team_merge_review",
                "status": "conflict",
                "source_kind": "agent_team_merge_review",
            },
        ],
    )
    _write_json(
        merge_reviews,
        {
            "items": [
                {"review_id": "review-applied", "status": "applied"},
                {"review_id": "review-error", "status": "error"},
            ]
        },
    )
    _write_json(
        skill_events,
        {
            "events": [
                {"selection_id": "sel-low", "confidence": 0.4},
                {"selection_id": "sel-override", "confidence": 0.9, "user_override": {"removed": ["debug"]}},
            ]
        },
    )
    _write_json(
        context_evidence,
        {
            "items": [
                {
                    "evidence_id": "ctx-high",
                    "drift_report": {"overall_drift": 0.42, "drift_risk": "high"},
                }
            ]
        },
    )
    _write_json(
        productivity_captures,
        {"captures": [{"capture_id": "cap-note", "target_kind": "note"}]},
    )
    _write_json(
        trajectory_report,
        {
            "results": [
                {"case_id": "case-ok", "passed": True},
                {"case_id": "case-bad", "passed": False, "error": "missing context"},
            ]
        },
    )

    report = feedback_regression.build_feedback_report(
        feedback_events_json=[feedback_events],
        merge_review_json=[merge_reviews],
        skill_selection_json=[skill_events],
        context_evidence_json=[context_evidence],
        productivity_capture_json=[productivity_captures],
        trajectory_report_json=[trajectory_report],
    )

    assert report["meta"]["suite"] == "feedback_regression"
    assert report["summary"]["status"] == "alert"
    assert report["summary"]["negative_feedback_count"] == 1
    assert report["summary"]["merge_review_apply_success_count"] == 1
    assert report["summary"]["merge_review_conflict_count"] == 1
    assert report["summary"]["skill_low_confidence_count"] == 1
    assert report["summary"]["skill_override_count"] == 1
    assert report["summary"]["context_high_drift_count"] == 1
    assert report["summary"]["notes_tasks_capture_count"] == 1
    assert report["summary"]["top_failing_trajectory_sample_count"] == 1
    assert report["feedback_pipeline"]["trajectory_failures"]["top_failing_samples"][0]["case_id"] == "case-bad"


def test_feedback_cli_writes_non_blocking_report_for_missing_inputs(tmp_path: Path, capsys) -> None:
    report_json = tmp_path / "feedback-regression.json"

    exit_code = feedback_regression.main(["--report-json", str(report_json)])
    stdout = json.loads(capsys.readouterr().out)
    report = json.loads(report_json.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert stdout["status"] == "passed"
    assert stdout["report_json"] == str(report_json)
    assert report["summary"]["negative_feedback_count"] == 0
    assert all(item["status"] == "missing" for item in report["artifacts"]["feedback_events"])
