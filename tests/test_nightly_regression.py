from __future__ import annotations

import json
from pathlib import Path

from scripts import nightly_regression


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_cli(args: list[str], capsys) -> tuple[int, dict]:
    exit_code = nightly_regression.main(args)
    return exit_code, json.loads(capsys.readouterr().out)


def _write_passing_memory_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    memory_eval = tmp_path / "memory-eval.json"
    memory_trend = tmp_path / "memory-trend.json"
    _write_json(
        memory_eval,
        {
            "meta": {"suite": "memory_context_quality"},
            "summary": {"total": 1, "passed": 1, "failed": 0, "errors": 0},
        },
    )
    _write_json(
        memory_trend,
        {
            "meta": {"suite": "memory_context_regression_trend"},
            "status": "ok",
            "trend": [],
            "promotion_history": {},
            "pollution_alerts": [],
        },
    )
    return memory_eval, memory_trend


def test_nightly_report_aggregates_memory_replay_alerts_and_review(tmp_path: Path) -> None:
    memory_eval = tmp_path / "memory-eval.json"
    memory_trend = tmp_path / "memory-trend.json"
    replay = tmp_path / "replay.json"
    alert = tmp_path / "alerts.json"
    candidates = tmp_path / "candidates.jsonl"
    feedback = tmp_path / "feedback-regression.json"

    _write_json(
        memory_eval,
        {
            "meta": {"suite": "memory_context_quality"},
            "summary": {"total": 2, "passed": 2, "failed": 0, "errors": 0},
            "comparison": {"regressions": []},
        },
    )
    _write_json(
        memory_trend,
        {
            "meta": {"suite": "memory_context_regression_trend"},
            "status": "alert",
            "trend": [
                {
                    "stage": "candidate",
                    "pollution_rate": 1.0,
                    "context_compaction_drift_report": {
                        "recall": 0.5,
                        "precision": 1.0,
                        "grounding": 1.0,
                        "answerability": 0.5,
                        "overall_drift": 0.25,
                        "drift_risk": "medium",
                        "case_count": 1,
                    },
                }
            ],
            "promotion_history": {"candidate_total": 1, "reviewed_total": 0},
            "pollution_alerts": [{"kind": "irrelevant_memory_pollution", "stage": "candidate"}],
        },
    )
    _write_json(
        replay,
        {
            "meta": {"suite": "trajectory_replay"},
            "summary": {"total": 2, "failed": 1},
            "results": [
                {"case_id": "case-ok", "passed": True},
                {"case_id": "case-bad", "passed": False},
            ],
        },
    )
    _write_json(alert, {"status": "alert", "alerts": [{"kind": "budget"}]})
    _write_json(
        feedback,
        {
            "meta": {"suite": "feedback_regression"},
            "summary": {
                "status": "alert",
                "negative_feedback_count": 1,
                "merge_review_conflict_count": 2,
                "skill_low_confidence_count": 3,
                "skill_override_count": 4,
                "context_high_drift_count": 5,
                "notes_tasks_capture_count": 6,
                "top_failing_trajectory_sample_count": 7,
            },
            "feedback_pipeline": {
                "status": "alert",
                "negative_feedback": {"count": 1, "sample_ids": ["fb-1"]},
            },
        },
    )
    _write_jsonl(
        candidates,
        [
            {
                "id": "mc_candidate_1",
                "tags": ["memory_context", "candidate_import"],
                "input": {"rendered_context": "Use Postgres.", "answer": "Use Postgres."},
                "expected": {"required_facts": ["Postgres"]},
            },
            {
                "id": "mc_candidate_2",
                "tags": ["memory_context", "candidate_import"],
                "input": {"rendered_context": "Use branch tree.", "answer": "Use branch tree."},
                "expected": {"required_facts": ["branch tree"]},
            },
        ],
    )

    report = nightly_regression.build_nightly_report(
        memory_eval_json=memory_eval,
        memory_trend_json=memory_trend,
        replay_json=[replay],
        alert_json=[alert],
        candidate_review_jsonl=[candidates],
        candidate_approve_id=["mc_candidate_1"],
        feedback_report_json=feedback,
        history_dir=tmp_path / "history",
    )

    assert report["meta"]["suite"] == "nightly_regression"
    assert report["summary"]["status"] == "failed"
    assert report["summary"]["alert_count"] == 2
    assert report["summary"]["failed_replay_cases"] == 1
    assert report["artifacts"]["replay"][0]["failed_case_ids"] == ["case-bad"]
    assert report["memory_review"]["queue"]["approved"] == 1
    assert report["memory_review"]["queue"]["pending"] == 1
    assert report["memory_review"]["promoted_case_ids"] == ["mc_candidate_1"]
    assert report["summary"]["candidate_pipeline"]["candidate_total"] == 2
    assert report["summary"]["context_compaction_drift_report"]["overall_drift"] == 0.25
    assert report["summary"]["context_compaction_overall_drift_bp"] == 2500
    assert report["summary"]["candidate_pipeline"]["pending"] == 1
    assert report["summary"]["candidate_pipeline"]["promoted_count"] == 1
    assert report["summary"]["replay_pipeline"]["failed_replay_cases"] == 1
    assert report["summary"]["replay_pipeline"]["alert_count"] == 1
    assert report["summary"]["feedback_negative"] == 1
    assert report["summary"]["feedback_merge_review_conflicts"] == 2
    assert report["summary"]["feedback_skill_low_confidence"] == 3
    assert report["summary"]["feedback_skill_overrides"] == 4
    assert report["summary"]["feedback_context_high_drift"] == 5
    assert report["summary"]["feedback_notes_tasks_captures"] == 6
    assert report["summary"]["feedback_top_failing_trajectories"] == 7
    assert report["summary"]["feedback_pipeline"]["negative_feedback"]["sample_ids"] == ["fb-1"]
    assert report["artifacts"]["feedback_regression"]["path"] == str(feedback)
    assert report["candidate_outputs"]["golden_write"] == "disabled"
    assert report["candidate_outputs"]["promoted_case_ids"] == ["mc_candidate_1"]
    assert {item["kind"] for item in report["regressions"]} == {
        "memory_pollution_alert",
        "trajectory_replay_failure",
        "alert_report_signal",
    }
    assert set(report) == {
        "meta",
        "commands",
        "delta",
        "history",
        "artifacts",
        "memory_review",
        "regressions",
        "candidate_outputs",
        "summary",
        "baseline_status",
    }


def test_nightly_cli_writes_report_without_golden_mutation(tmp_path: Path, capsys) -> None:
    report_json = tmp_path / "nightly.json"
    memory_eval, memory_trend = _write_passing_memory_artifacts(tmp_path)

    exit_code, stdout = _run_cli(
        [
            "--report-json",
            str(report_json),
            "--memory-eval-json",
            str(memory_eval),
            "--memory-trend-json",
            str(memory_trend),
            "--history-dir",
            str(tmp_path / "history"),
        ],
        capsys,
    )
    report = _read_json(report_json)

    assert exit_code == 0
    assert stdout["status"] == "passed"
    assert stdout["baseline_status"] == "missing"
    assert stdout["report_json"] == str(report_json)
    assert report["meta"]["golden_write"] == "disabled"
    assert report["summary"]["missing_artifacts"] == 0
    assert report["history"]["append"]["status"] == "written"
    assert nightly_regression.DEFAULT_REPORT_JSON == Path("reports/nightly/latest.json")


def test_nightly_report_fails_closed_when_required_memory_artifacts_are_missing(
    tmp_path: Path,
) -> None:
    report = nightly_regression.build_nightly_report(
        memory_eval_json=tmp_path / "missing-eval.json",
        memory_trend_json=tmp_path / "missing-trend.json",
        history_dir=tmp_path / "history",
    )

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["missing_artifacts"] == 2


def test_nightly_report_marks_missing_history_without_failing_baseline(tmp_path: Path) -> None:
    memory_eval, memory_trend = _write_passing_memory_artifacts(tmp_path)

    report = nightly_regression.build_nightly_report(
        memory_eval_json=memory_eval,
        memory_trend_json=memory_trend,
        history_dir=tmp_path / "missing-history",
    )

    assert report["summary"]["status"] == "passed"
    assert report["baseline_status"] == "missing"
    assert report["summary"]["baseline_status"] == "missing"
    assert report["delta"]["baseline_status"] == "missing"
    assert report["history"]["source_count"] == 0


def test_nightly_report_builds_previous_to_latest_delta(tmp_path: Path) -> None:
    memory_eval, memory_trend = _write_passing_memory_artifacts(tmp_path)
    alert = tmp_path / "alerts.json"
    previous = tmp_path / "previous-nightly.json"
    _write_json(alert, {"status": "alert", "alerts": [{"kind": "budget"}]})
    _write_json(
        previous,
        {
            "meta": {"generated_at": "2026-04-25T00:00:00Z", "suite": "nightly_regression"},
            "summary": {
                "alert_count": 0,
                "failed_replay_cases": 0,
                "memory_eval_status": "passed",
                "memory_review_approved": 0,
                "memory_review_pending": 0,
                "memory_review_rejected": 0,
                "memory_trend_status": "ok",
                "missing_artifacts": 0,
                "status": "passed",
            },
        },
    )

    report = nightly_regression.build_nightly_report(
        memory_eval_json=memory_eval,
        memory_trend_json=memory_trend,
        alert_json=[alert],
        previous_report_json=previous,
        history_dir=tmp_path / "history",
    )

    assert report["baseline_status"] == "available"
    assert report["delta"]["baseline_generated_at"] == "2026-04-25T00:00:00Z"
    assert report["delta"]["numeric"]["alert_count"] == {"current": 1, "delta": 1, "previous": 0}
    assert report["delta"]["status"]["status"] == {
        "changed": True,
        "current": "alert",
        "previous": "passed",
    }
    assert report["history"]["previous_report_json"] == str(previous)


def test_nightly_write_appends_latest_summary_to_history(tmp_path: Path) -> None:
    memory_eval, memory_trend = _write_passing_memory_artifacts(tmp_path)
    report_json = tmp_path / "nightly" / "latest.json"
    history_dir = tmp_path / "nightly" / "history"

    target = nightly_regression.write_nightly_report(
        report_json,
        memory_eval_json=memory_eval,
        memory_trend_json=memory_trend,
        history_dir=history_dir,
    )
    report = _read_json(target)
    history_files = sorted(history_dir.glob("*.json"))
    history_entry = _read_json(history_files[0])

    assert len(history_files) == 1
    assert report["history"]["append"]["path"] == str(history_files[0])
    assert report["history"]["append"]["status"] == "written"
    assert history_entry["meta"]["source_report_json"] == str(report_json)
    assert history_entry["summary"]["status"] == "passed"
    assert history_entry["summary"]["baseline_status"] == "missing"

    next_report = nightly_regression.build_nightly_report(
        memory_eval_json=memory_eval,
        memory_trend_json=memory_trend,
        history_dir=history_dir,
    )

    assert next_report["baseline_status"] == "available"
    assert next_report["history"]["source_count"] == 1
    assert next_report["delta"]["numeric"]["alert_count"] == {
        "current": 0,
        "delta": 0,
        "previous": 0,
    }


def test_nightly_report_auto_discovers_default_replay_and_alert_entrypoints(
    tmp_path: Path, monkeypatch
) -> None:
    memory_eval, memory_trend = _write_passing_memory_artifacts(tmp_path)
    default_replay = tmp_path / "reports" / "nightly" / "trajectory-replay.json"
    default_alerts = tmp_path / "reports" / "nightly" / "alerts.json"
    default_replay.parent.mkdir(parents=True)
    _write_json(
        default_replay,
        {
            "meta": {"suite": "trajectory_replay"},
            "summary": {"total": 1, "failed": 0},
            "results": [{"case_id": "case-ok", "passed": True}],
        },
    )
    _write_json(default_alerts, {"status": "ok", "alerts": []})
    monkeypatch.setattr(
        nightly_regression,
        "DEFAULT_REPLAY_JSON",
        Path("reports/nightly/trajectory-replay.json"),
    )
    monkeypatch.setattr(
        nightly_regression,
        "DEFAULT_ALERT_JSON",
        Path("reports/nightly/alerts.json"),
    )
    monkeypatch.setattr(nightly_regression, "REPO_ROOT", tmp_path)

    report = nightly_regression.build_nightly_report(
        memory_eval_json=memory_eval,
        memory_trend_json=memory_trend,
        history_dir=tmp_path / "history",
    )
    commands = {command["label"]: command for command in report["commands"]}

    assert report["summary"]["status"] == "passed"
    assert report["artifacts"]["replay"][0]["path"] == str(default_replay)
    assert report["artifacts"]["alerts"][0]["path"] == str(default_alerts)
    assert commands["trajectory-replay"]["status"] == "available"
    assert commands["nightly-alerts"]["status"] == "available"


def test_nightly_report_auto_discovers_default_candidate_pipeline_and_delta(
    tmp_path: Path, monkeypatch
) -> None:
    memory_eval, memory_trend = _write_passing_memory_artifacts(tmp_path)
    candidate_jsonl = tmp_path / "reports" / "nightly" / "memory-context-candidates.jsonl"
    reviewed_jsonl = tmp_path / "reports" / "nightly" / "memory-context-reviewed.jsonl"
    promoted_jsonl = tmp_path / "reports" / "nightly" / "memory-context-promoted.jsonl"
    previous = tmp_path / "previous-nightly.json"
    candidate_jsonl.parent.mkdir(parents=True)
    candidate = {
        "id": "mc_candidate_old_pending",
        "tags": ["memory_context", "candidate_import"],
        "input": {
            "rendered_context": "Context mentions the Postgres path.",
            "answer": "Use the Postgres path.",
        },
        "expected": {"required_facts": ["Postgres path"]},
    }
    reviewed = {
        **candidate,
        "promotion_review": {
            "status": "pending",
            "approved": False,
            "sla": {
                "overdue": True,
                "reviewed_after_due": True,
            },
        },
    }
    _write_jsonl(candidate_jsonl, [candidate])
    _write_jsonl(reviewed_jsonl, [reviewed])
    _write_jsonl(promoted_jsonl, [])
    _write_json(
        previous,
        {
            "meta": {"generated_at": "2026-04-25T00:00:00Z", "suite": "nightly_regression"},
            "summary": {
                "alert_count": 0,
                "candidate_pending": 0,
                "candidate_promoted": 0,
                "candidate_reviewed": 0,
                "candidate_sla_overdue": 0,
                "candidate_total": 0,
                "failed_replay_cases": 0,
                "memory_eval_status": "passed",
                "memory_review_approved": 0,
                "memory_review_pending": 0,
                "memory_review_rejected": 0,
                "memory_trend_status": "ok",
                "missing_artifacts": 0,
                "status": "passed",
            },
        },
    )
    monkeypatch.setattr(nightly_regression, "DEFAULT_CANDIDATE_JSONL", Path("reports/nightly/memory-context-candidates.jsonl"))
    monkeypatch.setattr(nightly_regression, "DEFAULT_REVIEWED_JSONL", Path("reports/nightly/memory-context-reviewed.jsonl"))
    monkeypatch.setattr(nightly_regression, "DEFAULT_PROMOTED_JSONL", Path("reports/nightly/memory-context-promoted.jsonl"))
    monkeypatch.setattr(nightly_regression, "REPO_ROOT", tmp_path)

    report = nightly_regression.build_nightly_report(
        memory_eval_json=memory_eval,
        memory_trend_json=memory_trend,
        previous_report_json=previous,
        history_dir=tmp_path / "history",
    )

    pipeline = report["summary"]["candidate_pipeline"]
    assert pipeline["candidate_total"] == 1
    assert pipeline["reviewed_total"] == 1
    assert pipeline["pending"] == 1
    assert pipeline["sla_overdue"] == 1
    assert pipeline["promoted_count"] == 0
    assert pipeline["baseline_delta"]["candidate_total"] == 1
    assert report["summary"]["baseline_delta"]["candidate_sla_overdue"] == 1
    assert report["delta"]["numeric"]["candidate_pending"] == {
        "current": 1,
        "delta": 1,
        "previous": 0,
    }
    assert report["artifacts"]["candidate_pipeline"]["candidate"][0]["path"] == str(candidate_jsonl)


def test_nightly_report_keeps_replay_and_alert_entrypoints_not_configured_when_absent(
    tmp_path: Path,
) -> None:
    memory_eval, memory_trend = _write_passing_memory_artifacts(tmp_path)

    report = nightly_regression.build_nightly_report(
        memory_eval_json=memory_eval,
        memory_trend_json=memory_trend,
        replay_json=None,
        alert_json=None,
        history_dir=tmp_path / "history",
    )
    commands = {command["label"]: command for command in report["commands"]}

    assert report["summary"]["status"] == "passed"
    assert report["artifacts"]["replay"] == []
    assert report["artifacts"]["alerts"] == []
    assert commands["trajectory-replay"]["status"] == "not_configured"
    assert commands["nightly-alerts"]["status"] == "not_configured"
