from __future__ import annotations

from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.context_compaction import (
    HISTORY_SUMMARY_MAX_CHARS,
    build_incremental_compaction_update,
)
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import build_graph
from focus_agent.engine.local_persistence import PersistentInMemorySaver
from focus_agent.engine.loop.compaction import make_model_compaction_summarizer
from focus_agent.engine.model_factory import ModelInvocationTimeoutError
from focus_agent.memory import MemoryExtractor, MemoryRetriever


class _FakeModel:
    def __init__(self, response: Any):
        self.response = response
        self.configs: list[dict] = []
        self.prompts: list[list] = []

    def with_config(self, config):
        self.configs.append(dict(config))
        return self

    def bind_tools(self, _tools, **_kwargs):
        return self

    def invoke(self, prompt_messages):
        self.prompts.append(list(prompt_messages))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _pair(index: int) -> list[object]:
    return [
        HumanMessage(content=f"human-{index}", id=f"human-{index}"),
        AIMessage(content=f"assistant-{index}", id=f"assistant-{index}"),
    ]


def _state_with_pending_compaction(*, due: bool = True) -> tuple[dict, str]:
    budget = {
        "recent_message_limit": 2,
        "recent_message_token_limit": 1000,
        "prompt_token_limit": 1 if due else 100_000,
        "output_token_reserve": 0,
        "chars_per_token": 1,
        "token_budget_mode": "chars_fallback",
    }
    first_state = {
        "messages": [*_pair(0), *_pair(1)],
        "context_budget": budget,
    }
    first = build_incremental_compaction_update(
        first_state,
        now="2026-11-07T00:00:00+00:00",
    )
    state = {
        **first_state,
        **first,
        "messages": [*first_state["messages"], *_pair(2)],
        "selected_model": "selected:test",
    }
    return state, str(first["context_compaction"]["history_summary"])


def _summarizer(
    model: _FakeModel,
    **settings_overrides: Any,
) -> tuple[Any, list[tuple[str, str]]]:
    calls: list[tuple[str, str]] = []

    def model_for(model_id: str, thinking_mode: str):
        calls.append((model_id, thinking_mode))
        return model

    settings = Settings(
        helper_model="helper:test",
        context_auto_compaction_post_turn_ratio=0.85,
        **settings_overrides,
    )
    summarize = make_model_compaction_summarizer(
        settings=settings,
        model_for=model_for,
        known_tool_names=("lookup",),
    )
    return summarize, calls


def test_v2_model_compaction_merges_pending_messages_and_previous_summary():
    state, previous_summary = _state_with_pending_compaction()
    state["llm_calls"] = 4
    helper = _FakeModel(AIMessage(content="模型撰写的滚动摘要"))
    summarize, calls = _summarizer(helper)

    result = summarize(state)

    assert calls == [("helper:test", "")]
    assert result["rolling_summary"] == "模型撰写的滚动摘要"
    assert result["llm_calls"] == 5
    metadata = result["context_compaction"]
    assert metadata["history_summary"] == "模型撰写的滚动摘要"
    assert metadata["summary_method"] == "model"
    assert "summary_fallback_reason" not in metadata

    prompt = helper.prompts[0]
    system_text, request_text = (message.content for message in prompt)
    assert "goals and constraints" in system_text
    assert "decisions made and conclusions reached" in system_text
    assert "open questions" in system_text
    assert "source URL" in system_text
    assert "files, paths" in system_text
    assert previous_summary in request_text
    assert "human-1" in request_text
    assert "assistant-1" in request_text
    assert "human-2" not in request_text
    assert helper.configs == [
        {
            "metadata": {"stream_phase": "quarantine"},
            "tags": ["stream_phase:quarantine"],
        }
    ]


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (RuntimeError("helper failed"), "model_error"),
        (ModelInvocationTimeoutError("helper timed out"), "timeout"),
        (AIMessage(content="   "), "empty_response"),
        (
            AIMessage(content=('<tool_call>{"name":"lookup","args":{"name":"focus"}}</tool_call>')),
            "tool_call_markup",
        ),
    ],
    ids=["error", "timeout", "empty", "tool-call-markup"],
)
def test_v2_model_compaction_falls_back_without_failing_the_turn(response, reason):
    state, _previous_summary = _state_with_pending_compaction()
    helper = _FakeModel(response)
    summarize, _calls = _summarizer(helper)
    expected = build_incremental_compaction_update(
        state,
        state["context_compaction"],
        trigger="turn_summary",
        force=False,
    )

    result = summarize(state)

    assert result["rolling_summary"] == expected["rolling_summary"]
    assert result["llm_calls"] == 1
    metadata = result["context_compaction"]
    assert metadata["summary_method"] == "heuristic"
    assert metadata["summary_fallback_reason"] == reason
    assert (
        metadata["source_message_cursor"] == expected["context_compaction"]["source_message_cursor"]
    )


def test_v2_model_compaction_does_not_call_helper_below_threshold():
    state, _previous_summary = _state_with_pending_compaction(due=False)
    helper = _FakeModel(AIMessage(content="must not be used"))
    summarize, calls = _summarizer(helper)
    expected = build_incremental_compaction_update(
        state,
        state["context_compaction"],
        trigger="turn_summary",
        force=False,
    )

    result = summarize(state)

    assert calls == []
    assert helper.prompts == []
    assert result["rolling_summary"] == expected["rolling_summary"]
    assert result.get("llm_calls", 0) == 0
    assert result["context_compaction"]["summary_method"] == "heuristic"
    assert "summary_fallback_reason" not in result["context_compaction"]


def test_v2_model_compaction_respects_auto_compaction_disabled():
    state, _previous_summary = _state_with_pending_compaction()
    helper = _FakeModel(AIMessage(content="must not be used"))
    summarize, calls = _summarizer(helper, context_auto_compaction_enabled=False)

    result = summarize(state)

    assert calls == []
    assert helper.prompts == []
    assert result.get("llm_calls", 0) == 0
    assert result["context_compaction"]["summary_method"] == "heuristic"


def test_v2_model_compaction_bounds_model_output_to_summary_budget():
    state, _previous_summary = _state_with_pending_compaction()
    helper = _FakeModel(AIMessage(content="summary line\n" * 1000))
    summarize, _calls = _summarizer(helper)

    result = summarize(state)

    assert len(result["rolling_summary"]) <= HISTORY_SUMMARY_MAX_CHARS
    assert result["context_compaction"]["summary_method"] == "model"


def test_v2_model_compaction_retry_merges_into_last_accepted_model_summary():
    state, _previous_summary = _state_with_pending_compaction()
    first_helper = _FakeModel(AIMessage(content="model summary v1"))
    first_summarize, _calls = _summarizer(first_helper)
    first = first_summarize(state)
    extended = {
        **state,
        **first,
        "messages": [*state["messages"], *_pair(3)],
    }
    failing_helper = _FakeModel(RuntimeError("temporary failure"))
    failing_summarize, _calls = _summarizer(failing_helper)
    fallback = failing_summarize(extended)

    retry_helper = _FakeModel(AIMessage(content="model summary v2"))
    retry_summarize, _calls = _summarizer(retry_helper)
    retried = retry_summarize({**extended, **fallback})

    assert fallback["context_compaction"]["summary_method"] == "heuristic"
    request_text = retry_helper.prompts[0][1].content
    assert "Previous summary:\nmodel summary v1" in request_text
    assert "human-2" in request_text
    assert "human-3" not in request_text
    assert retried["rolling_summary"] == "model summary v2"
    assert retried["llm_calls"] == 3
    assert retried["context_compaction"]["summary_method"] == "model"
    assert "summary_fallback_reason" not in retried["context_compaction"]
    assert retried["context_compaction"]["status"] == "updated"
    assert retried["context_compaction"]["no_gain"] is False


def test_v2_graph_compaction_helper_is_quarantined_and_counted(monkeypatch, tmp_path):
    main = _FakeModel(AIMessage(content="visible answer"))
    helper = _FakeModel(AIMessage(content="internal rolling summary"))

    def create_model(model_id, *_args, **_kwargs):
        return helper if model_id == "helper:test" else main

    monkeypatch.setattr("focus_agent.engine.graph_builder.create_chat_model", create_model)
    graph = build_graph(
        settings=Settings(
            helper_model="helper:test",
            context_auto_compaction_post_turn_ratio=0.85,
        ),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        memory_retriever=MemoryRetriever(store=None),
        memory_extractor=MemoryExtractor(mode="off"),
        tool_registry=ToolRegistry(tools=()),
    )
    thread_id = "thread-v2-model-compaction"
    result = graph.invoke(
        {
            "messages": [*_pair(0), *_pair(1), HumanMessage(content="latest question")],
            "selected_model": "selected:test",
            "context_budget": {
                "recent_message_limit": 2,
                "recent_message_token_limit": 1000,
                "prompt_token_limit": 1000,
                "output_token_reserve": 0,
                "chars_per_token": 1,
                "token_budget_mode": "chars_fallback",
            },
        },
        config={"configurable": {"thread_id": thread_id}},
        context=RequestContext(user_id="user-1", root_thread_id=thread_id),
        version="v2",
    )

    values = result.value
    assert values["messages"][-1].content == "visible answer"
    assert "internal rolling summary" not in [message.content for message in values["messages"]]
    assert values["rolling_summary"] == "internal rolling summary"
    assert values["context_compaction"]["summary_method"] == "model"
    assert values["llm_calls"] == 2
    assert len(helper.prompts) == 1
    assert {
        "metadata": {"stream_phase": "quarantine"},
        "tags": ["stream_phase:quarantine"],
    } in helper.configs
