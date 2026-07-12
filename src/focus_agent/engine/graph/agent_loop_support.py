from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain.messages import AIMessage

from ...core.repo_call import has_repo_method
from ...core.state import AgentState

_logger = logging.getLogger(__name__)

_HTTP_URL_RE = re.compile(r"https?://[^\s<>()\"'，。！？、]+", re.IGNORECASE)
_PRIMARY_OUTCOME_ROLES = frozenset({"primary"})
_ALTERNATIVE_OUTCOME_ROLES = frozenset({"alternative"})
_FAILED_OUTCOME_STATUSES = frozenset({"failed", "blocked"})
_SUCCESS_OUTCOME_STATUSES = frozenset({"succeeded", "recovered"})


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


def _web_fetch_args(preferred_args: dict[str, Any] | None, fallback_text: str) -> dict[str, Any]:
    args = dict(preferred_args or {})
    if str(args.get("url") or "").strip():
        return args
    match = _HTTP_URL_RE.search(str(fallback_text or ""))
    if not match:
        return args
    return {"url": match.group(0).rstrip(".,!?;:，。！？；：")}


def _should_force_degraded_skill_recovery_answer(
    state: AgentState,
    *,
    primary_tool_names: Sequence[str] = (),
) -> bool:
    """Stop tool storms after a Skill primary path is exhausted and fallback evidence exists."""

    outcomes = [
        dict(item) for item in state.get("tool_outcomes") or [] if isinstance(item, Mapping)
    ]
    if not outcomes:
        return False
    primary_tools = {str(name).strip() for name in primary_tool_names if str(name).strip()}
    if not primary_tools:
        primary_tools = {"run_skill_entrypoint", "run_workspace_command"}
    blocked_recovery_boundary = any(str(item.get("status") or "") == "blocked" for item in outcomes)
    primary_exhausted = any(
        (
            str(item.get("tool_name") or "") in primary_tools
            or str(item.get("evidence_role") or "") in _PRIMARY_OUTCOME_ROLES
        )
        and str(item.get("status") or "") in _FAILED_OUTCOME_STATUSES
        and (
            _outcome_attempt_index(item) >= _outcome_max_attempts(item) or blocked_recovery_boundary
        )
        for item in outcomes
    )
    if not primary_exhausted:
        return False
    return any(
        str(item.get("evidence_role") or "") in _ALTERNATIVE_OUTCOME_ROLES
        and str(item.get("status") or "") in _SUCCESS_OUTCOME_STATUSES
        for item in outcomes
    )


def _outcome_attempt_index(outcome: Mapping[str, Any]) -> int:
    try:
        return max(1, int(outcome.get("attempt_index") or 1))
    except (TypeError, ValueError):
        return 1


def _outcome_max_attempts(outcome: Mapping[str, Any]) -> int:
    try:
        return max(1, int(outcome.get("max_attempts") or 1))
    except (TypeError, ValueError):
        return 1


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


def _fire_system_agent_trigger(runner: Any | None, trigger_name: str, ctx: dict[str, Any]) -> None:
    """Best-effort fire-and-forget trigger for system agents from a sync node."""

    if runner is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        loop.create_task(runner.trigger(trigger_name, ctx))
    except Exception:  # noqa: BLE001
        _logger.debug(
            "Failed to fire system agent trigger '%s'",
            trigger_name,
            exc_info=True,
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


def _estimate_context_fullness(prompt_messages: list[Any]) -> float:
    """Roughly estimate how full the prompt is as a 0..1 ratio."""

    total = 0
    for message in prompt_messages:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += len(str(part.get("text", "")))
                else:
                    total += len(str(part))
        else:
            total += len(str(content))
    return min(1.0, total / 32000.0)


__all__ = [
    "_drain_steer_messages",
    "_estimate_context_fullness",
    "_filter_tools_by_agent_def",
    "_fire_system_agent_trigger",
    "_model_for_stream_phase",
    "_model_with_tools_for_stream_phase",
    "_outcome_attempt_index",
    "_outcome_max_attempts",
    "_resolve_agent_definition",
    "_should_force_degraded_skill_recovery_answer",
    "_web_fetch_args",
    "_with_focus_agent_turn_metadata",
    "_with_stream_phase",
]
