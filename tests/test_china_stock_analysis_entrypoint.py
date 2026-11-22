from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).parents[1] / ".focus_agent/skills/china-stock-analysis/scripts/run_analysis.py"
)
_SPEC = importlib.util.spec_from_file_location("stock_analysis_entrypoint", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
entrypoint = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(entrypoint)


def test_highlights_match_child_output_schemas(tmp_path):
    financial_path = tmp_path / "financial_analysis.json"
    valuation_path = tmp_path / "valuation.json"
    financial_path.write_text(
        json.dumps(
            {
                "score": 88,
                "anomalies": {"risk_level": "中"},
                "profitability": {"assessment": "盈利能力良好"},
            }
        ),
        encoding="utf-8",
    )
    valuation_path.write_text(
        json.dumps(
            {
                "summary": {
                    "平均内在价值": 12.5,
                    "当前价格": 10.0,
                    "投资结论": "仅供研究参考",
                }
            }
        ),
        encoding="utf-8",
    )

    assert entrypoint._highlights(
        financial_analysis_path=financial_path,
        valuation_path=valuation_path,
    ) == {
        "financial_score": 88,
        "financial_risk_level": "中",
        "financial_profitability_assessment": "盈利能力良好",
        "valuation_intrinsic_value": 12.5,
        "valuation_current_price": 10.0,
        "valuation_recommendation": "仅供研究参考",
    }


def test_highlights_omit_unavailable_values(tmp_path):
    financial_path = tmp_path / "financial_analysis.json"
    valuation_path = tmp_path / "valuation.json"
    financial_path.write_text("{}", encoding="utf-8")
    valuation_path.write_text('{"summary": {}}', encoding="utf-8")

    assert (
        entrypoint._highlights(
            financial_analysis_path=financial_path,
            valuation_path=valuation_path,
        )
        == {}
    )
