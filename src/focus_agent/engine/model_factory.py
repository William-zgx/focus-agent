from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from ..config import Settings
from ..harness.tools import tools_schema_fingerprint
from ..model_registry import create_chat_model


class ModelInvocationTimeoutError(TimeoutError):
    """Raised when a synchronous graph model call exceeds its runtime deadline."""


class _TimeoutBoundModel:
    def __init__(self, model: Any, *, timeout_seconds: float) -> None:
        self._model = model
        self._timeout_seconds = max(float(timeout_seconds), 0.001)

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        completed = threading.Event()
        result: dict[str, Any] = {}

        def invoke_model() -> None:
            try:
                if config is None:
                    result["value"] = self._model.invoke(input, **kwargs)
                else:
                    result["value"] = self._model.invoke(input, config=config, **kwargs)
            except BaseException as exc:  # noqa: BLE001
                result["error"] = exc
            finally:
                completed.set()

        threading.Thread(
            target=invoke_model,
            name="focus-agent-model-invoke",
            daemon=True,
        ).start()
        if not completed.wait(self._timeout_seconds):
            raise ModelInvocationTimeoutError(
                f"Model invocation exceeded {self._timeout_seconds:g} seconds."
            )
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def with_config(self, config: Any) -> _TimeoutBoundModel:
        return _TimeoutBoundModel(
            self._model.with_config(config),
            timeout_seconds=self._timeout_seconds,
        )

    def bind_tools(self, tools: Any, **kwargs: Any) -> _TimeoutBoundModel:
        return _TimeoutBoundModel(
            self._model.bind_tools(tools, **kwargs),
            timeout_seconds=self._timeout_seconds,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


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

    def _timeout_bound(self, model: Any) -> _TimeoutBoundModel:
        return _TimeoutBoundModel(
            model,
            timeout_seconds=self._settings.model_request_timeout_seconds,
        )

    def model_for(self, model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = self._model_cache.get(cache_key)
        if cached is not None:
            return cached
        model = self._timeout_bound(self.base_model_for(model_id, thinking_mode)).with_config(
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
            self._timeout_bound(self.base_model_for(model_id, thinking_mode))
            .bind_tools(selected_tools)
            .with_config({"run_name": "focus_agent_model"})
        )
        self._model_with_tools_cache[cache_key] = bound
        return bound
