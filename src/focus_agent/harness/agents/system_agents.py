"""Hidden system agents that run automatically.

Inspired by opencode's Compaction, Title, and Summary background agents,
this module provides a tiny registry/runner for "system agents": short,
focused LLM calls that fire at well-defined lifecycle points (first user
message, context overflow, end of turn, or explicit manual request) and
produce metadata (titles, summaries, memory candidates) rather than
user-visible answers.

System agents are hidden by default: they do not appear in subagent
pickers, do not consume turns, and run as background ``asyncio`` tasks
so the main response is never blocked on them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Well-known trigger names. Kept as plain strings so new triggers can be
# introduced by callers without editing this module.
TRIGGER_FIRST_USER_MESSAGE = "first_user_message"
TRIGGER_CONTEXT_OVERFLOW = "context_overflow"
TRIGGER_TURN_END = "turn_end"
TRIGGER_MANUAL = "manual"

# Sentinel model id meaning "use the project's configured small/fast
# model". Handlers resolve this via ``ctx["model_factory"]`` when they
# build their LLM call.
SMALL_MODEL: None = None

# Default model id used when the caller does not supply one and the
# registry's default-small-model lookup fails. Handlers fall back to
# this only as a last resort; the model factory is expected to know how
# to resolve it.
FALLBACK_SMALL_MODEL_ID = "haiku"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class SystemAgent:
    """A hidden background agent bound to a lifecycle trigger."""

    #: Unique name (e.g. ``"title"``, ``"compaction"``).
    name: str
    #: Async handler ``async def handler(ctx: dict) -> Any`` that
    #: performs the work.
    handler: Callable[..., Any] = field(repr=False)
    #: Human-readable description used in logs/debug UI only.
    description: str = ""
    #: Lifecycle trigger that causes this agent to fire. One of
    #: :data:`TRIGGER_FIRST_USER_MESSAGE`, :data:`TRIGGER_CONTEXT_OVERFLOW`,
    #: :data:`TRIGGER_TURN_END`, :data:`TRIGGER_MANUAL`, or any custom
    #: trigger a caller chooses to emit.
    trigger: str = TRIGGER_MANUAL
    #: Model id to use. ``None`` means "use the small model" (the
    #: factory is expected to resolve a cheap/fast model).
    model: str | None = SMALL_MODEL
    #: If ``True`` (default), the agent is hidden from user-facing
    #: subagent lists and runs without producing a visible turn.
    hidden: bool = True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class SystemAgentRegistry:
    """Registry of :class:`SystemAgent` definitions keyed by name."""

    def __init__(self) -> None:
        self._agents: dict[str, SystemAgent] = {}

    def register(self, agent: SystemAgent) -> None:
        """Register ``agent``. Overwrites any previous agent with the same name."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> SystemAgent | None:
        """Return the agent registered under ``name``, or ``None``."""
        return self._agents.get(name)

    def list_by_trigger(self, trigger: str) -> list[SystemAgent]:
        """Return all agents bound to ``trigger``, in registration order."""
        return [agent for agent in self._agents.values() if agent.trigger == trigger]

    def list_all(self) -> list[SystemAgent]:
        """Return all registered agents in registration order."""
        return list(self._agents.values())


# ---------------------------------------------------------------------------
# Helpers used by the built-in handlers
# ---------------------------------------------------------------------------
def _format_messages_for_prompt(messages: list[Any], *, max_chars: int = 6000) -> str:
    """Render a list of langchain-style messages into a single prompt string.

    This is a best-effort renderer: it understands both langchain message
    objects (``.type``/``.content``) and plain ``{"role": ..., "content": ...}``
    dicts. Long conversations are truncated to ``max_chars`` to keep the
    system-agent calls cheap.
    """
    if not messages:
        return ""
    lines: list[str] = []
    total = 0
    for msg in messages:
        role: str
        content: str
        if isinstance(msg, dict):
            role = str(msg.get("role") or "unknown")
            content = str(msg.get("content") or "")
        else:
            role = str(
                getattr(msg, "type", None)
                or getattr(msg, "role", None)
                or msg.__class__.__name__.replace("Message", "").lower()
            )
            content = str(getattr(msg, "content", "") or "")
        content = content.strip()
        if not content:
            continue
        line = f"[{role}] {content}"
        total += len(line)
        if total > max_chars:
            lines.append("... (earlier messages truncated)")
            break
        lines.append(line)
    return "\n".join(lines)


def _message_content(msg: Any) -> str:
    """Extract plain-text content from a single message-like object."""
    if isinstance(msg, dict):
        return str(msg.get("content") or "").strip()
    return str(getattr(msg, "content", "") or "").strip()


async def _call_small_model(
    ctx: dict,
    *,
    system_prompt: str,
    user_prompt: str,
    agent: SystemAgent | None = None,
) -> str:
    """Invoke the configured small/fast model with a single prompt.

    Helper shared by the built-in handlers. Looks up ``model_factory`` in
    ``ctx``; the factory can be either a langchain-like model instance or
    a callable that returns one when given a model id.
    """
    factory = ctx.get("model_factory")
    if factory is None:
        raise RuntimeError(
            "system agent ctx is missing 'model_factory'; cannot invoke LLM"
        )

    model_id = (agent.model if agent is not None else None) or FALLBACK_SMALL_MODEL_ID
    thinking_mode = str(ctx.get("thinking_mode") or "")

    # Resolve a model instance. The factory may be:
    #   * a GraphModelFactory-like object exposing ``model_for(model_id, thinking_mode)``
    #   * a callable ``(model_id) -> model``
    #   * a model instance itself (duck-typed by ``ainvoke``)
    model: Any
    if hasattr(factory, "model_for") and callable(getattr(factory, "model_for")):
        model = factory.model_for(model_id, thinking_mode)
    elif callable(factory):
        model = factory(model_id)
    else:
        model = factory

    messages_for_model = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = await model.ainvoke(messages_for_model)
    except TypeError:
        # Some model wrappers accept (system, human) message objects rather
        # than raw dicts; fall back to langchain imports lazily.
        try:
            from langchain.messages import SystemMessage, HumanMessage

            response = await model.ainvoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"failed to invoke small model '{model_id}': {exc}") from exc

    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    return str(content or "").strip()


# ---------------------------------------------------------------------------
# Built-in system agent handlers
# ---------------------------------------------------------------------------
async def generate_title(ctx: dict) -> str:
    """Generate a concise title from the first user message.

    Expected ctx keys:
        * ``first_message``: str (or message-like object) — the first
          user message in a conversation/thread.
        * ``model_factory``: Callable — used to obtain a small model.

    Returns:
        A short (one-line, ideally <= 10 words) title string.
    """
    first_message = ctx.get("first_message", "")
    if hasattr(first_message, "content"):
        first_message = _message_content(first_message)
    first_message = str(first_message or "").strip()
    if not first_message:
        return "New conversation"

    system_prompt = (
        "You generate very short, descriptive conversation titles. "
        "Return ONLY the title, on one line, no quotes, no explanation, "
        "no markdown. Keep it under 10 words. Preserve the original language "
        "of the user's message."
    )
    user_prompt = f"First user message:\n{first_message[:1200]}\n\nTitle:"
    try:
        title = await _call_small_model(
            ctx, system_prompt=system_prompt, user_prompt=user_prompt
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("generate_title: small-model call failed: %s", exc, exc_info=True)
        # Fallback: first ~60 chars of the first message.
        title = first_message.splitlines()[0][:60].strip() or "New conversation"
    # Normalize whitespace and strip wrapping quotes the model might add.
    title = " ".join(title.split()).strip("\"'`")
    return title or "New conversation"


async def compact_context(ctx: dict) -> str:
    """Summarize older messages when the context window is near capacity.

    Expected ctx keys:
        * ``messages``: list — the conversation messages to summarize.
        * ``model_factory``: Callable — used to obtain a small model.
        * ``threshold``: float, optional — used_ratio threshold (e.g. 0.8
          for 80%). Only informational; the caller decides *when* to
          fire, but we include it in the prompt so the model knows the
          budget situation.
        * ``rolling_summary``: str, optional — previous summary to fold in.

    Returns:
        A summary string suitable for storage as ``rolling_summary`` /
        ``context_compaction.summary``.
    """
    messages = ctx.get("messages") or []
    if not messages:
        return ""
    threshold = float(ctx.get("threshold") or 0.8)
    previous = str(ctx.get("rolling_summary") or "").strip()
    rendered = _format_messages_for_prompt(messages, max_chars=8000)
    if not rendered:
        return ""

    system_prompt = (
        "You are a context-compaction agent. Produce a dense, factual "
        "summary of the conversation so far that preserves: (1) the user's "
        "goal, (2) key decisions and outcomes, (3) open questions or next "
        "steps, (4) any artifacts/files/code references the assistant "
        "produced or inspected. Omit pleasantries. Be specific: include "
        "file paths, names, identifiers when they appear. Do NOT invent "
        "facts not in the conversation."
    )
    prior = (
        f"Existing summary to preserve and extend:\n{previous[:1200]}\n\n"
        if previous
        else ""
    )
    user_prompt = (
        f"{prior}Conversation (context usage at ~{int(threshold * 100)}% of budget):\n"
        f"{rendered}\n\n"
        "Compressed summary:"
    )
    try:
        summary = await _call_small_model(
            ctx, system_prompt=system_prompt, user_prompt=user_prompt
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("compact_context: small-model call failed: %s", exc, exc_info=True)
        # Fallback: a short note that compaction failed; callers should
        # retain previous rolling summary in that case.
        summary = previous or ""
    return summary.strip()


async def summarize_turn(ctx: dict) -> str:
    """Produce a brief summary of what was accomplished this turn.

    Expected ctx keys:
        * ``turn_messages``: list — the messages exchanged in this turn
          (typically one user message + one assistant response, but may
          include tool-call pairs).
        * ``model_factory``: Callable.

    Returns:
        A 1-3 sentence summary string.
    """
    turn_messages = ctx.get("turn_messages") or []
    if not turn_messages:
        return ""
    rendered = _format_messages_for_prompt(turn_messages, max_chars=6000)
    if not rendered:
        return ""

    system_prompt = (
        "Summarize what the assistant accomplished in this single turn. "
        "Focus on concrete outcomes: files read/written, tools invoked, "
        "decisions made, questions answered. 1-3 sentences. Do NOT include "
        "this meta-instruction in the output."
    )
    user_prompt = f"Turn messages:\n{rendered}\n\nTurn summary:"
    try:
        summary = await _call_small_model(
            ctx, system_prompt=system_prompt, user_prompt=user_prompt
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("summarize_turn: small-model call failed: %s", exc, exc_info=True)
        summary = ""
    return summary.strip()


async def extract_memories(ctx: dict) -> list[str]:
    """Identify facts/preferences about the user worth remembering.

    Expected ctx keys:
        * ``turn_messages``: list — this turn's messages.
        * ``model_factory``: Callable.
        * ``existing_memories``: list[str], optional — already-known
          memories, used to avoid duplicates.

    Returns:
        A list of short memory strings (may be empty).
    """
    turn_messages = ctx.get("turn_messages") or []
    if not turn_messages:
        return []
    rendered = _format_messages_for_prompt(turn_messages, max_chars=6000)
    if not rendered:
        return []

    existing = ctx.get("existing_memories") or []
    existing_block = ""
    if existing:
        existing_block = (
            "Already-known memories (do NOT repeat any of these):\n"
            + "\n".join(f"- {str(m).strip()}" for m in existing[:50])
            + "\n\n"
        )

    system_prompt = (
        "You extract durable, high-signal memories about the user from a "
        "conversation turn. A good memory is a fact or preference that "
        "will remain true across future sessions (e.g. 'User prefers "
        "Python over JavaScript', 'User's default editor is neovim', "
        "'The project uses pnpm'). Do NOT extract one-off task details, "
        "secrets, or information that is already in the existing list. "
        "Return ONLY a bullet list of 0-5 short memory strings, each on "
        "its own line starting with '- '. If there is nothing worth "
        "remembering, return an empty response."
    )
    user_prompt = (
        f"{existing_block}Turn messages:\n{rendered}\n\n"
        "New memories to remember:"
    )
    try:
        raw = await _call_small_model(
            ctx, system_prompt=system_prompt, user_prompt=user_prompt
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract_memories: small-model call failed: %s", exc, exc_info=True)
        return []

    memories: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading bullet markers the model might emit.
        if line.startswith(("- ", "* ", "• ")):
            line = line[2:].strip()
        elif line[:2].isdigit() and line[1:3] == ". ":
            line = line[3:].strip()
        if not line:
            continue
        memories.append(line)
    # Deduplicate (case-insensitive) and cap.
    seen: set[str] = set()
    deduped: list[str] = []
    for mem in memories:
        key = mem.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(mem)
        if len(deduped) >= 5:
            break
    return deduped


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
class SystemAgentRunner:
    """Fires system agents as background tasks and tracks their completion."""

    def __init__(self, registry: SystemAgentRegistry) -> None:
        self._registry = registry
        self._tasks: dict[str, asyncio.Task] = {}

    async def trigger(self, trigger_name: str, ctx: dict) -> list[asyncio.Task]:
        """Fire every agent registered for ``trigger_name``.

        Each matching agent is launched as a background task; this method
        returns immediately after scheduling them. Use :meth:`wait_all`
        to await completion (e.g. at turn end before persisting state).

        Args:
            trigger_name: The lifecycle trigger being fired.
            ctx: Arbitrary context dict forwarded to each handler. The
                dict is passed by reference; handlers may mutate it
                (e.g. to write back a generated title), so callers
                should either pass a fresh dict per trigger or be
                comfortable with that.

        Returns:
            The list of ``asyncio.Task`` objects scheduled for this
            trigger (already tracked internally).
        """
        agents = self._registry.list_by_trigger(trigger_name)
        tasks: list[asyncio.Task] = []
        for agent in agents:
            task_key = f"{trigger_name}:{agent.name}:{id(ctx)}"
            # Cancel any prior in-flight task for the same logical slot
            # so retries don't pile up.
            prior = self._tasks.get(task_key)
            if prior is not None and not prior.done():
                prior.cancel()
            task = asyncio.create_task(
                self.run_agent(agent, ctx),
                name=f"system-agent:{agent.name}",
            )
            self._tasks[task_key] = task
            tasks.append(task)
        if tasks:
            logger.debug(
                "system_agent: fired %d agent(s) for trigger '%s'",
                len(tasks),
                trigger_name,
            )
        return tasks

    async def run_agent(self, agent: SystemAgent, ctx: dict) -> Any:
        """Run a single system agent, catching and logging all errors.

        Errors from system agents must never crash the host turn; this
        method returns ``None`` on failure so background task results
        remain well-defined.
        """
        logger.debug("system_agent: running '%s' (trigger=%s)", agent.name, agent.trigger)
        try:
            result = await agent.handler(ctx)
            # Handlers may write results back into ctx under a key named
            # after the agent, if they wish to communicate with the caller.
            ctx.setdefault("results", {})[agent.name] = result
            return result
        except asyncio.CancelledError:
            logger.debug("system_agent: '%s' cancelled", agent.name)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "system_agent: '%s' failed: %s",
                agent.name,
                exc,
                exc_info=True,
            )
            ctx.setdefault("errors", {})[agent.name] = str(exc)
            return None

    async def wait_all(self) -> None:
        """Wait for all currently-running background tasks to finish.

        Errors in individual tasks have already been logged by
        :meth:`run_agent`; this method does not raise.
        """
        if not self._tasks:
            return
        pending = [task for task in self._tasks.values() if not task.done()]
        if not pending:
            return
        logger.debug("system_agent: waiting on %d in-flight task(s)", len(pending))
        results = await asyncio.gather(*pending, return_exceptions=True)
        for task, result in zip(pending, results):
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.warning(
                    "system_agent: background task %r raised: %s",
                    task.get_name(),
                    result,
                    exc_info=result,
                )
        # Drop references to finished tasks so they can be GC'd.
        self._tasks = {
            key: task for key, task in self._tasks.items() if not task.done()
        }


# ---------------------------------------------------------------------------
# Default registry factory
# ---------------------------------------------------------------------------
def create_default_system_agent_registry() -> SystemAgentRegistry:
    """Return a :class:`SystemAgentRegistry` pre-loaded with the built-in agents.

    Built-in agents registered:
        * ``title``        — fires on ``first_user_message``, generates a
                             concise conversation title.
        * ``compaction``   — fires on ``context_overflow``, summarizes
                             older messages to free context window.
        * ``turn_summary`` — fires on ``turn_end``, produces a short
                             summary of what was accomplished.
        * ``memory``       — fires on ``turn_end``, extracts durable
                             user facts/preferences.
    """
    registry = SystemAgentRegistry()
    registry.register(
        SystemAgent(
            name="title",
            description="Generate a short title for a new conversation from the first user message.",
            trigger=TRIGGER_FIRST_USER_MESSAGE,
            model=SMALL_MODEL,
            handler=generate_title,
            hidden=True,
        )
    )
    registry.register(
        SystemAgent(
            name="compaction",
            description="Summarize older messages when the context window nears capacity.",
            trigger=TRIGGER_CONTEXT_OVERFLOW,
            model=SMALL_MODEL,
            handler=compact_context,
            hidden=True,
        )
    )
    registry.register(
        SystemAgent(
            name="turn_summary",
            description="Summarize concrete outcomes of a single assistant turn.",
            trigger=TRIGGER_TURN_END,
            model=SMALL_MODEL,
            handler=summarize_turn,
            hidden=True,
        )
    )
    registry.register(
        SystemAgent(
            name="memory",
            description="Extract durable facts and preferences from a turn for long-term memory.",
            trigger=TRIGGER_TURN_END,
            model=SMALL_MODEL,
            handler=extract_memories,
            hidden=True,
        )
    )
    return registry


__all__ = [
    "SMALL_MODEL",
    "FALLBACK_SMALL_MODEL_ID",
    "TRIGGER_FIRST_USER_MESSAGE",
    "TRIGGER_CONTEXT_OVERFLOW",
    "TRIGGER_TURN_END",
    "TRIGGER_MANUAL",
    "SystemAgent",
    "SystemAgentRegistry",
    "SystemAgentRunner",
    "generate_title",
    "compact_context",
    "summarize_turn",
    "extract_memories",
    "create_default_system_agent_registry",
]
