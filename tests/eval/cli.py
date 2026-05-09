"""CLI entrypoint for the agent eval framework."""

from __future__ import annotations

import argparse
from dataclasses import replace
import inspect
import json
from pathlib import Path
import sys
import tomllib
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
from .runner import (
    build_default_runtime,
    build_harness_stability_runtime,
    load_dataset,
    run_suite,
)
from .schema import EvalCase, EvalResult
from .trajectory_replay import (
    ConvertedTrajectoryCase,
    build_replay_comparison,
    convert_trajectory_records,
    format_replay_comparison,
    load_trajectory_records,
    trajectory_record_failed,
    write_eval_cases_jsonl,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "replay":
        return _run_replay_command(args[1:])
    if args and args[0] == "promote":
        return _run_promote_command(args[1:])
    return _run_suite_command(args)


def _run_suite_command(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.eval")
    parser.add_argument("--suite", default="smoke", help="Named dataset under tests/eval/datasets/")
    parser.add_argument("--dataset", help="Explicit dataset path (.jsonl)")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--case-timeout",
        type=float,
        default=120.0,
        help="Per-case timeout in seconds. Use <=0 to disable.",
    )
    parser.add_argument("--model", help="Override Settings.model for this run")
    parser.add_argument("--matrix", help="TOML/JSON model matrix file for cross-model eval")
    parser.add_argument(
        "--retries",
        type=int,
        help="Additional attempts per case. Overrides case-level retries when set.",
    )
    parser.add_argument("--only-capability", help="Only run cases with this capability value")
    parser.add_argument("--risk-level", help="Only run cases with this risk_level value")
    parser.add_argument(
        "--emit-failures-dataset",
        help="Write failed base cases as replayable EvalCase JSONL skeletons.",
    )
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

    exit_code, _ = _execute_eval_cases(
        cases=cases,
        dataset_label=str(dataset_path),
        suite_label=args.suite,
        concurrency=args.concurrency,
        case_timeout=args.case_timeout,
        model=args.model,
        matrix=args.matrix,
        retries=args.retries,
        only_capability=args.only_capability,
        risk_level=args.risk_level,
        emit_failures_dataset=args.emit_failures_dataset,
        baseline=args.baseline,
        fail_if_regression=args.fail_if_regression,
        report_json=args.report_json,
        report_jsonl=args.report_jsonl,
        report_html=args.report_html,
    )
    return exit_code


def _execute_eval_cases(
    *,
    cases: list[EvalCase],
    dataset_label: str,
    suite_label: str,
    concurrency: int,
    case_timeout: float = 120.0,
    model: str | None = None,
    matrix: str | None = None,
    retries: int | None = None,
    only_capability: str | None = None,
    risk_level: str | None = None,
    emit_failures_dataset: str | None = None,
    baseline: str | None = None,
    fail_if_regression: bool = False,
    report_json: str | None = None,
    report_jsonl: str | None = None,
    report_html: str | None = None,
) -> tuple[int, list[EvalResult]]:
    cases = _filter_cases(cases, only_capability=only_capability, risk_level=risk_level)
    settings = Settings.from_env()
    if model:
        settings.model = model

    global_matrix = _load_model_matrix(matrix) if matrix else []
    print(
        f"[eval] dataset={dataset_label} cases={len(cases)} model={settings.model} "
        f"matrix={len(global_matrix) or 'case/default'} retries={retries if retries is not None else 'case/default'}"
    )
    results = _execute_model_runs(
        cases=cases,
        base_settings=settings,
        global_matrix=global_matrix,
        concurrency=max(1, concurrency),
        timeout_s=case_timeout,
        retries=retries,
    )
    summary = aggregate_metrics(results)
    baseline_summary = load_metric_summary(baseline) if baseline else None
    comparison = compare_baselines(baseline=baseline_summary, current=summary)

    print(
        json.dumps(
            {
                "dataset": dataset_label,
                "summary": summary.to_dict(),
                "regressions": comparison.get("regressions", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    meta = {
        "dataset": dataset_label,
        "suite": suite_label,
        "model": settings.model,
        "concurrency": max(1, concurrency),
        "case_timeout_s": case_timeout,
        "matrix": matrix,
        "retries": retries,
        "only_capability": only_capability,
        "risk_level": risk_level,
    }
    if report_json:
        write_json_report(
            report_json,
            summary=summary,
            results=results,
            comparison=comparison,
            meta=meta,
        )
        print(f"[eval] wrote JSON report to {report_json}")
    if report_jsonl:
        write_jsonl_results(report_jsonl, results)
        print(f"[eval] wrote JSONL results to {report_jsonl}")
    if report_html:
        write_html_report(
            report_html,
            summary=summary,
            results=results,
            comparison=comparison,
            title=f"Focus Agent Eval Report - {suite_label}",
        )
        print(f"[eval] wrote HTML report to {report_html}")
    if emit_failures_dataset:
        target = _write_failed_cases_dataset(
            emit_failures_dataset,
            cases=cases,
            results=results,
            suite_label=suite_label,
        )
        print(f"[eval] wrote failed cases dataset to {target}")

    if comparison.get("regressions") and (fail_if_regression or baseline):
        return 2, results
    return (0 if summary.failed == 0 else 1), results


def _run_replay_command(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.eval replay")
    parser.add_argument("--from", dest="source_path", required=True, help="JSON or JSONL result file")
    parser.add_argument("--case-id", help="Only replay one case id")
    parser.add_argument("--failed-only", action="store_true", help="Only show failed cases")
    parser.add_argument(
        "--trajectory-input",
        action="store_true",
        help="Treat --from as trajectory export JSON/JSONL instead of eval result records.",
    )
    parser.add_argument("--write-dataset", help="Write converted EvalCase JSONL to this path")
    parser.add_argument("--run", action="store_true", help="Execute converted trajectory cases through the eval runner")
    parser.add_argument("--case-id-prefix", default="traj", help="Prefix for generated EvalCase ids")
    parser.add_argument(
        "--copy-tool-trajectory",
        action="store_true",
        help="Seed expected tool-path expectations from the source trajectory when converting.",
    )
    parser.add_argument(
        "--copy-answer-substring",
        action="store_true",
        help="Seed answer_contains_any from the source answer when converting.",
    )
    parser.add_argument(
        "--answer-substring-chars",
        type=int,
        default=160,
        help="Max characters to keep when --copy-answer-substring is enabled.",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--model", help="Override Settings.model for this run")
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

    if args.trajectory_input:
        return _run_trajectory_replay(args)

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


def _run_trajectory_replay(args: argparse.Namespace) -> int:
    converted = _load_converted_trajectory_cases(
        args.source_path,
        case_id=args.case_id,
        failed_only=args.failed_only,
        case_id_prefix=args.case_id_prefix,
        copy_tool_trajectory=args.copy_tool_trajectory,
        copy_answer_substring=args.copy_answer_substring,
        answer_substring_chars=args.answer_substring_chars,
    )
    if not converted:
        print("[eval] no matching trajectory records found")
        return 1

    if args.write_dataset:
        dataset_path = write_eval_cases_jsonl(args.write_dataset, [item.case for item in converted])
        print(f"[eval] wrote replay dataset to {dataset_path}")

    if not args.run:
        for item in converted:
            source = item.source
            tools = ", ".join(step.get("tool", "") for step in source.get("trajectory", [])) or "-"
            print(
                f"case_id={item.case.id} trajectory_id={source.get('id')} "
                f"status={source.get('status')} tools={tools}"
            )
        return 0

    exit_code, replay_results = _execute_eval_cases(
        cases=[item.case for item in converted],
        dataset_label=str(args.source_path),
        suite_label="trajectory-replay",
        concurrency=args.concurrency,
        model=args.model,
        matrix=None,
        retries=None,
        only_capability=None,
        risk_level=None,
        emit_failures_dataset=None,
        baseline=args.baseline,
        fail_if_regression=args.fail_if_regression,
        report_json=args.report_json,
        report_jsonl=args.report_jsonl,
        report_html=args.report_html,
    )
    results_by_case_id = {result.case_id: result for result in replay_results}
    for item in converted:
        replay_result = results_by_case_id.get(item.case.id)
        if replay_result is None:
            continue
        comparison = build_replay_comparison(
            source_record=item.source,
            replay_result=replay_result,
        )
        print(format_replay_comparison(comparison))
        print("-" * 60)
    return exit_code


def _run_promote_command(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.eval promote")
    parser.add_argument("--from", dest="source_path", required=True, help="Trajectory export JSON or JSONL file")
    parser.add_argument("--out", required=True, help="Destination EvalCase JSONL path")
    parser.add_argument("--case-id", help="Only promote one generated case id or source trajectory id")
    parser.add_argument("--failed-only", action="store_true", help="Only promote failed trajectory turns")
    parser.add_argument("--case-id-prefix", default="traj", help="Prefix for generated EvalCase ids")
    parser.add_argument(
        "--copy-tool-trajectory",
        action="store_true",
        help="Seed expected tool-path expectations from the source trajectory.",
    )
    parser.add_argument(
        "--copy-answer-substring",
        action="store_true",
        help="Seed answer_contains_any from the source answer.",
    )
    parser.add_argument(
        "--answer-substring-chars",
        type=int,
        default=160,
        help="Max characters to keep when --copy-answer-substring is enabled.",
    )
    args = parser.parse_args(list(argv))

    converted = _load_converted_trajectory_cases(
        args.source_path,
        case_id=args.case_id,
        failed_only=args.failed_only,
        case_id_prefix=args.case_id_prefix,
        copy_tool_trajectory=args.copy_tool_trajectory,
        copy_answer_substring=args.copy_answer_substring,
        answer_substring_chars=args.answer_substring_chars,
    )
    if not converted:
        print("[eval] no matching trajectory records found")
        return 1

    target = write_eval_cases_jsonl(args.out, [item.case for item in converted])
    print(f"[eval] wrote promoted dataset to {target} cases={len(converted)}")
    return 0


def _load_converted_trajectory_cases(
    source_path: str,
    *,
    case_id: str | None,
    failed_only: bool,
    case_id_prefix: str,
    copy_tool_trajectory: bool,
    copy_answer_substring: bool,
    answer_substring_chars: int,
) -> list[ConvertedTrajectoryCase]:
    records = load_trajectory_records(source_path)
    if failed_only:
        records = [record for record in records if trajectory_record_failed(record)]
    converted = convert_trajectory_records(
        records,
        case_id_prefix=case_id_prefix,
        copy_tool_trajectory=copy_tool_trajectory,
        copy_answer_substring=copy_answer_substring,
        answer_substring_chars=answer_substring_chars,
    )
    if case_id:
        converted = [
            item
            for item in converted
            if item.case.id == case_id or str(item.source.get("id") or "") == case_id
        ]
    return converted


def _resolve_dataset_path(suite: str, explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser()
    dataset_dir = Path(__file__).resolve().parent / "datasets"
    return dataset_dir / f"{suite}.jsonl"


def _filter_cases(
    cases: list[EvalCase],
    *,
    only_capability: str | None,
    risk_level: str | None,
) -> list[EvalCase]:
    filtered = cases
    if only_capability:
        filtered = [case for case in filtered if case.capability == only_capability]
    if risk_level:
        filtered = [case for case in filtered if case.risk_level == risk_level]
    return filtered


def _execute_model_runs(
    *,
    cases: list[EvalCase],
    base_settings: Settings,
    global_matrix: list[dict[str, str]],
    concurrency: int,
    timeout_s: float,
    retries: int | None,
) -> list[EvalResult]:
    if not cases:
        return []
    if global_matrix:
        results: list[EvalResult] = []
        for variant in global_matrix:
            runtime = _runtime_for_model(base_settings, variant["model"])
            results.extend(
                _run_suite_compat(
                    cases,
                    runtime=runtime,
                    concurrency=concurrency,
                    retries=retries,
                    timeout_s=timeout_s,
                    model_label=variant["label"],
                    model_name=variant["model"],
                    progress=_print_progress,
                )
            )
        return results

    if any(case.model_matrix for case in cases):
        results = []
        for case in cases:
            variants = _case_model_variants(case, default_model=base_settings.model)
            for variant in variants:
                runtime = _runtime_for_model(base_settings, variant["model"])
                results.extend(
                    _run_suite_compat(
                        [case],
                        runtime=runtime,
                        concurrency=1,
                        retries=retries,
                        timeout_s=timeout_s,
                        model_label=variant["label"],
                        model_name=variant["model"],
                        progress=_print_progress,
                    )
                )
        return results

    runtime = _runtime_for_suite(cases=cases, base_settings=base_settings)
    return _run_suite_compat(
        cases,
        runtime=runtime,
        concurrency=concurrency,
        retries=retries,
        timeout_s=timeout_s,
        progress=_print_progress,
    )


def _runtime_for_suite(*, cases: list[EvalCase], base_settings: Settings):
    if cases and all("harness" in case.tags and "stability" in case.tags for case in cases):
        return build_harness_stability_runtime(settings=base_settings)
    return build_default_runtime(settings=base_settings)


def _runtime_for_model(base_settings: Settings, model: str):
    settings = Settings.from_env()
    settings.model = model or base_settings.model
    return build_default_runtime(settings=settings)


def _run_suite_compat(cases: list[EvalCase], **kwargs) -> list[EvalResult]:
    """Call run_suite while tolerating tests that monkey-patch the old signature."""
    signature = inspect.signature(run_suite)
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        return run_suite(cases, **kwargs)
    supported = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return run_suite(cases, **supported)


def _print_progress(result: EvalResult) -> None:
    print(
        f"[{'PASS' if result.passed else 'FAIL'}] {result.case_id} "
        f"model={result.metrics.get('model') or '-'} "
        f"tools={result.metrics.get('tool_calls', 0)} "
        f"latency_ms={round(float(result.metrics.get('latency_ms', 0.0)), 1)}"
    )


def _case_model_variants(case: EvalCase, *, default_model: str) -> list[dict[str, str]]:
    if not case.model_matrix:
        return [{"label": "default", "model": default_model}]
    variants: list[dict[str, str]] = []
    for index, item in enumerate(case.model_matrix, start=1):
        model = str(item.get("model") or default_model).strip()
        label = str(item.get("label") or item.get("role") or f"model_{index}").strip()
        variants.append({"label": label or f"model_{index}", "model": model})
    return variants


def _load_model_matrix(path: str) -> list[dict[str, str]]:
    source = Path(path).expanduser()
    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
    else:
        payload = tomllib.loads(source.read_text(encoding="utf-8"))
    raw_items: object
    if isinstance(payload, dict):
        raw_items = payload.get("models") or payload.get("model_matrix") or payload.get("matrix")
    else:
        raw_items = payload
    if not isinstance(raw_items, list):
        raise ValueError(f"model matrix must contain a list under models/model_matrix/matrix: {source}")
    variants: list[dict[str, str]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"model matrix item #{index} must be an object")
        model_name = str(item.get("model") or "").strip()
        if not model_name:
            raise ValueError(f"model matrix item #{index} is missing model")
        label = str(item.get("label") or item.get("role") or f"model_{index}").strip()
        variants.append({"label": label or f"model_{index}", "model": model_name})
    return variants


def _write_failed_cases_dataset(
    path: str,
    *,
    cases: list[EvalCase],
    results: list[EvalResult],
    suite_label: str,
) -> Path:
    case_by_id = {case.id: case for case in cases}
    failed_base_ids = []
    for result in results:
        if result.passed:
            continue
        base_id = str(result.metrics.get("base_case_id") or result.case_id).split("::", 1)[0]
        if base_id not in failed_base_ids:
            failed_base_ids.append(base_id)
    failed_cases: list[EvalCase] = []
    for base_id in failed_base_ids:
        case = case_by_id.get(base_id)
        if case is None:
            continue
        failed_cases.append(
            replace(
                case,
                origin={
                    **dict(case.origin or {}),
                    "type": "eval_failure",
                    "suite": suite_label,
                    "source_case_id": case.id,
                },
            )
        )
    return write_eval_cases_jsonl(path, failed_cases)


if __name__ == "__main__":
    raise SystemExit(main())
