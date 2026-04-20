from __future__ import annotations

import json
from pathlib import Path
import shutil

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.config import Settings
from tests.eval.cli import main as eval_cli_main
from tests.eval.metrics import aggregate_metrics, compare_baselines
from tests.eval.reporting import load_result_records
from tests.eval.runner.harness import EvalRuntime, load_dataset, run_case
from tests.eval.schema import EvalCase, EvalResult, JudgeVerdict, TrajectoryStep


class _FakeGraph:
    def invoke(self, payload, context=None, version=None):  # noqa: ARG002
        user_message = payload["messages"][-1].content
        if "README" in user_message:
            return {
                "messages": [
                    HumanMessage(content=user_message),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "tool-1",
                                "name": "read_file",
                                "args": {"path": "README.md"},
                            }
                        ],
                    ),
                    ToolMessage(content="Focus Agent is a compact Python starter project.", tool_call_id="tool-1"),
                    AIMessage(content="Focus Agent is a compact Python starter project."),
                ],
                "llm_calls": 1,
            }

        return {
            "messages": [
                HumanMessage(content=user_message),
                AIMessage(content="PING"),
            ],
            "llm_calls": 1,
        }


def test_run_case_extracts_trajectory_and_passes_rule_judge(monkeypatch):
    monkeypatch.setattr("tests.eval.runner.harness._build_isolated_graph", lambda runtime: _FakeGraph())
    case = EvalCase(
        id="repo-readme",
        input={"user_message": "Read the project README and summarize it."},
        expected={
            "answer_contains_any": ["Focus Agent"],
            "must_call_tools_any_order": ["read_file"],
            "max_tool_calls": 1,
        },
        tags=["smoke"],
    )
    runtime = EvalRuntime(settings=Settings(), tool_registry=None)  # type: ignore[arg-type]

    result = run_case(case, runtime=runtime)

    assert result.passed is True
    assert [step.tool for step in result.trajectory] == ["read_file"]
    assert result.metrics["tool_calls"] == 1


def test_aggregate_metrics_and_baseline_comparison_flag_regressions():
    baseline_results = [
        EvalResult(
            case_id="baseline-pass",
            passed=True,
            answer="ok",
            verdicts=[JudgeVerdict(kind="rule", passed=True)],
            metrics={"tool_calls": 1, "llm_calls": 1, "latency_ms": 100, "cost_usd": 0.01},
            tags=["smoke"],
        )
    ]
    current_results = [
        EvalResult(
            case_id="current-fail",
            passed=False,
            answer="bad",
            verdicts=[
                JudgeVerdict(
                    kind="rule",
                    passed=False,
                    details={"failures": ["called forbidden tools ['write_text_artifact']"]},
                )
            ],
            metrics={"tool_calls": 4, "llm_calls": 2, "latency_ms": 180, "cost_usd": 0.03},
            tags=["smoke"],
        )
    ]

    baseline = aggregate_metrics(baseline_results)
    current = aggregate_metrics(current_results)
    comparison = compare_baselines(baseline=baseline, current=current)

    assert comparison["regressions"]
    assert any("task_success dropped" in item for item in comparison["regressions"])
    assert any("forbidden tool violations grew" in item for item in comparison["regressions"])


def test_eval_cli_writes_reports_and_replays(monkeypatch, capsys):
    workspace_tmp = Path(".focus_agent/test_eval_framework")
    if workspace_tmp.exists():
        shutil.rmtree(workspace_tmp)
    workspace_tmp.mkdir(parents=True, exist_ok=True)

    dataset_path = workspace_tmp / "suite.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "id": "case-1",
                "input": {"user_message": "Reply with PING"},
                "expected": {"answer_contains_any": ["PING"]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = EvalResult(
        case_id="case-1",
        passed=True,
        answer="PING",
        verdicts=[JudgeVerdict(kind="rule", passed=True, reasoning="all good")],
        trajectory=[
            TrajectoryStep(tool="read_file", args={"path": "README.md"}, observation="ok")
        ],
        metrics={"tool_calls": 1, "llm_calls": 1, "latency_ms": 12.3, "cost_usd": 0.0},
        tags=["smoke"],
    )

    monkeypatch.setattr("tests.eval.cli.build_default_runtime", lambda settings=None: object())
    monkeypatch.setattr(
        "tests.eval.cli.load_dataset",
        lambda path: [
            EvalCase.from_dict(json.loads(dataset_path.read_text(encoding="utf-8").strip()))
        ],
    )
    monkeypatch.setattr(
        "tests.eval.cli.run_suite",
        lambda cases, runtime, concurrency, progress=None: [result],
    )

    report_json = workspace_tmp / "report.json"
    report_jsonl = workspace_tmp / "results.jsonl"
    report_html = workspace_tmp / "report.html"

    exit_code = eval_cli_main(
        [
            "--dataset",
            str(dataset_path),
            "--fail-if-regression",
            "--report-json",
            str(report_json),
            "--report-jsonl",
            str(report_jsonl),
            "--report-html",
            str(report_html),
        ]
    )

    assert exit_code == 0
    assert report_json.exists()
    assert report_jsonl.exists()
    assert report_html.exists()
    assert load_result_records(report_jsonl)[0]["case_id"] == "case-1"

    replay_code = eval_cli_main(["replay", "--from", str(report_jsonl), "--case-id", "case-1"])
    captured = capsys.readouterr()

    assert replay_code == 0
    assert "case_id=case-1" in captured.out


def test_smoke_dataset_guards_tool_policy_regressions():
    cases = {
        case.id: case
        for case in load_dataset(Path("tests/eval/datasets/smoke.jsonl"))
    }

    direct_writing = cases["gt_direct_writing_no_tools"]
    assert direct_writing.expected["max_tool_calls"] == 0
    assert "web_search" in direct_writing.expected["must_not_call_tools"]
    assert "write_text_artifact" in direct_writing.expected["must_not_call_tools"]

    direct_no_artifact = cases["gt_direct_writing_no_artifact"]
    assert direct_no_artifact.expected["max_tool_calls"] == 0
    assert "write_text_artifact" in direct_no_artifact.expected["must_not_call_tools"]

    workspace_lookup = cases["gt_workspace_lookup_no_web_for_tool_name"]
    assert workspace_lookup.expected["must_call_tools_any_order"] == ["search_code"]
    assert "web_search" in workspace_lookup.expected["must_not_call_tools"]
