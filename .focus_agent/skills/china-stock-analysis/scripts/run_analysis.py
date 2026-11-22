#!/usr/bin/env python3
"""
Run the China A-stock analysis workflow end-to-end.

This script intentionally uses only the Python standard library. The child
scripts provide the domain logic and declare their own third-party imports.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="运行A股个股财报与估值组合分析")
    parser.add_argument("--code", required=True, help="股票代码，如 000063")
    parser.add_argument("--years", type=int, default=5, help="抓取财报年数")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    stock_data_path = output_dir / "stock_data.json"
    financial_analysis_path = output_dir / "financial_analysis.json"
    valuation_path = output_dir / "valuation.json"
    summary_path = output_dir / "summary.json"

    steps = [
        _run_step(
            "fetch_stock_data",
            [
                sys.executable,
                str(script_dir / "data_fetcher.py"),
                "--code",
                args.code,
                "--data-type",
                "all",
                "--years",
                str(args.years),
                "--output",
                str(stock_data_path),
            ],
        ),
    ]
    if steps[0]["exit_code"] == 0 and stock_data_path.exists():
        steps.extend(
            [
                _run_step(
                    "analyze_financials",
                    [
                        sys.executable,
                        str(script_dir / "financial_analyzer.py"),
                        "--input",
                        str(stock_data_path),
                        "--level",
                        "deep",
                        "--output",
                        str(financial_analysis_path),
                    ],
                ),
                _run_step(
                    "calculate_valuation",
                    [
                        sys.executable,
                        str(script_dir / "valuation_calculator.py"),
                        "--input",
                        str(stock_data_path),
                        "--methods",
                        "all",
                        "--output",
                        str(valuation_path),
                    ],
                ),
            ]
        )
    else:
        steps.extend(
            [
                _skipped_step("analyze_financials", "stock_data.json was not produced"),
                _skipped_step("calculate_valuation", "stock_data.json was not produced"),
            ]
        )

    status = "completed" if all(step["exit_code"] == 0 for step in steps) else "failed"
    summary = {
        "status": status,
        "code": args.code,
        "years": args.years,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "steps": steps,
        "outputs": {
            "stock_data": str(stock_data_path),
            "financial_analysis": str(financial_analysis_path),
            "valuation": str(valuation_path),
            "summary": str(summary_path),
        },
        "highlights": _highlights(
            financial_analysis_path=financial_analysis_path,
            valuation_path=valuation_path,
        ),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if status == "completed" else 1


def _run_step(name: str, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {
        "name": name,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _skipped_step(name: str, reason: str) -> dict[str, Any]:
    return {
        "name": name,
        "exit_code": 1,
        "stdout": "",
        "stderr": f"Skipped: {reason}",
    }


def _highlights(*, financial_analysis_path: Path, valuation_path: Path) -> dict[str, Any]:
    highlights: dict[str, Any] = {}
    financial = _read_json(financial_analysis_path)
    valuation = _read_json(valuation_path)
    if isinstance(financial, dict):
        if (score := financial.get("score")) is not None:
            highlights["financial_score"] = score
        for section, key, output_key in (
            ("anomalies", "risk_level", "financial_risk_level"),
            ("profitability", "assessment", "financial_profitability_assessment"),
        ):
            section_value = financial.get(section)
            if isinstance(section_value, dict) and (value := section_value.get(key)) is not None:
                highlights[output_key] = value
    if isinstance(valuation, dict) and isinstance(summary := valuation.get("summary"), dict):
        for key, output_key in (
            ("平均内在价值", "valuation_intrinsic_value"),
            ("当前价格", "valuation_current_price"),
            ("投资结论", "valuation_recommendation"),
        ):
            if (value := summary.get(key)) is not None:
                highlights[output_key] = value
    return highlights


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
