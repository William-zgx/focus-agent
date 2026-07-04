"""Composable context assembly pipeline.

Inspired by a two-stage message pipeline (``transformContext`` ->
``convertToLlm``) where discrete stages each mutate a shared
:class:`PipelineContext` before it is handed to the model. Stages are
declared via the :class:`ContextStage` protocol so that callers can
reorder, remove, or replace them without touching the rest of the graph.

The default pipeline assembled by :func:`create_default_pipeline` mirrors
the context-building logic spread across
:mod:`focus_agent.engine.graph_memory_nodes` today, but exposes each
concern (memory retrieval, budget calculation, skill injection, role
prompt, tool filtering, pinned facts, rolling summary) as an independent
object that can be unit-tested in isolation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger("focus_agent.engine.context_pipeline")


# ---------------------------------------------------------------------------
# Core context carrier
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    """Mutable bag threaded through every :class:`ContextStage`.

    Stages read the input fields (``messages``, ``system_prompt``,
    ``model``, ``available_tools``, ``context_budget``) and append to the
    output fields (``assembled_messages``, ``extra_blocks``, ``metadata``).
    The final caller (typically the model-invocation node) consumes
    ``assembled_messages`` and ``extra_blocks`` to build the LLM request.
    """

    thread_id: str
    messages: list[Any]
    system_prompt: str | None
    model: str
    available_tools: list[Any]
    context_budget: Any | None = None
    # --- output fields, populated by stages ---
    assembled_messages: list[Any] = field(default_factory=list)
    extra_blocks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage protocol
# ---------------------------------------------------------------------------


class ContextStage(Protocol):
    """A single composable step in context assembly.

    Implementations MUST mutate ``ctx`` in place (appending to
    ``assembled_messages``/``extra_blocks`` or stashing diagnostic data in
    ``metadata``) and MUST NOT raise for ordinary "nothing to do" cases.
    """

    name: str

    async def apply(self, ctx: PipelineContext) -> None:
        """Apply this stage's transformation to ``ctx``."""
        ...


# ---------------------------------------------------------------------------
# Built-in stages
# ---------------------------------------------------------------------------


@dataclass
class MemoryRetrievalStage:
    """Retrieve relevant memories and render them into ``extra_blocks``.

    The stage operates in one of three modes, in priority order:

    1. If ``ctx.metadata`` already carries a ``memory_prompt_block`` string
       (produced by the legacy ``retrieve_memory`` graph node) it is reused
       verbatim so the pipeline never duplicates retrieval work.
    2. Else, if ``ctx.metadata["retrieved_memories"]`` is populated (a list
       of dicts each with ``summary``/``content``/``fact`` keys) the stage
       renders them into a single block.
    3. Else, if a ``memory_retriever`` service, ``request_context``, state
       snapshot, latest user query, and prompt mode are all supplied via
       metadata, the stage performs live retrieval. This path supports
       future standalone use where the pipeline fully replaces the legacy
       retrieve_memory node.

    If none of those sources are available the stage is a silent no-op.
    """

    name: str = "memory_retrieval"
    memory_retriever: Any | None = None

    async def apply(self, ctx: PipelineContext) -> None:
        augment = _augment_mode(ctx)
        # 1. Pre-rendered block left by the legacy retrieve_memory node.
        pre_rendered = ctx.metadata.get("memory_prompt_block")
        if pre_rendered:
            block = str(pre_rendered).strip()
            if block:
                # In augment mode the legacy assemble_context node will already
                # inject the memory block; do not double-append.
                if not augment:
                    ctx.extra_blocks.append(block)
                ctx.metadata["memory_source"] = "pre_rendered"
            return

        # 2. Already-retrieved memory records (list[dict]).
        retrieved = ctx.metadata.get("retrieved_memories") or []
        if retrieved:
            lines: list[str] = []
            for item in retrieved:
                if not isinstance(item, dict):
                    continue
                text = item.get("summary") or item.get("content") or item.get("fact")
                if text:
                    lines.append(str(text))
            if lines:
                if not augment:
                    block = "Relevant memories:\n" + "\n".join(f"- {line}" for line in lines)
                    ctx.extra_blocks.append(block)
                ctx.metadata["memory_source"] = "retrieved_memories"
                ctx.metadata["retrieved_memories_applied"] = len(lines)
            return

        # 3. Live retrieval path — used only when the pipeline runs standalone
        #    (i.e. without a preceding retrieve_memory node).
        if self.memory_retriever is None:
            logger.debug(
                "MemoryRetrievalStage: no retriever or pre-retrieved data; skipping (thread=%s)",
                ctx.thread_id,
            )
            return
        request_context = ctx.metadata.get("request_context")
        state_snapshot = ctx.metadata.get("state_snapshot") or {}
        query = ctx.metadata.get("latest_user_query", "")
        prompt_mode = ctx.metadata.get("prompt_mode")
        if request_context is None or not query:
            logger.debug(
                "MemoryRetrievalStage: retriever present but insufficient context; skipping (thread=%s)",
                ctx.thread_id,
            )
            return
        try:
            bundle = self.memory_retriever.retrieve_for_turn(
                context=request_context,
                state=dict(state_snapshot),
                query=query,
                prompt_mode=prompt_mode,
            )
        except Exception:  # noqa: BLE001 - retrieval failure must not break assembly
            logger.exception(
                "MemoryRetrievalStage: live retrieval failed (thread=%s)", ctx.thread_id
            )
            return
        try:
            # Local import keeps the engine package usable in contexts where
            # the memory subpackage is not wired up (tests, minimal builds).
            from ..memory import render_memory_block

            block = render_memory_block(bundle)
        except Exception:  # noqa: BLE001
            logger.exception(
                "MemoryRetrievalStage: render_memory_block failed (thread=%s)", ctx.thread_id
            )
            return
        if block and block.strip():
            ctx.extra_blocks.append(block.strip())
            ctx.metadata["memory_source"] = "live_retrieval"
            ctx.metadata["memory_prompt_block"] = block.strip()
            ctx.metadata["memory_retrieval_plan"] = getattr(bundle, "retrieval_plan", None)


def _augment_mode(ctx: PipelineContext) -> bool:
    """Return True when the pipeline is running alongside (not replacing) legacy assembly.

    In augment mode, stages that duplicate blocks already produced by
    ``make_assemble_context_node`` (memory, skills, pinned facts, rolling
    summary) populate ``ctx.metadata`` for observability but do NOT append
    to ``ctx.extra_blocks``, so the final prompt does not contain the same
    section twice.
    """
    return bool(ctx.metadata.get("augment_mode"))


@dataclass
class ContextBudgetStage:
    """Calculate and attach a token budget for the turn.

    Reads ``ctx.context_budget`` (a :class:`~focus_agent.core.types.ContextBudget`
    or ``None``) and populates ``ctx.metadata["effective_budget"]`` with a
    normalized budget view used by downstream stages (notably summary
    compaction).
    """

    name: str = "context_budget"
    default_prompt_token_limit: int = 128_000

    async def apply(self, ctx: PipelineContext) -> None:
        budget = ctx.context_budget
        if budget is None:
            effective = {
                "prompt_token_limit": self.default_prompt_token_limit,
                "chars_per_token": 4,
                "recent_message_limit": 12,
            }
        else:
            # Accept either a ContextBudget pydantic model or a plain dict.
            if hasattr(budget, "model_dump"):
                effective = budget.model_dump()
            elif isinstance(budget, dict):
                effective = dict(budget)
            else:
                effective = {
                    "prompt_token_limit": getattr(
                        budget, "prompt_token_limit", self.default_prompt_token_limit
                    ),
                    "chars_per_token": getattr(budget, "chars_per_token", 4),
                    "recent_message_limit": getattr(budget, "recent_message_limit", 12),
                }
        ctx.metadata["effective_budget"] = effective
        logger.debug(
            "ContextBudgetStage: budget=%s (thread=%s)",
            effective.get("prompt_token_limit"),
            ctx.thread_id,
        )


@dataclass
class SkillInjectionStage:
    """Inject active-skill documentation into the system prompt.

    Mirrors the ``active_skills_block`` / ``available_skills_block``
    handling in ``make_assemble_context_node``. If a skill registry is
    supplied it will be queried with ``ctx.metadata.get("active_skill_ids")``;
    otherwise the stage is a no-op.
    """

    name: str = "skill_injection"
    skill_registry: Any | None = None

    async def apply(self, ctx: PipelineContext) -> None:
        active_ids = ctx.metadata.get("active_skill_ids") or ()
        # If the legacy assemble_context already rendered the blocks (present
        # in metadata), skip live registry calls but still expose them.
        pre_active = ctx.metadata.get("active_skills_block")
        pre_available = ctx.metadata.get("available_skills_block")
        if (pre_active is not None or pre_available is not None) and self.skill_registry is None:
            if pre_active and not _augment_mode(ctx):
                ctx.extra_blocks.append(str(pre_active))
            if pre_available and not _augment_mode(ctx):
                ctx.extra_blocks.append(str(pre_available))
            return
        if self.skill_registry is None or not active_ids:
            return
        try:
            active_block = self.skill_registry.render_active_skills_block(tuple(active_ids))
            available_block = self.skill_registry.render_available_skills_block()
        except Exception:  # noqa: BLE001 - registry failure must not break assembly
            logger.exception(
                "SkillInjectionStage: registry render failed (thread=%s)", ctx.thread_id
            )
            return
        if active_block and not _augment_mode(ctx):
            ctx.extra_blocks.append(active_block)
        if available_block and not _augment_mode(ctx):
            ctx.extra_blocks.append(available_block)
        ctx.metadata["active_skills_block"] = active_block
        ctx.metadata["available_skills_block"] = available_block


@dataclass
class RolePromptStage:
    """Prepend a role-specific system prompt based on the agent definition.

    Reads ``ctx.metadata["agent_definition"]`` (an object exposing a
    ``system_prompt`` or ``role`` attribute, or a plain mapping). If no
    definition is supplied the stage leaves ``ctx.system_prompt`` unchanged.
    """

    name: str = "role_prompt"
    default_role: str = "executor"

    async def apply(self, ctx: PipelineContext) -> None:
        agent_def = ctx.metadata.get("agent_definition")
        role_prompt: str | None = None
        if agent_def is not None:
            role_prompt = (
                getattr(agent_def, "system_prompt", None)
                or (agent_def.get("system_prompt") if isinstance(agent_def, dict) else None)
            )
            role = (
                getattr(agent_def, "role", None)
                or (agent_def.get("role") if isinstance(agent_def, dict) else None)
                or self.default_role
            )
        else:
            role = self.default_role
        ctx.metadata["resolved_role"] = role
        if role_prompt:
            if ctx.system_prompt:
                ctx.system_prompt = f"{role_prompt}\n\n{ctx.system_prompt}"
            else:
                ctx.system_prompt = role_prompt


@dataclass
class ToolFilteringStage:
    """Filter ``available_tools`` against the agent definition's tool policy.

    Reads ``ctx.metadata["tool_policy"]`` which may be a list of allowed
    tool names (``"*"`` is treated as "allow all"), or an object with an
    ``allowed`` attribute. Matching is case-sensitive.
    """

    name: str = "tool_filtering"
    wildcard: str = "*"

    async def apply(self, ctx: PipelineContext) -> None:
        policy = ctx.metadata.get("tool_policy")
        if policy is None:
            return  # no policy -> keep all tools

        if hasattr(policy, "allowed"):
            allowed = list(policy.allowed)
        elif isinstance(policy, (list, tuple, set)):
            allowed = [str(item) for item in policy]
        elif isinstance(policy, dict):
            allowed = [str(item) for item in (policy.get("allowed") or [])]
        else:
            allowed = [str(policy)]

        if self.wildcard in allowed:
            ctx.metadata["filtered_tools"] = list(ctx.available_tools)
            return

        def _tool_name(tool: Any) -> str:
            return str(
                getattr(tool, "name", None)
                or (tool.get("name") if isinstance(tool, dict) else str(tool))
            )

        filtered = [tool for tool in ctx.available_tools if _tool_name(tool) in allowed]
        ctx.metadata["filtered_tools"] = filtered
        ctx.metadata["tools_dropped"] = len(ctx.available_tools) - len(filtered)
        logger.debug(
            "ToolFilteringStage: kept %d/%d tools (thread=%s)",
            len(filtered),
            len(ctx.available_tools),
            ctx.thread_id,
        )


@dataclass
class PinnedFactsStage:
    """Inject pinned facts into the extra context blocks.

    Reads ``pinned_facts`` (a list of :class:`~focus_agent.core.types.PinnedFact`
    or plain strings) and ``pinned_items`` (legacy free-form strings) from
    ``ctx.metadata``. Facts are rendered as a dedicated block so the model
    treats them as high-priority context.
    """

    name: str = "pinned_facts"

    async def apply(self, ctx: PipelineContext) -> None:
        pinned_facts = ctx.metadata.get("pinned_facts") or []
        pinned_items = ctx.metadata.get("pinned_items") or []
        lines: list[str] = []
        for fact in pinned_facts:
            if hasattr(fact, "fact"):
                text = fact.fact
            elif isinstance(fact, dict):
                text = fact.get("fact") or fact.get("content") or str(fact)
            else:
                text = str(fact)
            if text:
                lines.append(f"- {text}")
        for item in pinned_items:
            text = str(item).strip()
            if text and text not in lines:
                lines.append(f"- {text}")
        if lines:
            block = "Pinned context:\n" + "\n".join(lines)
            if not _augment_mode(ctx):
                ctx.extra_blocks.append(block)
            ctx.metadata["pinned_facts_block"] = block


@dataclass
class RollingSummaryStage:
    """Prepend a rolling summary to older messages.

    If ``ctx.metadata["rolling_summary"]`` is present it is prepended as a
    synthetic block in ``extra_blocks`` so older turns do not need to be
    sent verbatim. The stage is placed before stages that copy
    ``ctx.messages`` into ``assembled_messages`` so the summary surfaces
    ahead of the real history.
    """

    name: str = "rolling_summary"
    summary_prefix: str = "Summary of earlier conversation:"

    async def apply(self, ctx: PipelineContext) -> None:
        summary = ctx.metadata.get("rolling_summary")
        if not summary:
            return
        block = f"{self.summary_prefix}\n{summary}"
        if not _augment_mode(ctx):
            ctx.extra_blocks.append(block)
        ctx.metadata["rolling_summary_applied"] = True
        ctx.metadata["rolling_summary_block"] = block


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


@dataclass
class ContextPipeline:
    """Ordered container of :class:`ContextStage` instances.

    Stages are applied sequentially; a stage raising an exception aborts
    the build (wrapped in a :class:`RuntimeError` identifying the failing
    stage) so callers can diagnose partial context.
    """

    stages: list[ContextStage] = field(default_factory=list)

    def add_stage(self, stage: ContextStage) -> None:
        """Append ``stage`` to the end of the pipeline."""
        self.stages.append(stage)

    async def build(self, ctx: PipelineContext) -> PipelineContext:
        """Run every stage against ``ctx`` and return it (mutated in place)."""
        for stage in self.stages:
            try:
                await stage.apply(ctx)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "ContextPipeline: stage %s failed (thread=%s)",
                    getattr(stage, "name", type(stage).__name__),
                    ctx.thread_id,
                )
                raise RuntimeError(
                    f"Context stage '{getattr(stage, 'name', type(stage).__name__)}' failed: {exc}"
                ) from exc

        # Final assembly: if no earlier stage populated assembled_messages,
        # copy the original messages through.
        if not ctx.assembled_messages:
            ctx.assembled_messages = list(ctx.messages)
        return ctx

    def describe(self) -> list[str]:
        """Return the ordered list of stage names (for observability/debug)."""
        return [getattr(stage, "name", type(stage).__name__) for stage in self.stages]


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def create_default_pipeline(
    *,
    memory_retriever: Any | None = None,
    skill_registry: Any | None = None,
    extra_stages: list[ContextStage] | None = None,
) -> ContextPipeline:
    """Build a :class:`ContextPipeline` with the standard stage ordering.

    The order mirrors the implicit phases inside
    :func:`make_assemble_context_node`:

    1. :class:`MemoryRetrievalStage`
    2. :class:`ContextBudgetStage`
    3. :class:`SkillInjectionStage`
    4. :class:`RolePromptStage`
    5. :class:`ToolFilteringStage`
    6. :class:`PinnedFactsStage`
    7. :class:`RollingSummaryStage`

    Callers can inject ``extra_stages`` to append additional custom stages
    (e.g. a context-engineering compression stage) without reordering the
    built-ins.
    """
    stages: list[ContextStage] = [
        MemoryRetrievalStage(memory_retriever=memory_retriever),
        ContextBudgetStage(),
        SkillInjectionStage(skill_registry=skill_registry),
        RolePromptStage(),
        ToolFilteringStage(),
        PinnedFactsStage(),
        RollingSummaryStage(),
    ]
    if extra_stages:
        stages.extend(extra_stages)
    return ContextPipeline(stages=stages)


__all__ = [
    "ContextBudgetStage",
    "ContextPipeline",
    "ContextStage",
    "MemoryRetrievalStage",
    "PinnedFactsStage",
    "PipelineContext",
    "RolePromptStage",
    "RollingSummaryStage",
    "SkillInjectionStage",
    "ToolFilteringStage",
    "create_default_pipeline",
]
