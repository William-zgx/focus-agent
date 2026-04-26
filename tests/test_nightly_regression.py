from __future__ import annotations

import json
from pathlib import Path

from scripts import nightly_regression


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


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
            "trend": [{"stage": "candidate", "pollution_rate": 1.0}],
            "promotion_history": {"candidate_total": 1, "reviewed_total": 0},
            "pollution_alerts": [{"kind": "irrelevant_memory_pollution", "stage": "candidate"}],
        },
    )
    _write_json(
        replay,
        {
            "meta": {"suite": "trajectory_replay"},
            "summary": {"total": 2, "failed": 1},
            "results": [{"case_id": "case-ok", "passed": True}, {"case_id": "case-bad", "passed": False}],
        },
    )
    _write_json(alert, {"status": "alert", "alerts": [{"kind": "budget"}]})
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
    memory_eval = tmp_path / "memory-eval.json"
    memory_trend = tmp_path / "memory-trend.json"
    report_json = tmp_path / "nightly.json"
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

    exit_code = nightly_regression.main(
        [
            "--report-json",
            str(report_json),
            "--memory-eval-json",
            str(memory_eval),
            "--memory-trend-json",
            str(memory_trend),
            "--history-dir",
            str(tmp_path / "history"),
        ]
    )
    stdout = json.loads(capsys.readouterr().out)
    report = json.loads(report_json.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert stdout["status"] == "passed"
    assert stdout["baseline_status"] == "missing"
    assert stdout["report_json"] == str(report_json)
    assert report["meta"]["golden_write"] == "disabled"
    assert report["summary"]["missing_artifacts"] == 0
    assert report["history"]["append"]["status"] == "written"
    assert nightly_regression.DEFAULT_REPORT_JSON == Path("reports/nightly/latest.json")


def test_nightly_report_fails_closed_when_required_memory_artifacts_are_missing(tmp_path: Path) -> None:
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
    report = json.loads(target.read_text(encoding="utf-8"))
    history_files = sorted(history_dir.glob("*.json"))
    history_entry = json.loads(history_files[0].read_text(encoding="utf-8"))

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
    assert next_report["delta"]["numeric"]["alert_count"] == {"current": 0, "delta": 0, "previous": 0}
