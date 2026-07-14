import time

import pytest
from langchain.messages import AIMessage

from focus_agent.config import Settings
from focus_agent.engine.model_factory import (
    GraphModelFactory,
    ModelInvocationTimeoutError,
)


class _FakeModel:
    def __init__(self, *, sleep_seconds: float = 0.0):
        self.sleep_seconds = sleep_seconds
        self.bound_tools = None
        self.config = None

    def bind_tools(self, tools, **_kwargs):
        self.bound_tools = list(tools)
        return self

    def with_config(self, config):
        self.config = config
        return self

    def invoke(self, _input, config=None, **_kwargs):
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return AIMessage(content="completed", response_metadata={"config": config})


def test_graph_model_factory_enforces_hard_invoke_timeout():
    model = _FakeModel(sleep_seconds=0.2)
    factory = GraphModelFactory(
        settings=Settings(model_request_timeout_seconds=0.02),
        chat_model_factory=lambda *_args, **_kwargs: model,
    )

    started_at = time.monotonic()
    with pytest.raises(ModelInvocationTimeoutError, match="exceeded 0.02 seconds"):
        factory.model_for("openai:fake", "").invoke("blocked")

    assert time.monotonic() - started_at < 0.15


def test_graph_model_factory_preserves_tool_binding_and_invoke_result():
    model = _FakeModel()
    factory = GraphModelFactory(
        settings=Settings(model_request_timeout_seconds=5),
        chat_model_factory=lambda *_args, **_kwargs: model,
    )

    result = factory.model_with_tools_for(
        "openai:fake",
        "",
        default_tools=["default"],
        available_tools=["web_search"],
    ).invoke("prompt", config={"trace": "test"})

    assert model.bound_tools == ["web_search"]
    assert model.config == {"run_name": "focus_agent_model"}
    assert result.content == "completed"
    assert result.response_metadata["config"] == {"trace": "test"}
