from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from focus_agent.config import ConfiguredModel, ModelCatalogConfig, ProviderConfig, Settings
from focus_agent.core.token_usage import accumulate_token_usage, message_token_usage
from focus_agent.engine.graph.agent_loop_helpers import _message_content_text
from focus_agent.engine.graph.tool_history_repair import _messages_for_model
from focus_agent.model_registry import create_chat_model
from focus_agent.observability.trajectory import _build_metrics


def _anthropic_settings() -> Settings:
    return Settings(
        model="claude_gateway:claude-test",
        model_catalog=ModelCatalogConfig(
            providers=(
                ProviderConfig(
                    id="claude_gateway",
                    backend_provider="anthropic",
                    base_url_env="TEST_CLAUDE_BASE_URL",
                    api_key_env="TEST_CLAUDE_API_KEY",
                ),
            ),
            models=(
                ConfiguredModel(
                    id="claude_gateway:claude-test",
                    supports_thinking=True,
                    request_kwargs={"default_headers": {"x-catalog-header": "present"}},
                ),
            ),
        ),
    )


def _cache_marker_count(value: Any) -> int:
    if isinstance(value, dict):
        return int("cache_control" in value) + sum(
            _cache_marker_count(item) for item in value.values()
        )
    if isinstance(value, list):
        return sum(_cache_marker_count(item) for item in value)
    return 0


def test_create_chat_model_configures_native_anthropic_and_thinking(monkeypatch) -> None:
    pytest.importorskip("langchain_anthropic")
    from langchain_anthropic import ChatAnthropic

    monkeypatch.setenv("TEST_CLAUDE_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("TEST_CLAUDE_API_KEY", "test-key")

    model = create_chat_model(
        "claude_gateway:claude-test",
        temperature=0.2,
        thinking_mode="enabled",
        settings=_anthropic_settings(),
        timeout_seconds=19.5,
        max_retries=4,
    )

    assert isinstance(model, ChatAnthropic)
    assert model.anthropic_api_url == "https://gateway.example.test"
    assert model.anthropic_api_key.get_secret_value() == "test-key"
    assert model.default_headers == {"x-catalog-header": "present"}
    assert model.default_request_timeout == 19.5
    assert model.max_retries == 4
    assert model.max_tokens == 16_384
    assert model.thinking == {"type": "enabled", "budget_tokens": 4096}
    assert model.temperature is None


def test_anthropic_payload_marks_tools_system_and_moving_history() -> None:
    pytest.importorskip("langchain_anthropic")
    from focus_agent.providers.anthropic_channel import create_anthropic_chat_model

    model = create_anthropic_chat_model(model="claude-test", api_key="test-key")
    tools = [
        {
            "name": "lookup",
            "description": "Look up a value",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "finish",
            "description": "Finish the task",
            "input_schema": {"type": "object", "properties": {}},
        },
    ]
    messages = [
        SystemMessage(content=[{"type": "text", "text": "Stable instructions"}]),
        HumanMessage("Find the value"),
        AIMessage(
            content=[
                {"type": "thinking", "thinking": "Use lookup", "signature": "signature"},
                {"type": "tool_use", "id": "call-1", "name": "lookup", "input": {}},
            ],
            tool_calls=[{"id": "call-1", "name": "lookup", "args": {}}],
        ),
        ToolMessage("42", tool_call_id="call-1"),
    ]
    original_messages = deepcopy(messages)
    original_tools = deepcopy(tools)
    history = _messages_for_model({"recent_messages": [], "messages": messages[1:]})
    bound = model.bind_tools(tools)

    payload = model._get_request_payload([messages[0], *history], **bound.kwargs)

    history_assistant = next(message for message in history if isinstance(message, AIMessage))
    assert history_assistant.content == messages[2].content
    assert "cache_control" not in payload["tools"][0]
    assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert payload["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert payload["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert _cache_marker_count(payload) == 3
    assert _cache_marker_count(payload) <= 4
    assert messages == original_messages
    assert tools == original_tools
    assistant = next(message for message in payload["messages"] if message["role"] == "assistant")
    assert assistant["content"][0] == {
        "type": "thinking",
        "thinking": "Use lookup",
        "signature": "signature",
    }


def test_anthropic_cache_respects_existing_breakpoint_budget() -> None:
    pytest.importorskip("langchain_anthropic")
    from focus_agent.providers.anthropic_channel import apply_anthropic_prompt_cache

    marker = {"type": "ephemeral"}
    payload = {
        "tools": [{"name": "first", "cache_control": marker}, {"name": "last"}],
        "system": [
            {"type": "text", "text": "cached", "cache_control": marker},
            {"type": "text", "text": "tail"},
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": [{"type": "text", "text": "cached", "cache_control": marker}],
                    }
                ],
            }
        ],
    }
    original = deepcopy(payload)

    cached = apply_anthropic_prompt_cache(payload)

    assert _cache_marker_count(cached) == 4
    assert cached["tools"][-1]["cache_control"] == marker
    assert "cache_control" not in cached["system"][-1]
    assert "cache_control" not in cached["messages"][-1]["content"][-1]
    assert payload == original


def test_openai_compatible_payload_has_no_anthropic_cache_markers(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    model = create_chat_model("openai:gpt-4.1-mini", temperature=0.0)

    payload = model._get_request_payload(
        [SystemMessage("Stable instructions"), HumanMessage("Find the value")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look up a value",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert _cache_marker_count(payload) == 0


def test_message_content_text_extracts_visible_anthropic_text() -> None:
    message = AIMessage(
        content=[
            {"type": "thinking", "thinking": "Hidden reasoning", "signature": "signature"},
            {"type": "text", "text": "Visible answer."},
            {"type": "text", "text": "More detail."},
        ]
    )

    assert _message_content_text(message) == "Visible answer.\nMore detail."


def test_cache_usage_is_normalized_accumulated_and_recorded() -> None:
    message = AIMessage(
        content="Done",
        usage_metadata={
            "input_tokens": 1100,
            "output_tokens": 25,
            "total_tokens": 1125,
            "input_token_details": {"cache_read": 800, "cache_creation": 200},
        },
    )

    usage = message_token_usage(message)
    assert usage == {
        "input_tokens": 1100,
        "output_tokens": 25,
        "total_tokens": 1125,
        "cache_read_input_tokens": 800,
        "cache_creation_input_tokens": 200,
    }
    accumulated = accumulate_token_usage(usage, usage)
    assert accumulated["cache_read_input_tokens"] == 1600
    assert accumulated["cache_creation_input_tokens"] == 400

    metrics = _build_metrics(messages=[message], trajectory=[], latency_ms=1.0, llm_calls=1)
    assert metrics["cache_read_input_tokens"] == 800
    assert metrics["cache_creation_input_tokens"] == 200
