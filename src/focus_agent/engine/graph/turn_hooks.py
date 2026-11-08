"""Turn lifecycle nodes shared by every agent core."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from langchain.messages import HumanMessage

from ...core.state import AgentState
from .memory_nodes import maybe_interrupt_for_merge
from .memory_nodes import summarize_turn as _summarize_turn_impl
from .tool_execution import HarnessToolServices

logger = logging.getLogger(__name__)

_TURN_SCOPED_PLAN_META_KEYS = frozenset(
    {"replan_requested", "live_web_answer_repair_count", "skill_execution_answer_repair_count"}
)


def _fire_system_agent(
    runner: Any | None,
    trigger_name: str,
    ctx: dict[str, Any],
) -> None:
    """Fire system agents for ``trigger_name`` as fire-and-forget background tasks.

    Safe to call from a sync node. Never raises; if no running event loop is
    available (e.g. tests invoking the graph synchronously) the trigger is
    silently skipped.
    """

    if runner is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        loop.create_task(runner.trigger(trigger_name, ctx))
    except Exception:  # noqa: BLE001
        logger.debug(
            "Failed to fire system agent trigger '%s'",
            trigger_name,
            exc_info=True,
        )


def _build_system_agent_ctx(state: AgentState, runtime: Any) -> dict[str, Any]:
    """Build a minimal context dict for system agent handlers."""

    ctx = getattr(runtime, "context", None)
    return {
        "state": dict(state),
        "context": ctx,
        "user_id": getattr(ctx, "user_id", None),
        "root_thread_id": getattr(ctx, "root_thread_id", None),
    }


class TurnLifecycle:
    """Owns the start/end hooks of one compiled graph.

    ``bootstrap_turn``, ``summarize_turn`` and ``maybe_interrupt_for_merge`` are
    graph nodes; services address them by name through ``update_state``.
    """

    def __init__(
        self,
        *,
        harness_services: HarnessToolServices | None,
        system_agent_runner: Any | None,
        summarize: Callable[[AgentState], dict[str, Any]] = _summarize_turn_impl,
    ) -> None:
        self._services = harness_services
        self._system_agent_runner = system_agent_runner
        self._summarize = summarize
        self._agent_start_fired_threads: set[str] = set()

    def _turn_ctx(self, state: AgentState) -> dict[str, Any]:
        services = self._services
        thread_id = state.get("thread_id") if isinstance(state, dict) else None
        return {
            "thread_id": thread_id,
            "run_id": services.run_id if services else None,
            "agent_name": (services.active_agent_name if services else None) or "focus_agent",
            "state": state,
        }

    def _fire_on_turn_start(self, state: AgentState) -> None:
        services = self._services
        if services is not None and services.extension_registry is not None:
            thread_id = str(state.get("thread_id", "") or "")
            if thread_id not in self._agent_start_fired_threads:
                try:
                    from ...harness.extensions import ExtensionContext

                    ctx = ExtensionContext(
                        thread_id=thread_id,
                        run_id=services.run_id,
                        agent_name=services.active_agent_name or "focus_agent",
                    )
                    services.extension_registry.fire_hook("on_agent_start", ctx)
                    self._agent_start_fired_threads.add(thread_id)
                except Exception:  # noqa: BLE001
                    logger.warning("extension on_agent_start failed", exc_info=True)
        if services is None or services.middleware_stack is None:
            return
        try:
            services.middleware_stack.on_turn_start(self._turn_ctx(state))
        except Exception:  # noqa: BLE001
            logger.warning("middleware.on_turn_start failed", exc_info=True)

    def _fire_on_turn_end(self, state: AgentState) -> None:
        services = self._services
        if services is None or services.middleware_stack is None:
            return
        try:
            services.middleware_stack.on_turn_end(self._turn_ctx(state))
        except Exception:  # noqa: BLE001
            logger.warning("middleware.on_turn_end failed", exc_info=True)

    def bootstrap_turn(self, state: AgentState, runtime: Any) -> dict[str, Any]:
        self._fire_on_turn_start(state)
        human_count = sum(1 for m in state.get("messages", []) or [] if isinstance(m, HumanMessage))
        if human_count <= 1:
            _fire_system_agent(
                self._system_agent_runner,
                "first_user_message",
                _build_system_agent_ctx(state, runtime),
            )
        # Plan/reflect state and answer-repair budgets are scoped to one turn;
        # bootstrap runs only at START, so interrupt resumes keep them.
        plan_meta = {
            key: value
            for key, value in (state.get("plan_meta") or {}).items()
            if key not in _TURN_SCOPED_PLAN_META_KEYS
        }
        return {
            "llm_calls": state.get("llm_calls", 0),
            "plan": None,
            "current_step_id": "",
            "reflection": None,
            "plan_meta": plan_meta,
        }

    def summarize_turn(self, state: AgentState, runtime: Any) -> dict[str, Any]:
        result = self._summarize(state)
        _fire_system_agent(
            self._system_agent_runner,
            "turn_end",
            {
                **_build_system_agent_ctx(state, runtime),
                "rolling_summary": result.get("rolling_summary", ""),
            },
        )
        return result

    def maybe_interrupt_for_merge(self, state: AgentState) -> dict[str, Any]:
        self._fire_on_turn_end(state)
        return maybe_interrupt_for_merge(state)


__all__ = ["TurnLifecycle"]
