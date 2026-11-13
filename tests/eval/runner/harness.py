"""Test-only dataset and suite orchestration for the production eval runner."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from focus_agent.config import Settings
from focus_agent.eval.runner.harness import (
    EvalRuntime,
    _failure_metrics,
    _result_case_id,
    build_default_runtime,
    run_case,
)

from ..schema import EvalCase, EvalResult, JudgeVerdict
from .metrics import _apply_suite_acceptance
from .stability import harness_stability_tools, make_harness_stability_model


def build_harness_stability_runtime(
    *,
    settings: Settings | None = None,
    cost_per_1k_input: float | None = None,
    cost_per_1k_output: float | None = None,
) -> EvalRuntime:
    """Build an offline runtime for the harness_stability release-gate suite."""

    return build_default_runtime(
        settings=settings,
        tools=harness_stability_tools(),
        model_factory=make_harness_stability_model,
        cost_per_1k_input=cost_per_1k_input,
        cost_per_1k_output=cost_per_1k_output,
    )


def load_dataset(path: str | Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"dataset not found: {p}")
    for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{p}:{line_no} invalid JSON: {exc}") from exc
        cases.append(EvalCase.from_dict(obj))
    return cases


def run_suite(
    cases: Iterable[EvalCase],
    *,
    runtime: EvalRuntime,
    concurrency: int = 4,
    retries: int | None = None,
    model_label: str | None = None,
    model_name: str | None = None,
    timeout_s: float = 120.0,
    progress: Callable[[EvalResult], None] | None = None,
) -> list[EvalResult]:
    cases = list(cases)
    work_items = _expand_attempts(cases, retries=retries)
    if concurrency <= 1 or len(work_items) <= 1:
        results = []
        for case, attempt, attempts in work_items:
            r = run_case(
                case,
                runtime=runtime,
                timeout_s=timeout_s,
                model_label=model_label,
                model_name=model_name,
                base_case_id=case.id,
                attempt=attempt,
                attempts=attempts,
            )
            results.append(r)
        results = _apply_suite_acceptance(results)
        if progress:
            for result in results:
                progress(result)
        return results

    results_by_id: dict[str, EvalResult] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(
                run_case,
                case,
                runtime=runtime,
                timeout_s=timeout_s,
                model_label=model_label,
                model_name=model_name,
                base_case_id=case.id,
                attempt=attempt,
                attempts=attempts,
            ): (case, attempt, attempts)
            for case, attempt, attempts in work_items
        }
        for fut in as_completed(futures):
            case, attempt, attempts = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                metrics = _failure_metrics(
                    case=case,
                    runtime=runtime,
                    latency_ms=None,
                    model_label=model_label,
                    model_name=model_name or runtime.settings.model,
                    base_case_id=case.id,
                    attempt=attempt,
                    attempts=attempts,
                )
                r = EvalResult(
                    case_id=_result_case_id(
                        case.id,
                        model_label=model_label,
                        attempt=attempt,
                        attempts=attempts,
                    ),
                    passed=False,
                    answer="",
                    verdicts=[
                        JudgeVerdict(
                            kind="harness", passed=False, reasoning=f"future failed: {exc!r}"
                        )
                    ],
                    metrics=metrics,
                    error=repr(exc),
                    tags=list(case.tags),
                )
            results_by_id[r.case_id] = r
    ordered_results = [
        results_by_id[
            _result_case_id(
                case.id,
                model_label=model_label,
                attempt=attempt,
                attempts=attempts,
            )
        ]
        for case, attempt, attempts in work_items
    ]
    ordered_results = _apply_suite_acceptance(ordered_results)
    if progress:
        for result in ordered_results:
            progress(result)
    return ordered_results


def _expand_attempts(
    cases: list[EvalCase],
    *,
    retries: int | None,
) -> list[tuple[EvalCase, int, int]]:
    work_items: list[tuple[EvalCase, int, int]] = []
    for case in cases:
        retry_count = case.retries if retries is None else max(0, int(retries))
        attempts = max(1, retry_count + 1)
        for attempt in range(1, attempts + 1):
            work_items.append((case, attempt, attempts))
    return work_items
