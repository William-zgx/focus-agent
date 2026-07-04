"""Graph node that runs the :class:`~focus_agent.engine.context_pipeline.ContextPipeline`.

The node plugs into the existing graph between ``retrieve_memory`` and
``assemble_context``. It pulls data already present in state (retrieved
memories, pinned facts, rolling summary, active skill ids, etc.) and feeds
it through the pipeline. It runs in ``augment_mode`` by default, meaning
stages that duplicate work done by the legacy ``assemble_context`` node
only populate ``metadata``/diagnostics and do not emit blocks into
``ctx.extra_blocks`` — this guarantees zero prompt duplication while
letting us progressively move logic into the pipeline.

Failures are caught and logged; the node returns ``{}`` so the legacy
nodes continue to produce the full prompt and nothing breaks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from focus_agent.engine.context_pipeline import (
    ContextPipeline,
    PipelineContext,
    create_default_pipeline,
)

logger = logging.getLogger(__name__)


def _run_pipeline_async(pipeline: ContextPipeline, ctx: PipelineContext) -> Any:
    """Run ``pipeline.build(ctx)`` to completion on a fresh event loop.

    The node function is synchronous (mirroring the other graph nodes in
    :mod:`focus_agent.engine.graph_memory_nodes`), but the pipeline stages
    are declared as ``async`` for protocol flexibility. Stages today do not
    perform real awaits, but if future stages do (e.g. an embedding call)
    driving them through a proper loop keeps the contract honest.
    """
    return asyncio.run(pipeline.build(ctx))


def make_context_pipeline_node(
    context_pipeline: ContextPipeline | None = None,
    *,
    memory_retriever: Any | None = None,
    skill_registry: Any | None = None,
    agent_registry: Any | None = None,
) -> Any:
    """Create a LangGraph node that invokes the ``ContextPipeline``.

    All dependency arguments are optional: when a dependency is ``None`` the
    corresponding stages skip themselves, which keeps the node safe to wire
    into the graph in every environment (tests, minimal builds, etc.).

    The returned node is a plain synchronous function (mirroring the
    signature of the other memory/context graph nodes) so it works both
    when LangGraph drives the graph synchronously (``graph.invoke``) and
    asynchronously (``graph.ainvoke``).
    """
    pipeline = context_pipeline or create_default_pipeline(
        memory_retriever=memory_retriever,
        skill_registry=skill_registry,
    )

    def _run_pipeline(state: dict[str, Any], runtime: Any | None = None) -> dict[str, Any]:
        thread_id = (
            state.get("thread_id")
            or state.get("root_thread_id")
            or getattr(getattr(runtime, "context", None), "root_thread_id", "")
            or ""
        )
        messages = list(state.get("messages", []) or [])
        model = state.get("selected_model", "")
        system_prompt = state.get("system_prompt")
        available_tools = list(state.get("available_tools", []) or [])
        context_budget = state.get("context_budget")

        ctx = PipelineContext(
            thread_id=str(thread_id),
            messages=messages,
            system_prompt=system_prompt,
            model=model,
            available_tools=available_tools,
            context_budget=context_budget,
        )

        # --- Resolve active agent definition (role prompt / tool policy). ---
        active_agent_name = (
            state.get("active_agent_name")
            or (state.get("metadata") or {}).get("target_agent")
            or ""
        )
        agent_definition = None
        tool_policy = None
        if agent_registry is not None and active_agent_name:
            try:
                agent_definition = agent_registry.get(active_agent_name)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "context_pipeline_node: agent_registry lookup failed for %s",
                    active_agent_name,
                    exc_info=True,
                )
        if agent_definition is not None:
            tool_policy = (
                getattr(agent_definition, "allowed_tools", None)
                or (
                    agent_definition.get("allowed_tools")
                    if isinstance(agent_definition, dict)
                    else None
                )
                or getattr(agent_definition, "tools", None)
            )

        # --- Populate metadata from state for stages to consume. ---
        # ``augment_mode=True`` tells stages that legacy assemble_context will
        # still render the final prompt, so they should not double-append blocks.
        ctx.metadata["augment_mode"] = True
        ctx.metadata["state_snapshot"] = dict(state)
        request_context = getattr(runtime, "context", None) if runtime is not None else None
        ctx.metadata["request_context"] = request_context
        ctx.metadata["pinned_facts"] = list(state.get("pinned_facts", []) or [])
        ctx.metadata["pinned_items"] = list(state.get("pinned_items", []) or [])
        ctx.metadata["rolling_summary"] = state.get("rolling_summary", "") or ""
        ctx.metadata["user_constraints"] = list(state.get("user_constraints", []) or [])
        ctx.metadata["active_agent_name"] = active_agent_name
        ctx.metadata["agent_definition"] = agent_definition
        ctx.metadata["tool_policy"] = tool_policy
        ctx.metadata["agent_registry"] = agent_registry
        ctx.metadata["memory_retriever"] = memory_retriever
        ctx.metadata["skill_registry"] = skill_registry

        # Memory: prefer the already-produced state keys from retrieve_memory.
        ctx.metadata["retrieved_memories"] = list(state.get("retrieved_memories", []) or [])
        ctx.metadata["memory_prompt_block"] = state.get("memory_prompt_block") or ""
        ctx.metadata["memory_retrieval_plan"] = state.get("memory_retrieval_plan") or {}

        # Skills: prefer already-rendered blocks from state if present.
        active_skill_ids = list(state.get("active_skill_ids") or [])
        if runtime is not None and getattr(getattr(runtime, "context", None), "skill_hints", None):
            for hid in runtime.context.skill_hints:
                if hid not in active_skill_ids:
                    active_skill_ids.append(hid)
        ctx.metadata["active_skill_ids"] = tuple(active_skill_ids)
        if state.get("active_skills_block"):
            ctx.metadata["active_skills_block"] = state["active_skills_block"]
        if state.get("available_skills_block"):
            ctx.metadata["available_skills_block"] = state["available_skills_block"]

        # Latest user query for live-retrieval fallback path.
        try:
            from focus_agent.engine.graph_turn_helpers import _latest_human_message_text

            ctx.metadata["latest_user_query"] = _latest_human_message_text(messages) or ""
        except Exception:  # noqa: BLE001
            ctx.metadata["latest_user_query"] = ""

        # Prompt mode (coerce to string for stages).
        prompt_mode = state.get("prompt_mode")
        ctx.metadata["prompt_mode"] = str(prompt_mode) if prompt_mode is not None else "explore"

        # --- Run the pipeline. ---
        try:
            result_ctx = _run_pipeline_async(pipeline, ctx)
        except Exception as exc:  # noqa: BLE001 - never break the graph
            logger.warning(
                "ContextPipeline failed: %s; falling back to legacy assembly (thread=%s)",
                exc,
                thread_id,
            )
            return {}

        # --- Write results back to state. ---
        updates: dict[str, Any] = {}

        extra_blocks = list(result_ctx.extra_blocks or [])
        if extra_blocks:
            # In augment_mode we don't expect extra_blocks (the legacy
            # assemble_context node renders memory/pinned/summary sections),
            # but custom stages added via create_default_pipeline(extra_stages=...)
            # can opt in to producing them. Expose them under
            # ``context_extra_blocks`` so assemble_context can splice them
            # into the final prompt without duplication.
            updates["context_extra_blocks"] = extra_blocks

        # Expose pipeline metadata for downstream stages / observability.
        pipeline_meta = {
            "stages": pipeline.describe(),
            "effective_budget": result_ctx.metadata.get("effective_budget"),
            "resolved_role": result_ctx.metadata.get("resolved_role"),
            "memory_source": result_ctx.metadata.get("memory_source"),
            "tools_dropped": result_ctx.metadata.get("tools_dropped"),
            "rolling_summary_applied": bool(result_ctx.metadata.get("rolling_summary_applied")),
        }
        filtered_tools = result_ctx.metadata.get("filtered_tools")
        if filtered_tools is not None:
            pipeline_meta["filtered_tools_count"] = len(filtered_tools)
        updates["context_pipeline_meta"] = pipeline_meta

        if result_ctx.system_prompt and not state.get("assembled_context"):
            updates["system_prompt"] = result_ctx.system_prompt

        # When running outside augment mode (e.g. future standalone use),
        # surface assembled_messages so the model node can consume them.
        if result_ctx.assembled_messages and not ctx.metadata.get("augment_mode"):
            updates["assembled_messages"] = list(result_ctx.assembled_messages)

        logger.debug(
            "context_pipeline_node: produced %d extra block(s), stages=%s (thread=%s)",
            len(extra_blocks),
            pipeline_meta["stages"],
            thread_id,
        )
        return updates

    return _run_pipeline


__all__ = ["make_context_pipeline_node"]
