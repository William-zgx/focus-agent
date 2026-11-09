from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from langchain.messages import AIMessage

from ...core.repo_call import has_repo_method
from ...core.state import AgentState

_logger = logging.getLogger(__name__)


def _with_stream_phase(
    model: Any,
    phase: str,
    *,
    has_method: Callable[[Any, str], bool] = has_repo_method,
) -> Any:
    if not has_method(model, "with_config"):
        return model
    return model.with_config(
        {
            "metadata": {"stream_phase": phase},
            "tags": [f"stream_phase:{phase}"],
        }
    )


def _model_for_stream_phase(
    model_for: Callable[[str, str], Any],
    phase: str,
) -> Callable[[str, str], Any]:
    def wrapped(model_id: str, thinking_mode: str) -> Any:
        return _with_stream_phase(model_for(model_id, thinking_mode), phase)

    return wrapped


def _model_with_tools_for_stream_phase(
    model_with_tools_for: Callable[[str, str, list[Any] | None], Any],
    phase: str,
) -> Callable[[str, str, list[Any] | None], Any]:
    def wrapped(model_id: str, thinking_mode: str, available_tools: list[Any] | None) -> Any:
        return _with_stream_phase(
            model_with_tools_for(model_id, thinking_mode, available_tools),
            phase,
        )

    return wrapped


def _with_focus_agent_turn_metadata(
    response: AIMessage,
    metadata: Mapping[str, Any],
) -> AIMessage:
    if not metadata:
        return response
    response_metadata = getattr(response, "response_metadata", None)
    if not isinstance(response_metadata, Mapping):
        response_metadata = {}
    focus_agent = response_metadata.get("focus_agent")
    focus_agent_metadata = dict(focus_agent) if isinstance(focus_agent, Mapping) else {}
    focus_agent_metadata.update(dict(metadata))
    return response.model_copy(
        update={
            "response_metadata": {
                **dict(response_metadata),
                "focus_agent": focus_agent_metadata,
            }
        }
    )


def _drain_steer_messages(run_manager: Any | None, thread_id: str | None) -> list[str]:
    """Drain any steering messages queued for ``thread_id``; safe if None."""

    if run_manager is None or not thread_id:
        return []
    try:
        drainer = getattr(run_manager, "drain_steer_queue_nowait", None)
        if drainer is None:
            return []
        return list(drainer(thread_id) or [])
    except Exception:  # noqa: BLE001
        _logger.debug("Failed to drain steer queue", exc_info=True)
        return []


def _resolve_agent_definition(
    registry: Any | None,
    state: AgentState,
) -> tuple[Any | None, str | None]:
    """Look up the requested AgentDefinition from state, if any."""

    if registry is None:
        return None, None
    agent_name = (
        state.get("agent_name")
        or state.get("selected_agent")
        or (state.get("metadata") or {}).get("agent_name")
        or (state.get("metadata") or {}).get("target_agent")
        or ""
    )
    agent_name = str(agent_name or "").strip()
    if not agent_name:
        return None, None
    try:
        definition = registry.get(agent_name)
    except Exception:  # noqa: BLE001
        _logger.debug("AgentDefinition lookup failed for '%s'", agent_name, exc_info=True)
        return None, agent_name
    return definition, agent_name


def _filter_tools_by_agent_def(
    available_tools: list[Any],
    agent_def: Any,
) -> list[Any]:
    """Apply an AgentDefinition's tool_policy, if present."""

    if agent_def is None:
        return available_tools
    policy = getattr(agent_def, "tool_policy", None)
    if policy is None:
        return available_tools
    filter_fn = getattr(policy, "filter", None)
    if filter_fn is None:
        return available_tools
    try:
        names = [str(getattr(tool, "name", "") or "") for tool in available_tools]
        allowed = set(filter_fn(names))
        return [tool for tool in available_tools if str(getattr(tool, "name", "") or "") in allowed]
    except Exception:  # noqa: BLE001
        _logger.debug("AgentDefinition tool_policy filter failed", exc_info=True)
        return available_tools


__all__ = [
    "_drain_steer_messages",
    "_filter_tools_by_agent_def",
    "_model_for_stream_phase",
    "_model_with_tools_for_stream_phase",
    "_resolve_agent_definition",
    "_with_focus_agent_turn_metadata",
    "_with_stream_phase",
]
