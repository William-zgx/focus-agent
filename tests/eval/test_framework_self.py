"""Self-tests for the eval framework.

These tests assert the framework itself is correct by running the harness
against a scripted fake model. They deliberately DO NOT hit any real LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain.messages import AIMessage
from langchain.tools import tool as langchain_tool

from .judges import RuleJudge, TrajectoryJudge
from .metrics import aggregate_metrics, compare_baselines
from .reporting import (
    load_metric_summary,
    write_html_report,
    write_json_report,
    write_jsonl_results,
)
from .runner import load_dataset, run_case, run_suite
from .schema import EvalCase, TrajectoryStep


def _direct_answer_script(messages, allow_tools):  # noqa: ARG001
    return AIMessage(content="ReAct 把 reasoning 与 act 交替进行，使模型边思考边用工具。")


def _tool_then_answer_script(messages, allow_tools):
    if allow_tools and not any(
        isinstance(m, AIMessage) and getattr(m, "tool_calls", None) for m in messages
    ):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "search_code",
                    "args": {"query": "assemble_context"},
                }
            ],
        )
    return AIMessage(content="在 graph_builder.py 和 context_policy.py 中使用 assemble_context。")


@langchain_tool
def search_code(query: str = "") -> str:  # type: ignore[no-untyped-def]
    """Fake search_code tool."""
    return f'{{"query": "{query}", "hits": ["graph_builder.py:1", "context_policy.py:2"]}}'


def test_rule_judge_passes_when_answer_matches():
    case = EvalCase.from_dict(
        {
            "id": "unit_rule_pass",
            "input": {"user_message": "x"},
            "expected": {"answer_contains_any": ["hello"]},
        }
    )
    verdict = RuleJudge().evaluate(case=case, answer="hello world", trajectory=[])
    assert verdict.passed


def test_rule_judge_normalizes_unicode_hyphens():
    case = EvalCase.from_dict(
        {
            "id": "unit_rule_unicode_hyphen",
            "input": {"user_message": "x"},
            "expected": {"answer_contains_all": ["self-repair"]},
        }
    )
    verdict = RuleJudge().evaluate(case=case, answer="self\u2011repair preview", trajectory=[])
    assert verdict.passed


def test_rule_judge_matches_hyphenated_terms_with_spaces():
    case = EvalCase.from_dict(
        {
            "id": "unit_rule_hyphen_space",
            "input": {"user_message": "x"},
            "expected": {"answer_contains_all": ["self-repair"]},
        }
    )
    verdict = RuleJudge().evaluate(case=case, answer="self repair preview", trajectory=[])
    assert verdict.passed


def test_rule_judge_catches_forbidden_tool():
    case = EvalCase.from_dict(
        {
            "id": "unit_rule_forbidden",
            "input": {"user_message": "x"},
            "expected": {"must_not_call_tools": ["web_search"]},
        }
    )
    traj = [TrajectoryStep(tool="web_search", args={}, observation="{}")]
    verdict = RuleJudge().evaluate(case=case, answer="anything", trajectory=traj)
    assert not verdict.passed
    assert "forbidden" in verdict.reasoning


def test_trajectory_judge_enforces_max_tool_calls():
    case = EvalCase.from_dict(
        {
            "id": "unit_traj_max",
            "input": {"user_message": "x"},
            "expected": {"max_tool_calls": 1},
        }
    )
    steps = [TrajectoryStep(tool="a", args={}, observation=""), TrajectoryStep(tool="b", args={}, observation="")]
    verdict = TrajectoryJudge().evaluate(case=case, answer="", trajectory=steps)
    assert not verdict.passed


def test_trajectory_judge_enforces_runtime_count_expectations():
    case = EvalCase.from_dict(
        {
            "id": "unit_traj_runtime_counts",
            "input": {"user_message": "x"},
            "expected": {
                "min_cache_hits": 1,
                "max_fallback_uses": 0,
                "min_parallel_tool_calls": 1,
            },
        }
    )
    steps = [
        TrajectoryStep(
            tool="search_code",
            args={},
            observation="",
            cache_hit=True,
            parallel_batch_size=2,
        )
    ]

    verdict = TrajectoryJudge().evaluate(case=case, answer="", trajectory=steps)

    assert verdict.passed
    assert "cache_hits" in verdict.details["checks_run"]


def test_trajectory_judge_enforces_runtime_tool_membership_expectations():
    case = EvalCase.from_dict(
        {
            "id": "unit_traj_runtime_tools",
            "input": {"user_message": "x"},
            "expected": {
                "must_hit_cache_tools_any_order": ["search_code"],
                "must_use_fallback_tools_any_order": ["web_search"],
                "must_parallelize_tools_any_order": ["read_file"],
            },
        }
    )
    steps = [
        TrajectoryStep(tool="search_code", args={}, observation="", cache_hit=True),
        TrajectoryStep(tool="web_search", args={}, observation="", fallback_used=True),
        TrajectoryStep(tool="read_file", args={}, observation="", parallel_batch_size=2),
    ]

    verdict = TrajectoryJudge().evaluate(case=case, answer="", trajectory=steps)

    assert verdict.passed
    assert "must_use_fallback_tools_any_order" in verdict.details["checks_run"]


def test_dataset_loader_parses_jsonl():
    cases = load_dataset(Path(__file__).parent / "datasets" / "smoke.jsonl")
    assert cases
    assert all(c.id for c in cases)


def test_run_case_direct_answer(eval_runtime_factory):
    case = EvalCase.from_dict(
        {
            "id": "e2e_direct",
            "input": {"user_message": "用一句话说明 ReAct"},
            "expected": {
                "answer_contains_any": ["reasoning", "act"],
                "max_tool_calls": 0,
            },
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
    )
    runtime = eval_runtime_factory(script=_direct_answer_script)
    result = run_case(case, runtime=runtime)
    assert result.passed, result.verdicts
    assert result.metrics["tool_calls"] == 0
    assert result.metrics["llm_calls"] >= 1
    assert "ReAct" in result.answer or "reasoning" in result.answer


def test_run_case_with_tool_call(eval_runtime_factory):
    case = EvalCase.from_dict(
        {
            "id": "e2e_tool",
            "input": {"user_message": "在仓库里找 assemble_context"},
            "expected": {
                "must_call_tools_any_order": ["search_code"],
                "answer_contains_any": ["graph_builder"],
                "max_tool_calls": 2,
            },
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
    )
    runtime = eval_runtime_factory(script=_tool_then_answer_script, tools=[search_code])
    result = run_case(case, runtime=runtime)
    assert result.passed, [v.reasoning for v in result.verdicts]
    assert [s.tool for s in result.trajectory] == ["search_code"]


def test_run_case_runs_trajectory_judge_for_runtime_only_expectations(eval_runtime_factory):
    def _runtime_script(messages, allow_tools):
        if allow_tools and not any(
            isinstance(m, AIMessage) and getattr(m, "tool_calls", None) for m in messages
        ):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "search_code",
                        "args": {"query": "assemble_context"},
                    }
                ],
            )
        return AIMessage(content="done")

    runtime = eval_runtime_factory(script=_runtime_script, tools=[search_code])
    case = EvalCase.from_dict(
        {
            "id": "e2e_runtime_expectation",
            "input": {"user_message": "在仓库里找 assemble_context"},
            "expected": {
                "must_hit_cache_tools_any_order": [],
                "max_fallback_uses": 0,
            },
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
    )

    result = run_case(case, runtime=runtime)

    trajectory_verdicts = [verdict for verdict in result.verdicts if verdict.kind == "trajectory"]
    assert trajectory_verdicts
    assert trajectory_verdicts[0].passed


def test_run_suite_aggregates_metrics(eval_runtime_factory):
    cases = [
        EvalCase.from_dict(
            {
                "id": f"bulk_{i}",
                "input": {"user_message": "hi"},
                "expected": {"answer_contains_any": ["reasoning", "act"]},
                "judge": {"rule": True, "llm": {"enabled": False}},
            }
        )
        for i in range(3)
    ]
    runtime = eval_runtime_factory(script=_direct_answer_script)
    results = run_suite(cases, runtime=runtime, concurrency=1)
    summary = aggregate_metrics(results)
    assert summary.total == 3
    assert summary.passed == 3
    assert summary.task_success == 1.0


def test_compare_baselines_flags_regression():
    base = aggregate_metrics([])
    base.task_success = 0.90
    base.avg_cost_usd = 0.01
    cur = aggregate_metrics([])
    cur.task_success = 0.80
    cur.avg_cost_usd = 0.01
    diff = compare_baselines(baseline=base, current=cur)
    assert any("task_success" in r for r in diff["regressions"])


def test_reports_write_files(tmp_path, eval_runtime_factory):
    case = EvalCase.from_dict(
        {
            "id": "e2e_report",
            "input": {"user_message": "hi"},
            "expected": {"answer_contains_any": ["reasoning"]},
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
    )
    runtime = eval_runtime_factory(script=_direct_answer_script)
    results = run_suite([case], runtime=runtime, concurrency=1)
    summary = aggregate_metrics(results)

    json_path = tmp_path / "report.json"
    jsonl_path = tmp_path / "report.jsonl"
    html_path = tmp_path / "report.html"
    write_json_report(json_path, summary=summary, results=results, meta={"suite": "unit"})
    write_jsonl_results(jsonl_path, results)
    write_html_report(html_path, summary=summary, results=results)

    loaded = load_metric_summary(json_path)
    assert loaded.total == summary.total
    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["total"] == 1
    assert jsonl_path.read_text(encoding="utf-8").strip().startswith("{")
    assert "<html" in html_path.read_text(encoding="utf-8").lower()
