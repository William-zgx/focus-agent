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
from tests.eval.trajectory_replay import build_replay_comparison, convert_trajectory_records


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
                    ToolMessage(
                        content="cached read",
                        tool_call_id="tool-unused",
                        artifact={"runtime": {"cache_hit": True}},
                    ),
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


def test_run_case_extracts_runtime_metadata_into_trajectory_and_metrics(monkeypatch):
    class _RuntimeGraph:
        def invoke(self, payload, context=None, version=None):  # noqa: ARG002
            user_message = payload["messages"][-1].content
            return {
                "messages": [
                    HumanMessage(content=user_message),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "tool-1",
                                "name": "web_search",
                                "args": {"query": "focus agent"},
                            }
                        ],
                    ),
                    ToolMessage(
                        content='{"provider":"duckduckgo"}',
                        tool_call_id="tool-1",
                        artifact={
                            "runtime": {
                                "cache_hit": True,
                                "fallback_used": True,
                                "fallback_group": "web_search",
                                "parallel_batch_size": 2,
                            }
                        },
                    ),
                    AIMessage(content="done"),
                ],
                "llm_calls": 1,
            }

    monkeypatch.setattr("tests.eval.runner.harness._build_isolated_graph", lambda runtime: _RuntimeGraph())
    runtime = EvalRuntime(settings=Settings(), tool_registry=None)  # type: ignore[arg-type]
    case = EvalCase(
        id="runtime-metrics",
        input={"user_message": "search focus agent"},
        expected={"must_call_tools_any_order": ["web_search"], "max_tool_calls": 1},
    )

    result = run_case(case, runtime=runtime)

    assert result.trajectory[0].cache_hit is True
    assert result.trajectory[0].fallback_used is True
    assert result.trajectory[0].fallback_group == "web_search"
    assert result.trajectory[0].parallel_batch_size == 2
    assert result.metrics["cache_hits"] == 1
    assert result.metrics["fallback_uses"] == 1
    assert result.metrics["parallel_tool_calls"] == 1


def test_aggregate_metrics_and_baseline_comparison_flag_regressions():
    baseline_results = [
        EvalResult(
            case_id="baseline-pass",
            passed=True,
            answer="ok",
            verdicts=[JudgeVerdict(kind="rule", passed=True)],
            metrics={"tool_calls": 1, "llm_calls": 1, "cache_hits": 1, "latency_ms": 100, "cost_usd": 0.01},
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
            metrics={"tool_calls": 4, "llm_calls": 2, "fallback_uses": 1, "latency_ms": 180, "cost_usd": 0.03},
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
            TrajectoryStep(tool="read_file", args={"path": "README.md"}, observation="ok", cache_hit=True)
        ],
        metrics={"tool_calls": 1, "llm_calls": 1, "cache_hits": 1, "latency_ms": 12.3, "cost_usd": 0.0},
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


def test_convert_trajectory_records_builds_replayable_eval_cases():
    converted = convert_trajectory_records(
        [
            {
                "id": "turn-1",
                "status": "failed",
                "thread_id": "thread-1",
                "root_thread_id": "root-1",
                "scene": "long_dialog_research",
                "user_message": "Read README",
                "answer": "README says Focus Agent is compact.",
                "branch_role": "research",
                "metrics": {"latency_ms": 42.0, "fallback_uses": 1},
                "trajectory": [
                    {"tool": "read_file", "args": {"path": "README.md"}},
                    {"tool": "web_search", "args": {"query": "focus agent"}},
                ],
            }
        ],
        case_id_prefix="obs",
        copy_tool_trajectory=True,
        copy_answer_substring=True,
        answer_substring_chars=12,
    )

    assert len(converted) == 1
    case = converted[0].case
    assert case.id == "obs-turn-1"
    assert case.input == {"user_message": "Read README"}
    assert case.expected["optimal_tool_sequence"] == ["read_file", "web_search"]
    assert case.expected["max_tool_calls"] == 2
    assert case.expected["answer_contains_any"] == ["README says"]
    assert case.origin["trajectory_id"] == "turn-1"
    assert case.origin["source_tools"] == ["read_file", "web_search"]
    assert "branch_role:research" in case.tags


def test_build_replay_comparison_reports_tool_path_and_runtime_diff():
    source_record = {
        "id": "turn-1",
        "status": "failed",
        "answer": "old answer",
        "metrics": {"latency_ms": 100, "fallback_uses": 1, "cache_hits": 0},
        "trajectory": [{"tool": "read_file"}, {"tool": "web_search"}],
    }
    replay_result = EvalResult(
        case_id="obs-turn-1",
        passed=True,
        answer="new answer",
        trajectory=[TrajectoryStep(tool="read_file", args={}, observation="ok")],
        metrics={"latency_ms": 55, "fallback_uses": 0, "cache_hits": 1},
    )

    comparison = build_replay_comparison(source_record, replay_result)

    assert comparison["source_failed"] is True
    assert comparison["tool_path_changed"] is True
    assert comparison["source_tools"] == ["read_file", "web_search"]
    assert comparison["replay_tools"] == ["read_file"]
    assert comparison["replay_cache_hits"] == 1


def test_eval_cli_replays_trajectory_exports_and_writes_dataset(monkeypatch, capsys):
    workspace_tmp = Path(".focus_agent/test_eval_framework_trajectory")
    if workspace_tmp.exists():
        shutil.rmtree(workspace_tmp)
    workspace_tmp.mkdir(parents=True, exist_ok=True)

    trajectory_path = workspace_tmp / "trajectory.jsonl"
    trajectory_path.write_text(
        json.dumps(
            {
                "id": "turn-1",
                "status": "failed",
                "thread_id": "thread-1",
                "root_thread_id": "root-1",
                "scene": "long_dialog_research",
                "user_message": "Read README",
                "answer": "old answer",
                "metrics": {"latency_ms": 33.0},
                "trajectory": [{"tool": "read_file", "args": {"path": "README.md"}}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    replay_dataset = workspace_tmp / "replay_cases.jsonl"

    replay_result = EvalResult(
        case_id="traj-turn-1",
        passed=True,
        answer="new answer",
        verdicts=[JudgeVerdict(kind="rule", passed=True, reasoning="all good")],
        trajectory=[TrajectoryStep(tool="read_file", args={"path": "README.md"}, observation="ok")],
        metrics={"tool_calls": 1, "llm_calls": 1, "cache_hits": 0, "latency_ms": 12.3, "cost_usd": 0.0},
    )

    monkeypatch.setattr("tests.eval.cli.build_default_runtime", lambda settings=None: object())
    monkeypatch.setattr(
        "tests.eval.cli.run_suite",
        lambda cases, runtime, concurrency, progress=None: [replay_result],
    )

    exit_code = eval_cli_main(
        [
            "replay",
            "--from",
            str(trajectory_path),
            "--trajectory-input",
            "--write-dataset",
            str(replay_dataset),
            "--run",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert replay_dataset.exists()
    dataset_record = json.loads(replay_dataset.read_text(encoding="utf-8").strip())
    assert dataset_record["id"] == "traj-turn-1"
    assert dataset_record["input"]["user_message"] == "Read README"
    assert "trajectory_id=turn-1" in captured.out
    assert "tools_before=read_file" in captured.out


def test_eval_cli_promote_trajectory_exports_to_dataset(capsys):
    workspace_tmp = Path(".focus_agent/test_eval_framework_promote")
    if workspace_tmp.exists():
        shutil.rmtree(workspace_tmp)
    workspace_tmp.mkdir(parents=True, exist_ok=True)

    trajectory_path = workspace_tmp / "trajectory.json"
    trajectory_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "turn-2",
                        "status": "failed",
                        "thread_id": "thread-2",
                        "root_thread_id": "root-2",
                        "scene": "long_dialog_research",
                        "user_message": "Search docs",
                        "answer": "Focus Agent docs",
                        "trajectory": [{"tool": "web_search", "args": {"query": "focus agent docs"}}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    promoted_path = workspace_tmp / "promoted.jsonl"

    exit_code = eval_cli_main(
        [
            "promote",
            "--from",
            str(trajectory_path),
            "--out",
            str(promoted_path),
            "--copy-tool-trajectory",
            "--copy-answer-substring",
            "--answer-substring-chars",
            "10",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(promoted_path.read_text(encoding="utf-8").strip())
    assert payload["id"] == "traj-turn-2"
    assert payload["expected"]["optimal_tool_sequence"] == ["web_search"]
    assert payload["expected"]["answer_contains_any"] == ["Focus Agen"]
    assert "wrote promoted dataset" in captured.out


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

    long_history_direct = cases["gt_long_history_direct_writing_no_tools"]
    assert long_history_direct.expected["max_tool_calls"] == 0
    assert long_history_direct.input["initial_state"]["context_budget"]["prompt_token_limit"] == 360

    workspace_lookup = cases["gt_workspace_lookup_no_web_for_tool_name"]
    assert workspace_lookup.expected["must_call_tools_any_order"] == ["search_code"]
    assert "web_search" in workspace_lookup.expected["must_not_call_tools"]
