from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import Settings
from ..harness.tools import tools_schema_fingerprint
from ..model_registry import create_chat_model


class GraphModelFactory:
    def __init__(
        self, *, settings: Settings, chat_model_factory: Callable[..., Any] = create_chat_model
    ) -> None:
        self._settings = settings
        self._chat_model_factory = chat_model_factory
        self._base_model_cache: dict[str, Any] = {}
        self._model_cache: dict[str, Any] = {}
        self._model_with_tools_cache: dict[str, Any] = {}

    def base_model_for(self, model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = self._base_model_cache.get(cache_key)
        if cached is not None:
            return cached
        model = self._chat_model_factory(
            model_id,
            temperature=self._settings.temperature,
            thinking_mode=thinking_mode or None,
            settings=self._settings,
        )
        self._base_model_cache[cache_key] = model
        return model

    def model_for(self, model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = self._model_cache.get(cache_key)
        if cached is not None:
            return cached
        model = self.base_model_for(model_id, thinking_mode).with_config(
            {"run_name": "focus_agent_model"}
        )
        self._model_cache[cache_key] = model
        return model

    def model_with_tools_for(
        self,
        model_id: str,
        thinking_mode: str,
        *,
        default_tools: list[Any],
        available_tools: list[Any] | None = None,
    ):
        selected_tools = list(default_tools if available_tools is None else available_tools)
        tool_key = tools_schema_fingerprint(selected_tools)
        cache_key = f"{model_id}|{thinking_mode or ''}|{tool_key}"
        cached = self._model_with_tools_cache.get(cache_key)
        if cached is not None:
            return cached
        bound = (
            self.base_model_for(model_id, thinking_mode)
            .bind_tools(selected_tools)
            .with_config({"run_name": "focus_agent_model"})
        )
        self._model_with_tools_cache[cache_key] = bound
        return bound
