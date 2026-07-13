"""High-level :class:`FocusAgent` facade.

This module wraps the low level :class:`FocusAgentHarness` with a
stream-oriented façade that drives :class:`AgentEventPublisher` through a
normalized run lifecycle.

It exists to make Task B ("wire AgentEventPublisher into facade streaming") a
small, contained change: previously the producer code in
``replay_streaming._produce_run_stream`` manually translated raw LangGraph
chunks into bridge events; this facade produces the same canonical events but
through the typed publisher API while keeping backward compatibility.

The facade is *not* required to use the harness — direct callers may still
drive :meth:`FocusAgentHarness.stream_chunks` and publish events themselves if
they need fine-grained control.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from ...core.tool_protocol import safe_visible_text_transition
from ...transport.stream_events import (
    STREAM_VISIBILITY_VISIBLE,
    extract_reasoning_delta,
    extract_tool_call_chunks,
    extract_visible_text_candidate_delta,
    looks_like_stream_visible_text_artifact,
    safe_stream_visible_text_transition,
    sanitize_stream_metadata,
    sanitize_stream_visible_text,
    stream_visibility_phase_from_metadata,
)
from ..streaming.publisher import AgentEventPublisher
from .factory import FocusAgentHarness
from .mention import extract_primary_agent

logger = logging.getLogger("focus_agent.harness.agents.facade")


@dataclass(slots=True)
class StreamResult:
    """Summary returned by :meth:`FocusAgent.stream` after the run completes."""

    run_id: str
    thread_id: str
    status: str
    final_state: dict[str, Any] | None = None
    visible_text: str = ""
    interrupted: bool = False


class FocusAgent:
    """Streaming facade over :class:`FocusAgentHarness`.

    Exposes a coroutine-driven :meth:`stream` method that drives the graph,
    publishes events through :class:`AgentEventPublisher`, and aggregates
    visible assistant text into the returned :class:`StreamResult`.
    """

    def __init__(self, harness: FocusAgentHarness) -> None:
        self._harness = harness

    @property
    def harness(self) -> FocusAgentHarness:
        return self._harness

    @property
    def stream_bridge(self) -> Any:
        return self._harness.stream_bridge

    @property
    def tool_registry(self) -> Any:
        return getattr(self._harness, "tool_registry", None)

    # ------------------------------------------------------------------ API
    async def stream(
        self,
        *,
        run_id: str,
        thread_id: str,
        message: str,
        config: dict[str, Any],
        context: Any,
        settings: Any,
        checkpointer: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StreamResult:
        """Run a single turn, publishing events via AgentEventPublisher.

        Returns a :class:`StreamResult` summarizing what happened. All
        streaming deltas are published to the harness ``stream_bridge`` as a
        side effect so SSE subscribers can observe them.
        """
        # --- @mention parsing ---------------------------------------------
        agent_registry = getattr(self._harness, "agent_definition_registry", None)
        agent_name, clean_message = extract_primary_agent(message, agent_registry)
        run_metadata = dict(metadata or {})
        if agent_name:
            run_metadata.setdefault("target_agent", agent_name)

        # --- Build payload ------------------------------------------------
        try:
            import langchain.messages as langchain_messages
        except Exception:  # pragma: no cover - langchain always present at runtime
            langchain_messages = None  # type: ignore[assignment]
        if langchain_messages is not None:
            payload: Any = {"messages": [langchain_messages.HumanMessage(content=clean_message)]}
        else:
            payload = {"messages": [{"role": "user", "content": clean_message}]}
        payload["metadata"] = run_metadata

        return await self._run_stream_graph(
            run_id=run_id,
            thread_id=thread_id,
            payload=payload,
            config=config,
            context=context,
            settings=settings,
            checkpointer=checkpointer,
            metadata=run_metadata,
        )

    async def _run_stream_graph(
        self,
        *,
        run_id: str,
        thread_id: str,
        payload: Any,
        config: dict[str, Any],
        context: Any,
        settings: Any,
        checkpointer: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StreamResult:
        """Drive the graph, translating chunks into AgentEventPublisher calls.

        Recognised LangGraph v2 chunk shapes:

        * ``{"type": "messages", "data": (message_chunk, metadata)}``
        * ``{"type": "custom",   "data": {...}}``
        * ``{"type": "updates",  "data": {...}}``
        * ``{"type": "tasks",    "data": {...}}``

        This method is intentionally forgiving: if the publisher fails it
        falls back to direct ``bridge.publish`` so existing observers keep
        working.
        """
        bridge = self._harness.stream_bridge
        publisher = AgentEventPublisher.for_harness(
            self._harness, run_id=run_id, thread_id=thread_id
        )

        visible_text_buffer = ""
        visible_text_pending = ""
        reasoning_buffer = ""
        reasoning_text_pending = ""
        interrupted = False
        success = False
        final_state: dict[str, Any] | None = None

        # Start-of-turn lifecycle.
        await _safe_publish(publisher.on_turn_started(metadata=metadata or {}))

        tool_args_buffers: dict[str, str] = {}

        try:
            async for chunk in self._harness.stream_chunks(
                checkpointer=checkpointer,
                settings=settings,
                payload=payload,
                config=config,
                context=context,
            ):
                if chunk is None:
                    await _safe_publish(publisher.on_heartbeat())
                    continue

                chunk_type = chunk.get("type")
                data = chunk.get("data")

                if chunk_type == "messages":
                    message_chunk, chunk_metadata = data
                    safe_metadata = sanitize_stream_metadata(chunk_metadata)
                    tool_calls = extract_tool_call_chunks(message_chunk)
                    visible_delta = extract_visible_text_candidate_delta(message_chunk)
                    safe_visible_delta = sanitize_stream_visible_text(visible_delta)
                    hide_visible_delta = (
                        stream_visibility_phase_from_metadata(chunk_metadata)
                        != STREAM_VISIBILITY_VISIBLE
                        or bool(tool_calls)
                        or (
                            looks_like_stream_visible_text_artifact(visible_delta)
                            and not safe_visible_delta
                        )
                    )
                    if hide_visible_delta:
                        visible_text_pending = ""
                    elif visible_delta:
                        next_visible_text, visible_text_pending = (
                            safe_stream_visible_text_transition(
                                visible_text_buffer,
                                visible_delta,
                                pending_text=visible_text_pending,
                            )
                        )
                        if next_visible_text.startswith(visible_text_buffer):
                            delta_text = next_visible_text[len(visible_text_buffer) :]
                        else:
                            delta_text = next_visible_text
                        visible_text_buffer = next_visible_text
                        if delta_text:
                            await _safe_publish(
                                publisher.on_assistant_text_delta(
                                    delta_text,
                                    message_id=str(getattr(message_chunk, "id", "") or run_id),
                                    metadata=safe_metadata,
                                )
                            )
                    reasoning_delta = extract_reasoning_delta(message_chunk)
                    if reasoning_delta:
                        next_reasoning_text, reasoning_text_pending = safe_visible_text_transition(
                            reasoning_buffer,
                            reasoning_delta,
                            pending_text=reasoning_text_pending,
                        )
                        if next_reasoning_text.startswith(reasoning_buffer):
                            publish_reasoning_delta = next_reasoning_text[len(reasoning_buffer) :]
                        else:
                            publish_reasoning_delta = next_reasoning_text
                        reasoning_buffer = next_reasoning_text
                        if publish_reasoning_delta:
                            await _safe_publish(
                                publisher.on_reasoning_delta(
                                    publish_reasoning_delta,
                                    message_id=str(getattr(message_chunk, "id", "") or run_id),
                                )
                            )
                    for tc in tool_calls:
                        tc_id = tc.get("id") or tc.get("tool_call_id")
                        tc_name = tc.get("name")
                        tc_args = tc.get("args_delta")
                        if tc_id and tc_id not in tool_args_buffers:
                            tool_args_buffers[tc_id] = ""
                            await _safe_publish(
                                publisher.on_tool_call_started(
                                    tool_call_id=tc_id,
                                    tool_name=tc_name or "",
                                    args_preview=(str(tc_args)[:200] if tc_args else None),
                                    metadata=safe_metadata,
                                )
                            )
                        if tc_id and tc_args is not None:
                            args_str = tc_args if isinstance(tc_args, str) else str(tc_args)
                            tool_args_buffers[tc_id] += args_str
                            await _safe_publish(
                                publisher.on_tool_call_delta(
                                    tool_call_id=tc_id,
                                    args_delta=args_str,
                                    tool_name=tc_name,
                                    metadata=safe_metadata,
                                )
                            )

                elif chunk_type == "updates":
                    # Tool results come back via node updates.
                    for tool_result in _iter_tool_results(data):
                        tr_id = tool_result.get("tool_call_id") or tool_result.get("id")
                        is_err = bool(tool_result.get("error"))
                        if tr_id:
                            if tr_id in tool_args_buffers:
                                await _safe_publish(publisher.on_tool_call_ended(tr_id))
                                tool_args_buffers.pop(tr_id, None)
                            await _safe_publish(
                                publisher.on_tool_result(
                                    tool_call_id=tr_id,
                                    result=tool_result.get("result"),
                                    tool_name=tool_result.get("name"),
                                    is_error=is_err,
                                )
                            )
                    final_state = _coerce_dict(data)
                    await _safe_publish(publisher.on_state_update(data=final_state))

                elif chunk_type == "custom":
                    event_name = None
                    payload_data: dict[str, Any] = {}
                    if isinstance(data, dict):
                        event_name = data.get("event")
                        payload_data = {k: v for k, v in data.items() if k != "event"}
                    if event_name:
                        await _safe_publish(publisher.on_custom(event_name, **payload_data))

                elif chunk_type == "tasks":
                    task_payload = data if isinstance(data, dict) else {"value": data}
                    await _safe_publish(publisher.on_task_update(**task_payload))

            success = True
        except asyncio.CancelledError:
            interrupted = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error during streamed turn %s: %s", run_id, exc, exc_info=True)
            success = False
        finally:
            # Flush any tool calls whose result we never saw.
            for tc_id in list(tool_args_buffers):
                await _safe_publish(publisher.on_tool_call_ended(tc_id))
                tool_args_buffers.pop(tc_id, None)

            # Always emit message.completed so the client never hangs waiting
            # for a completion signal.  When the model produced no visible
            # assistant text (e.g. only tool calls), send an empty content
            # string -- downstream consumers can still detect turn completion.
            await _safe_publish(publisher.on_message_completed(content=visible_text_buffer or ""))
            if interrupted:
                await _safe_publish(publisher.on_turn_interrupted())
                status = "interrupted"
            elif success:
                await _safe_publish(publisher.on_turn_completed("success", final_state=final_state))
                status = "success"
            else:
                await _safe_publish(publisher.on_turn_completed("error"))
                status = "error"

        # If the publisher fell into failed mode, close the stream directly so
        # subscribers do not hang waiting for run.closed.
        if publisher.failed and bridge is not None:
            try:
                publish_end = getattr(bridge, "publish_end", None)
                if callable(publish_end):
                    await publish_end(run_id)
            except Exception:  # noqa: BLE001
                pass

        return StreamResult(
            run_id=run_id,
            thread_id=thread_id,
            status=status,
            final_state=final_state,
            visible_text=visible_text_buffer,
            interrupted=interrupted,
        )


# --------------------------------------------------------------------- helpers
async def _safe_publish(coro: Any) -> None:
    """Await a publisher coroutine, logging but not surfacing errors."""
    if coro is None:
        return
    try:
        await coro
    except Exception:  # noqa: BLE001
        logger.debug("publisher event raised (ignored)", exc_info=True)


def _iter_tool_results(updates: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of tool results from LangGraph 'updates' payload."""
    results: list[dict[str, Any]] = []
    if not isinstance(updates, dict):
        return results
    for _node, node_update in updates.items():
        if not isinstance(node_update, dict):
            continue
        messages = node_update.get("messages")
        if not messages:
            continue
        if not isinstance(messages, (list, tuple)):
            messages = [messages]
        for msg in messages:
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                # This is actually a request, skip.
                continue
            tr_id = getattr(msg, "tool_call_id", None)
            if tr_id:
                results.append(
                    {
                        "tool_call_id": tr_id,
                        "name": getattr(msg, "name", None),
                        "result": getattr(msg, "content", None),
                        "error": bool(getattr(msg, "status", None) == "error"),
                    }
                )
    return results


def _coerce_dict(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    return {"value": data}


__all__ = ["FocusAgent", "StreamResult"]
