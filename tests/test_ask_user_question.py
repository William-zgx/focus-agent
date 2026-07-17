from __future__ import annotations

import json

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.capabilities.ask_user_question import (
    ASK_USER_QUESTION_KIND,
    ASK_USER_QUESTION_TOOL_NAME,
    ask_user_question_response_error,
    build_ask_user_question_interrupt_payload,
    format_ask_user_question_tool_result,
    normalize_ask_user_questions,
    parse_ask_user_question_answers,
)
from focus_agent.capabilities.default_tool_modules.conversation import (
    build_conversation_tools,
)
from focus_agent.capabilities.tool_registry import ToolRuntimeMeta
from focus_agent.capabilities.tool_runtime import ToolResultCacheStore
from focus_agent.config import Settings, ToolCatalogConfig
from focus_agent.core.types import ContextBudget
from focus_agent.engine.graph.tool_execution import make_tool_executor_node


def _sample_questions() -> list[dict]:
    return [
        {
            "question": "Which auth mode should we use?",
            "header": "Auth",
            "multi_select": False,
            "options": [
                {"label": "OAuth", "description": "Standard browser login"},
                {"label": "API key", "description": "Service-to-service"},
            ],
        },
        {
            "question": "Which surfaces need work?",
            "header": "Scope",
            "multi_select": True,
            "options": [
                {"label": "Web", "description": "Desktop web"},
                {"label": "Mobile", "description": "Android"},
            ],
        },
    ]


def test_normalize_and_build_ask_user_question_interrupt_payload():
    payload = build_ask_user_question_interrupt_payload(
        tool_call_id="call-ask-1",
        questions=_sample_questions(),
    )
    assert payload["kind"] == ASK_USER_QUESTION_KIND
    assert payload["tool_name"] == ASK_USER_QUESTION_TOOL_NAME
    assert payload["tool_call_id"] == "call-ask-1"
    assert payload["interrupt_id"].startswith("ask-user-question:call-ask-1:")
    assert len(payload["questions"]) == 2
    assert payload["questions"][0]["id"] == "q0"
    assert payload["questions"][1]["multi_select"] is True


def test_ask_user_question_response_validation_and_parse():
    questions = normalize_ask_user_questions(_sample_questions())
    payload = build_ask_user_question_interrupt_payload(
        tool_call_id="call-ask-2",
        questions=questions,
    )
    good = {
        "kind": ASK_USER_QUESTION_KIND,
        "interrupt_id": payload["interrupt_id"],
        "tool_call_id": "call-ask-2",
        "answers": [
            {
                "question_id": "q0",
                "selected_labels": ["OAuth"],
                "other_text": None,
            },
            {
                "question_id": "q1",
                "selected_labels": ["Web", "Other"],
                "other_text": "CLI too",
            },
        ],
    }
    assert (
        ask_user_question_response_error(
            good,
            interrupt_id=payload["interrupt_id"],
            tool_call_id="call-ask-2",
            questions=questions,
        )
        is None
    )
    parsed = parse_ask_user_question_answers(good, questions=questions)
    assert parsed[0]["selected_labels"] == ["OAuth"]
    assert parsed[1]["selected_other"] is True
    assert parsed[1]["other_text"] == "CLI too"
    result = json.loads(format_ask_user_question_tool_result(questions=questions, answers=parsed))
    assert result["status"] == "answered"
    assert result["answers"][1]["other_text"] == "CLI too"

    bad = {
        **good,
        "answers": [
            {"question_id": "q0", "selected_labels": ["OAuth"]},
        ],
    }
    assert (
        ask_user_question_response_error(
            bad,
            interrupt_id=payload["interrupt_id"],
            tool_call_id="call-ask-2",
            questions=questions,
        )
        is not None
    )


def test_ask_user_question_tool_rejects_direct_invoke():
    tools, _runtime = build_conversation_tools(
        checkpointer=None,
        tool_catalog=ToolCatalogConfig(),
        emit_tool_event=lambda **_kwargs: None,
        get_current_thread_id=lambda: None,
    )
    with pytest.raises(RuntimeError, match="cannot be executed automatically"):
        tools[ASK_USER_QUESTION_TOOL_NAME].invoke({"questions": _sample_questions()})


class _Runtime:
    def __init__(self, context):
        self.context = context


def test_tool_executor_resumes_ask_user_question_with_answers(monkeypatch):
    tools, runtime_meta = build_conversation_tools(
        checkpointer=None,
        tool_catalog=ToolCatalogConfig(),
        emit_tool_event=lambda **_kwargs: None,
        get_current_thread_id=lambda: "thread-1",
    )
    tool = tools[ASK_USER_QUESTION_TOOL_NAME]
    tool.metadata = {**runtime_meta[ASK_USER_QUESTION_TOOL_NAME]}
    tools_by_name = {ASK_USER_QUESTION_TOOL_NAME: tool}
    runtime_by_name = {
        ASK_USER_QUESTION_TOOL_NAME: ToolRuntimeMeta.from_tool(tool),
    }
    node = make_tool_executor_node(
        tools_by_name=tools_by_name,
        tool_runtime_by_name=runtime_by_name,
        tool_result_cache=ToolResultCacheStore(),
    )
    state = {
        "messages": [
            HumanMessage(content="pick options"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-ask-3",
                        "name": ASK_USER_QUESTION_TOOL_NAME,
                        "args": {"questions": _sample_questions()},
                    }
                ],
            ),
        ],
        "thread_id": "thread-1",
        "context_budget": ContextBudget(),
    }
    context = type(
        "Ctx",
        (),
        {
            "root_thread_id": "thread-1",
            "branch_id": None,
        },
    )()
    captured: dict[str, object] = {}

    def _fake_interrupt(value):
        captured["payload"] = value
        return {
            "kind": ASK_USER_QUESTION_KIND,
            "interrupt_id": value["interrupt_id"],
            "tool_call_id": "call-ask-3",
            "answers": [
                {
                    "question_id": "q0",
                    "selected_labels": ["API key"],
                    "other_text": None,
                },
                {
                    "question_id": "q1",
                    "selected_labels": ["Web", "Mobile"],
                    "other_text": None,
                },
            ],
        }

    monkeypatch.setattr(
        "focus_agent.engine.graph.tool_execution.interrupt",
        _fake_interrupt,
    )
    result = node(state, _Runtime(context))
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["kind"] == ASK_USER_QUESTION_KIND
    assert payload["tool_call_id"] == "call-ask-3"
    tool_messages = [
        message
        for message in result["messages"]
        if getattr(message, "type", "") == "tool" or message.__class__.__name__ == "ToolMessage"
    ]
    assert tool_messages
    content = json.loads(str(tool_messages[-1].content))
    assert content["status"] == "answered"
    assert content["answers"][0]["selected_labels"] == ["API key"]


def test_default_tools_include_ask_user_question(tmp_path):
    from focus_agent.capabilities.default_tool_modules.factory import get_default_tools

    tools = get_default_tools(Settings(workspace_root=str(tmp_path)))
    names = {tool.name for tool in tools}
    assert ASK_USER_QUESTION_TOOL_NAME in names
