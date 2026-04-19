"""Pytest fixtures for the agent eval framework.

Provides deterministic fakes so the framework itself can be tested
without external LLM providers or network access.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from langchain.messages import AIMessage

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from langchain.tools import tool as langchain_tool

from .runner.harness import EvalRuntime


def _make_scripted_model(script: Callable[[list[Any], bool], AIMessage]) -> Callable[..., Any]:
    """Return a create_chat_model replacement that yields a scripted fake."""

    class ScriptedRunnable:
        def __init__(self, allow_tools: bool):
            self.allow_tools = allow_tools

        def with_config(self, _config):
            return self

        def invoke(self, messages):
            return script(list(messages), self.allow_tools)

    class ScriptedModel:
        def bind_tools(self, _tools):
            return ScriptedRunnable(allow_tools=True)

        def with_config(self, _config):
            return ScriptedRunnable(allow_tools=False)

    def _factory(*_args, **_kwargs):
        return ScriptedModel()

    return _factory


@pytest.fixture
def scripted_model_factory():
    """Provide a helper for tests to build a scripted model factory."""
    return _make_scripted_model


@pytest.fixture
def eval_runtime_factory(scripted_model_factory):
    """Build an EvalRuntime with injected fake tools and a scripted model.

    Usage:
        runtime = eval_runtime_factory(script=my_script, tools=[my_tool])
    """

    def _build(
        *,
        script: Callable[[list[Any], bool], AIMessage],
        tools: list[Any] | None = None,
        settings: Settings | None = None,
    ) -> EvalRuntime:
        tools = tools or [_noop_tool()]
        return EvalRuntime(
            settings=settings or Settings(),
            tool_registry=ToolRegistry(tools=tuple(tools)),
            model_factory=scripted_model_factory(script),
        )

    return _build


def _noop_tool():
    @langchain_tool
    def noop(query: str = "") -> str:
        """No-op placeholder tool used by eval self-tests."""
        return f"noop:{query}"

    return noop
