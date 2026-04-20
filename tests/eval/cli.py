"""CLI entrypoint for the agent eval framework."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from focus_agent.config import Settings

from .metrics import aggregate_metrics, compare_baselines
from .reporting import (
    load_metric_summary,
    load_result_records,
    write_html_report,
    write_json_report,
    write_jsonl_results,
)
from .runner import build_default_runtime, load_dataset, run_suite


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "replay":
        return _run_replay_command(args[1:])
    return _run_suite_command(args)


def _run_suite_command(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.eval")
    parser.add_argument("--suite", default="smoke", help="Named dataset under tests/eval/datasets/")
    parser.add_argument("--dataset", help="Explicit dataset path (.jsonl)")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--model", help="Override Settings.model for this run")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--baseline", help="Path to a prior JSON report for regression comparison")
    parser.add_argument(
        "--fail-if-regression",
        action="store_true",
        help="Exit with code 2 when the baseline comparison flags regressions.",
    )
    parser.add_argument("--report-json", help="Write a structured JSON report")
    parser.add_argument("--report-jsonl", help="Write per-case results as JSONL")
    parser.add_argument("--report-html", help="Write an HTML report")
    args = parser.parse_args(list(argv))

    dataset_path = _resolve_dataset_path(args.suite, args.dataset)
    cases = load_dataset(dataset_path)
    if args.max_cases > 0:
        cases = cases[: args.max_cases]

    settings = Settings.from_env()
    if args.model:
        settings.model = args.model
    runtime = build_default_runtime(settings=settings)

    print(f"[eval] dataset={dataset_path} cases={len(cases)} model={settings.model}")
    results = run_suite(
        cases,
        runtime=runtime,
        concurrency=max(1, args.concurrency),
        progress=lambda result: print(
            f"[{'PASS' if result.passed else 'FAIL'}] {result.case_id} "
            f"tools={result.metrics.get('tool_calls', 0)} "
            f"latency_ms={round(float(result.metrics.get('latency_ms', 0.0)), 1)}"
        ),
    )
    summary = aggregate_metrics(results)
    baseline = load_metric_summary(args.baseline) if args.baseline else None
    comparison = compare_baselines(baseline=baseline, current=summary)

    print(
        json.dumps(
            {
                "dataset": str(dataset_path),
                "summary": summary.to_dict(),
                "regressions": comparison.get("regressions", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    meta = {
        "dataset": str(dataset_path),
        "suite": args.suite,
        "model": settings.model,
        "concurrency": max(1, args.concurrency),
    }
    if args.report_json:
        write_json_report(
            args.report_json,
            summary=summary,
            results=results,
            comparison=comparison,
            meta=meta,
        )
        print(f"[eval] wrote JSON report to {args.report_json}")
    if args.report_jsonl:
        write_jsonl_results(args.report_jsonl, results)
        print(f"[eval] wrote JSONL results to {args.report_jsonl}")
    if args.report_html:
        write_html_report(
            args.report_html,
            summary=summary,
            results=results,
            comparison=comparison,
            title=f"Focus Agent Eval Report - {args.suite}",
        )
        print(f"[eval] wrote HTML report to {args.report_html}")

    if comparison.get("regressions") and (args.fail_if_regression or args.baseline):
        return 2
    return 0 if summary.failed == 0 else 1


def _run_replay_command(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.eval replay")
    parser.add_argument("--from", dest="source_path", required=True, help="JSON or JSONL result file")
    parser.add_argument("--case-id", help="Only replay one case id")
    parser.add_argument("--failed-only", action="store_true", help="Only show failed cases")
    args = parser.parse_args(list(argv))

    records = load_result_records(args.source_path)
    if args.case_id:
        records = [record for record in records if record.get("case_id") == args.case_id]
    if args.failed_only:
        records = [record for record in records if not bool(record.get("passed"))]

    if not records:
        print("[eval] no matching records found")
        return 1

    for record in records:
        tools = ", ".join(step.get("tool", "") for step in record.get("trajectory", [])) or "-"
        verdicts = record.get("verdicts") or []
        notes = "; ".join(
            f"{item.get('kind')}: {item.get('reasoning', '')}" for item in verdicts if item.get("reasoning")
        ) or (record.get("error") or "")
        print(f"case_id={record.get('case_id')} passed={record.get('passed')} tools={tools}")
        print(f"answer={record.get('answer', '')[:300]}")
        print(f"notes={notes[:300]}")
        print("-" * 60)
    return 0


def _resolve_dataset_path(suite: str, explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser()
    dataset_dir = Path(__file__).resolve().parent / "datasets"
    return dataset_dir / f"{suite}.jsonl"


if __name__ == "__main__":
    raise SystemExit(main())
