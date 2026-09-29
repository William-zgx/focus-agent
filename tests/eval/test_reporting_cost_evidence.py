from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.eval.metrics import aggregate_metrics
from tests.eval.reporting import write_html_report, write_json_report
from tests.eval.schema import EvalResult


def _result(case_id: str, **metrics: Any) -> EvalResult:
    return EvalResult(case_id=case_id, passed=True, answer="ok", metrics=metrics)


def test_unknown_usage_is_null_and_explicitly_unknown_in_reports(tmp_path: Path) -> None:
    result = _result(
        "unknown",
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
        cost_status="unknown",
        model_label="fake",
        model="fake",
    )
    summary = aggregate_metrics([result])
    payload = summary.to_dict()

    assert payload["avg_input_tokens"] is None
    assert payload["avg_output_tokens"] is None
    assert payload["input_tokens_known_count"] == 0
    assert payload["input_tokens_unknown_count"] == 1
    assert payload["output_tokens_known_count"] == 0
    assert payload["output_tokens_unknown_count"] == 1
    assert payload["avg_cost_usd"] is None
    assert payload["cost_known_count"] == 0
    assert payload["cost_unknown_count"] == 1
    assert payload["model_matrix"]["fake"]["avg_cost_usd"] is None

    json_path = write_json_report(
        tmp_path / "report.json",
        summary=summary,
        results=[result],
    )
    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["avg_cost_usd"] is None

    html_path = write_html_report(tmp_path / "report.html", summary=summary, results=[result])
    html = html_path.read_text(encoding="utf-8")
    assert '<td class="nowrap">unknown</td></tr>' in html


def test_mixed_usage_averages_only_known_evidence_and_preserves_counts() -> None:
    known = _result(
        "known",
        input_tokens=100,
        output_tokens=20,
        cost_usd=0.0,
        cost_status="measured",
        model_label="fake",
        model="fake",
    )
    unknown = _result(
        "unknown",
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
        cost_status="unknown",
        model_label="fake",
        model="fake",
    )

    payload = aggregate_metrics([known, unknown]).to_dict()

    assert payload["avg_input_tokens"] == 100.0
    assert payload["avg_output_tokens"] == 20.0
    assert payload["input_tokens_known_count"] == 1
    assert payload["input_tokens_unknown_count"] == 1
    assert payload["output_tokens_known_count"] == 1
    assert payload["output_tokens_unknown_count"] == 1
    assert payload["avg_cost_usd"] == 0.0
    assert payload["cost_known_count"] == 1
    assert payload["cost_unknown_count"] == 1
    assert payload["model_matrix"]["fake"]["avg_cost_usd"] == 0.0


def test_known_zero_usage_and_cost_remain_zero() -> None:
    payload = aggregate_metrics(
        [
            _result(
                "zero",
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                cost_status="measured",
            )
        ]
    ).to_dict()

    assert payload["avg_input_tokens"] == 0.0
    assert payload["avg_output_tokens"] == 0.0
    assert payload["avg_cost_usd"] == 0.0
    assert payload["input_tokens_known_count"] == 1
    assert payload["output_tokens_known_count"] == 1
    assert payload["cost_known_count"] == 1
