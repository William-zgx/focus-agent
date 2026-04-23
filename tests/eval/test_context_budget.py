from __future__ import annotations

import json
from typing import Any

from langchain.messages import AIMessage, ToolMessage
from langchain.tools import tool as langchain_tool

from focus_agent.core import context_policy as context_policy_module
from focus_agent.core.types import ContextBudget

from .runner import run_case
from .schema import EvalCase


def _long_history_direct_writing_script(messages: list[Any], allow_tools: bool) -> AIMessage:
    assert not allow_tools, "direct writing turn should not bind tools"
    prompt_text = "\n".join(str(getattr(message, "content", "")) for message in messages)
    assert "帮我写一段关于杨絮好处的短文" in prompt_text
    assert "Keep the current writing request authoritative." in prompt_text
    assert "OBSOLETE_HISTORY" not in prompt_text
    return AIMessage(content="杨絮随风飘散，帮助柳树传播种子，也提醒人们观察季节变化。")


def test_eval_long_history_direct_writing_stays_tool_free(eval_runtime_factory):
    user_message = "帮我写一段关于杨絮好处的短文，直接发给我。"
    case = EvalCase(
        id="budget_long_history_direct_writing_no_tools",
        tags=["smoke", "regression", "context_budget"],
        input={
            "user_message": user_message,
            "initial_state": {
                "rolling_summary": "OBSOLETE_HISTORY " * 500,
                "user_constraints": [
                    {"constraint": "Keep the current writing request authoritative."}
                ],
                "context_budget": ContextBudget(prompt_token_limit=360, chars_per_token=1),
            },
        },
        expected={
            "answer_contains_any": ["杨絮"],
            "max_tool_calls": 0,
            "must_not_call_tools": ["web_search", "web_fetch", "write_text_artifact"],
        },
        judge={"rule": True, "llm": {"enabled": False}},
    )

    result = run_case(case, runtime=eval_runtime_factory(script=_long_history_direct_writing_script))

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    assert result.metrics["tool_calls"] == 0


@langchain_tool
def search_code(query: str = "") -> str:  # type: ignore[no-untyped-def]
    """Return a deliberately oversized structured code-search observation."""
    return json.dumps(
        {
            "query": query,
            "results": [
                {
                    "path": "src/focus_agent/core/context_policy.py",
                    "line_number": 42,
                    "line": "def assemble_context(state, mode):",
                }
            ],
            "noise": "POLLUTION" * 2000,
        },
        ensure_ascii=False,
    )


def _long_tool_output_script(messages: list[Any], allow_tools: bool) -> AIMessage:
    if allow_tools and not any(isinstance(message, ToolMessage) for message in messages):
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

    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
    tool_text = "\n".join(str(message.content) for message in tool_messages)
    if "POLLUTION" in tool_text:
        return AIMessage(content="POLLUTION leaked into the answer.")
    tool_message = tool_messages[-1]
    tool_payload = json.loads(str(tool_message.content))
    artifact = getattr(tool_message, "artifact", None)
    prompt_payload = tool_payload
    if isinstance(artifact, dict) and isinstance(artifact.get("prompt_observation"), str):
        prompt_payload = json.loads(str(artifact["prompt_observation"]))
    refs = prompt_payload.get("refs") or []
    if "src/focus_agent/core/context_policy.py:42" in refs:
        return AIMessage(content=f"Relevant hit: {refs[0]}.")

    results = prompt_payload.get("results") or []
    if results and isinstance(results[0], dict):
        ref = str(results[0].get("ref") or "").strip()
        if ref:
            return AIMessage(content=f"Relevant hit: {ref}.")
        path = str(results[0].get("path") or "").strip()
        line_number = results[0].get("line_number")
        if path and line_number is not None:
            return AIMessage(content=f"Relevant hit: {path}:{line_number}.")
        if path:
            return AIMessage(content=f"Relevant hit: {path}.")

    if prompt_payload.get("artifact_ref") == "tool-observation://search_code/call-1":
        return AIMessage(content="artifact-like prompt reference retained.")
    return AIMessage(content="search result survived compaction but lost location detail.")


def test_eval_long_tool_output_does_not_pollute_final_answer(eval_runtime_factory):
    case = EvalCase(
        id="budget_long_tool_output_no_answer_pollution",
        tags=["smoke", "regression", "context_budget", "tools"],
        input={
            "user_message": "找到仓库里 assemble_context 的定义位置。",
            "initial_state": {
                "context_budget": ContextBudget(
                    prompt_token_limit=500,
                    chars_per_token=1,
                    tool_observation_token_limit=260,
                )
            },
        },
        expected={
            "must_call_tools_any_order": ["search_code"],
            "answer_contains_all": ["context_policy.py"],
            "answer_must_not_contain": ["POLLUTION"],
            "max_tool_calls": 1,
        },
        judge={"rule": True, "llm": {"enabled": False}},
    )

    result = run_case(
        case,
        runtime=eval_runtime_factory(script=_long_tool_output_script, tools=[search_code]),
    )

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    assert result.metrics["tool_calls"] == 1
    assert "POLLUTION" not in result.answer
    assert "artifact-like prompt reference missing" not in result.answer
    assert "artifact-like refs missing" not in result.answer
    assert "POLLUTION" not in result.trajectory[0].observation


def test_eval_long_tool_output_marks_prompt_compaction_runtime(eval_runtime_factory):
    case = EvalCase(
        id="budget_long_tool_output_marks_prompt_compaction",
        tags=["smoke", "regression", "context_budget", "tools"],
        input={
            "user_message": "找到仓库里 assemble_context 的定义位置。",
            "initial_state": {
                "context_budget": ContextBudget(
                    prompt_token_limit=500,
                    chars_per_token=1,
                    tool_observation_token_limit=180,
                    tool_reference_token_limit=80,
                )
            },
        },
        expected={
            "must_call_tools_any_order": ["search_code"],
            "answer_contains_all": ["context_policy.py"],
            "max_tool_calls": 1,
        },
        judge={"rule": True, "llm": {"enabled": False}},
    )

    result = run_case(
        case,
        runtime=eval_runtime_factory(script=_long_tool_output_script, tools=[search_code]),
    )

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    runtime = result.trajectory[0].runtime
    assert runtime["observation_prompt_compacted"] is True
    assert runtime["observation_original_chars"] > runtime["observation_trimmed_chars"]


def _tokenizer_first_budget_script(messages: list[Any], allow_tools: bool) -> AIMessage:
    assert not allow_tools, "tokenizer-first budget case should stay tool free"
    prompt_text = "\n".join(str(getattr(message, "content", "")) for message in messages)
    assert "Current user turn must stay exact." in prompt_text
    assert "Preserve this exact constraint." in prompt_text
    assert "OBSOLETE_HISTORY" not in prompt_text
    return AIMessage(content="constraint survived tokenizer-first trimming")


def test_eval_tokenizer_first_budget_prioritizes_constraints(eval_runtime_factory, monkeypatch):
    def fake_estimate(message, *, budget):  # noqa: ARG001
        text = str(getattr(message, "content", ""))
        if "Current user turn must stay exact." in text:
            return 20
        if "Preserve this exact constraint." in text:
            return 18
        if "OBSOLETE_HISTORY" in text:
            return 40
        return max(1, len(text) // 10)

    monkeypatch.setattr(context_policy_module, "_message_budget_units", fake_estimate)

    case = EvalCase(
        id="budget_tokenizer_first_constraints_survive",
        tags=["smoke", "regression", "context_budget", "tokenizer"],
        input={
            "user_message": "Current user turn must stay exact.",
            "initial_state": {
                "rolling_summary": "OBSOLETE_HISTORY " * 120,
                "user_constraints": [{"constraint": "Preserve this exact constraint."}],
                "context_budget": ContextBudget(
                    prompt_token_limit=45,
                    chars_per_token=4,
                    token_budget_mode="tokenizer_first",
                    tokenizer_id="fake-model",
                ),
            },
        },
        expected={
            "answer_contains_all": ["constraint survived tokenizer-first trimming"],
            "max_tool_calls": 0,
        },
        judge={"rule": True, "llm": {"enabled": False}},
    )

    result = run_case(case, runtime=eval_runtime_factory(script=_tokenizer_first_budget_script))

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    assert result.metrics["tool_calls"] == 0


def _branch_review_packing_script(messages: list[Any], allow_tools: bool) -> AIMessage:
    assert not allow_tools, "branch-review packing case should stay tool free"
    prompt_text = "\n".join(str(getattr(message, "content", "")) for message in messages)
    assert "## Findings" in prompt_text
    assert "## Constraints and goals" in prompt_text
    assert "## Artifacts in scope" in prompt_text
    assert prompt_text.index("## Findings") < prompt_text.index("## Constraints and goals")
    return AIMessage(content="branch review packing preserved import-worthy blocks")


def test_eval_branch_review_packing_prioritizes_findings_and_artifacts(eval_runtime_factory):
    case = EvalCase(
        id="budget_branch_review_block_packing",
        tags=["smoke", "regression", "context_budget", "branch_review"],
        input={
            "user_message": "请准备 merge review 摘要。",
            "initial_state": {
                "prompt_mode": "branch_review",
                "rolling_summary": "OLD_SUMMARY " * 120,
                "user_constraints": [{"constraint": "Keep the review concise."}],
                "branch_meta": {
                    "branch_id": "branch-pack",
                    "branch_name": "review-pack",
                    "branch_role": "verify",
                },
                "branch_local_findings": [{"finding": "Branch finding worth importing"}],
                "artifacts": [{"title": "Review notes", "kind": "note"}],
                "context_budget": ContextBudget(prompt_token_limit=360, chars_per_token=1),
            },
        },
        expected={
            "answer_contains_all": ["branch review packing preserved import-worthy blocks"],
            "max_tool_calls": 0,
        },
        judge={"rule": True, "llm": {"enabled": False}},
    )

    result = run_case(case, runtime=eval_runtime_factory(script=_branch_review_packing_script))

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    assert result.metrics["tool_calls"] == 0
