"""Unit + e2e tests for the Plan-Act-Reflect graph extension.

Uses the same scripted-model infrastructure as test_framework_self.py so the
whole loop runs without external LLMs.
"""

from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage, SystemMessage
from langchain.tools import tool as langchain_tool

from focus_agent.config import Settings
from focus_agent.core.types import Plan, PlanStep
from focus_agent.engine.graph_builder import (
    _format_plan_block,
    _parse_plan_json,
    _parse_reflection_json,
    _should_plan,
)

from .runner import run_case
from .schema import EvalCase


# ---- helpers ---------------------------------------------------------------


def _system_text(messages: list[Any]) -> str:
    for msg in messages:
        if isinstance(msg, SystemMessage):
            return str(getattr(msg, "content", ""))
    return ""


def _is_planner_call(messages: list[Any]) -> bool:
    return "任务规划器" in _system_text(messages)


def _is_reflect_call(messages: list[Any]) -> bool:
    return "计划审计员" in _system_text(messages)


@langchain_tool
def search_code(query: str = "") -> str:  # type: ignore[no-untyped-def]
    """Fake search_code tool used by plan/act/reflect e2e tests."""
    return f'{{"query": "{query}", "hits": ["graph_builder.py:1"]}}'


# ---- pure-function unit tests ---------------------------------------------


def test_should_plan_requires_more_than_scene_alone():
    """Scene whitelist is a *permission*, not a trigger on its own."""
    state = {"task_brief": "hi"}
    assert not _should_plan(
        state=state,
        scene="long_dialog_research",
        plan_scenes=("long_dialog_research",),
        min_chars=500,
    )


def test_should_plan_triggers_on_scene_plus_multi_step():
    state = {"task_brief": "先查找然后读取"}
    assert _should_plan(
        state=state,
        scene="long_dialog_research",
        plan_scenes=("long_dialog_research",),
        min_chars=500,
    )


def test_should_plan_triggers_on_long_brief():
    state = {"task_brief": "x" * 130}
    assert _should_plan(state=state, scene="other", plan_scenes=(), min_chars=120)


def test_should_plan_requires_scene_when_only_keyword():
    state = {"task_brief": "先找文件然后读取内容"}
    assert not _should_plan(state=state, scene="other", plan_scenes=(), min_chars=500)


def test_should_plan_skips_when_no_trigger():
    state = {"task_brief": "hi"}
    assert not _should_plan(state=state, scene="other", plan_scenes=(), min_chars=500)


def test_should_plan_retriggers_on_replan_request():
    plan = Plan(steps=[PlanStep(id="s1", goal="x")])
    state = {"task_brief": "hi", "plan": plan, "plan_meta": {"replan_requested": True}}
    assert _should_plan(state=state, scene="other", plan_scenes=(), min_chars=500)


def test_parse_plan_json_ok():
    raw = '{"steps": [{"id": "s1", "goal": "查找引用"}, {"id": "s2", "goal": "读取"}], "success_criteria": "列出路径"}'
    plan = _parse_plan_json(raw, created_at_call=1, replan_count=0)
    assert plan is not None
    assert len(plan.steps) == 2
    assert plan.steps[0].goal == "查找引用"
    assert plan.success_criteria == "列出路径"


def test_parse_plan_json_tolerates_fences():
    raw = "```json\n{\"steps\":[{\"id\":\"s1\",\"goal\":\"g\"}]}\n```"
    assert _parse_plan_json(raw, created_at_call=0, replan_count=0) is not None


def test_parse_plan_json_rejects_empty():
    assert _parse_plan_json("nonsense", created_at_call=0, replan_count=0) is None
    assert _parse_plan_json('{"steps": []}', created_at_call=0, replan_count=0) is None


def test_parse_reflection_json_ok():
    assert _parse_reflection_json('{"status": "done", "reasoning": "ok"}').status == "done"
    v = _parse_reflection_json('{"status": "replan", "missing": ["a"]}')
    assert v is not None and v.missing == ["a"]


def test_parse_reflection_json_rejects_invalid_status():
    assert _parse_reflection_json('{"status": "whatever"}') is None


def test_format_plan_block_renders_markers():
    plan = Plan(
        steps=[
            PlanStep(id="s1", goal="查", done=True),
            PlanStep(id="s2", goal="读"),
        ],
        success_criteria="done",
    )
    block = _format_plan_block(plan, current_step_id="s2")
    assert "✓" in block and "➤" in block and "[s2]" in block


# ---- e2e with scripted model ----------------------------------------------


def _plan_then_direct_answer_script(messages, allow_tools):  # noqa: ARG001
    if _is_planner_call(messages):
        return AIMessage(
            content='{"steps": [{"id": "s1", "goal": "解释 ReAct"}], "success_criteria": "包含 reasoning 和 act"}'
        )
    if _is_reflect_call(messages):
        return AIMessage(content='{"status": "done", "reasoning": "answer mentions both"}')
    return AIMessage(content="ReAct 把 reasoning 与 act 交替。")


def test_plan_act_reflect_happy_path(eval_runtime_factory):
    case = EvalCase.from_dict(
        {
            "id": "e2e_par_happy",
            "scene": "long_dialog_research",
            "input": {"user_message": "请先简述 ReAct 是什么，然后说明它的两个关键要素。"},
            "expected": {
                "answer_contains_any": ["reasoning", "act"],
                "max_tool_calls": 0,
            },
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
    )
    runtime = eval_runtime_factory(script=_plan_then_direct_answer_script)
    result = run_case(case, runtime=runtime)
    assert result.passed, [v.reasoning for v in result.verdicts]
    # plan + act + reflect = at least 3 LLM calls
    assert result.metrics["llm_calls"] >= 3


_replan_script_state: dict[str, int] = {"phase": 0}


def _plan_replan_then_done_script(messages, allow_tools):  # noqa: ARG001
    if _is_planner_call(messages):
        _replan_script_state["phase"] += 1
        if _replan_script_state["phase"] == 1:
            return AIMessage(
                content='{"steps": [{"id": "s1", "goal": "初步解释"}], "success_criteria": "包含 reasoning 和 act"}'
            )
        return AIMessage(
            content='{"steps": [{"id": "s1", "goal": "补充 reasoning"}, {"id": "s2", "goal": "补充 act"}], "success_criteria": "两词都出现"}'
        )
    if _is_reflect_call(messages):
        _replan_script_state["phase"] += 10
        # first reflect -> replan; second -> done
        if _replan_script_state["phase"] < 20:
            return AIMessage(content='{"status": "replan", "reasoning": "missing act", "missing": ["act"]}')
        return AIMessage(content='{"status": "done", "reasoning": "ok"}')
    # act: first pass answers vaguely, second adds both keywords
    if _replan_script_state["phase"] < 12:
        return AIMessage(content="大概是一种推理与工具结合的思路。")
    return AIMessage(content="ReAct 把 reasoning 与 act 交替。")


def test_plan_act_reflect_replan_once(eval_runtime_factory):
    _replan_script_state["phase"] = 0
    case = EvalCase.from_dict(
        {
            "id": "e2e_par_replan",
            "scene": "long_dialog_research",
            "input": {"user_message": "请先解释 ReAct 然后说明它的两个关键要素"},
            "expected": {
                "answer_contains_any": ["reasoning", "act"],
            },
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
    )
    runtime = eval_runtime_factory(script=_plan_replan_then_done_script)
    result = run_case(case, runtime=runtime)
    assert result.passed, [v.reasoning for v in result.verdicts]
    # 2 plans + 2 acts + 2 reflects = 6 LLM calls; allow some slack
    assert result.metrics["llm_calls"] >= 4


_replan_fallback_state: dict[str, int] = {"plan_calls": 0, "reflect_calls": 0, "act_calls": 0}


def _replan_parse_fail_falls_back_script(messages, allow_tools):  # noqa: ARG001
    if _is_planner_call(messages):
        _replan_fallback_state["plan_calls"] += 1
        if _replan_fallback_state["plan_calls"] == 1:
            return AIMessage(
                content='{"steps": [{"id": "s1", "goal": "先尝试回答"}], "success_criteria": "包含 reasoning 和 act"}'
            )
        return AIMessage(content="not json")
    if _is_reflect_call(messages):
        _replan_fallback_state["reflect_calls"] += 1
        return AIMessage(content='{"status": "replan", "reasoning": "missing act", "missing": ["act"]}')
    _replan_fallback_state["act_calls"] += 1
    if _replan_fallback_state["act_calls"] == 1:
        return AIMessage(content="这是一种推理方法。")
    return AIMessage(content="ReAct 把 reasoning 与 act 交替。")


def test_replan_parse_failure_falls_back_to_plain_react(eval_runtime_factory):
    _replan_fallback_state.update({"plan_calls": 0, "reflect_calls": 0, "act_calls": 0})
    case = EvalCase.from_dict(
        {
            "id": "e2e_par_replan_fallback",
            "scene": "long_dialog_research",
            "input": {"user_message": "请先解释 ReAct 然后说明它的两个关键要素"},
            "expected": {
                "answer_contains_any": ["reasoning", "act"],
            },
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
    )
    runtime = eval_runtime_factory(script=_replan_parse_fail_falls_back_script)
    result = run_case(case, runtime=runtime)
    assert result.passed, [v.reasoning for v in result.verdicts]
    assert _replan_fallback_state == {"plan_calls": 2, "reflect_calls": 1, "act_calls": 2}
    assert result.metrics["llm_calls"] == 5


def _plan_disabled_script(messages, allow_tools):  # noqa: ARG001
    # Should never be called with a planner system prompt if flag is off.
    assert not _is_planner_call(messages), "planner invoked despite flag off"
    assert not _is_reflect_call(messages), "reflect invoked despite flag off"
    return AIMessage(content="ReAct 把 reasoning 与 act 交替。")


def test_flag_off_disables_plan_and_reflect(eval_runtime_factory):
    settings = Settings()
    settings.plan_act_reflect_enabled = False
    case = EvalCase.from_dict(
        {
            "id": "e2e_par_off",
            "scene": "long_dialog_research",
            "input": {"user_message": "用一句话解释 ReAct"},
            "expected": {"answer_contains_any": ["reasoning", "act"]},
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
    )
    runtime = eval_runtime_factory(script=_plan_disabled_script, settings=settings)
    result = run_case(case, runtime=runtime)
    assert result.passed, [v.reasoning for v in result.verdicts]
    assert result.metrics["llm_calls"] == 1
