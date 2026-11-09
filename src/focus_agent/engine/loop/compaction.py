"""Model-written context compaction for the v2 ``summarize_turn`` node.

The heuristic update still runs first on every turn; it moves the cursor and is
the fallback.  When post-turn compaction is due and messages have left the
recent window since the last model summary, the helper model rewrites the
summary to absorb them.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from langchain.messages import HumanMessage, SystemMessage

from ...config import Settings
from ...context_usage import build_context_usage
from ...core.context_compaction import (
    HISTORY_SUMMARY_MAX_CHARS,
    _message_text,
    _message_type,
    build_incremental_compaction_update,
)
from ...core.context_compaction_model import (
    PendingModelCompaction,
    model_summary_state,
    pending_model_compaction,
    with_heuristic_summary,
    with_model_summary,
)
from ...core.message_utils import clip_text
from ...core.state import AgentState
from ...core.time_utils import utc_now
from ...transport.stream_events import STREAM_VISIBILITY_QUARANTINE
from ..model_factory import ModelInvocationTimeoutError
from ..tools.lexicon import CJK_RE
from ..tools.textual_repair import _looks_like_textual_tool_call_artifact
from .support import _with_stream_phase

logger = logging.getLogger(__name__)


def _cjk_count(value: str) -> int:
    return len(CJK_RE.findall(value))


def _requires_chinese_output(user_text: str) -> bool:
    # A bare "chinese" would also match topics such as "Chinese New Year".
    return bool(_cjk_count(user_text)) or "in chinese" in user_text.lower()


_MESSAGE_MAX_CHARS = 2_000
_TOOL_ARGS_MAX_CHARS = 400
_TRANSCRIPT_MAX_CHARS = 48_000
_USER_ROLES = frozenset({"human", "user"})
_ROLE_LABELS = {
    "human": "User",
    "user": "User",
    "ai": "Assistant",
    "assistant": "Assistant",
    "tool": "Tool result",
    "system": "System",
}
_SYSTEM_PROMPT = (
    "You maintain the running summary of a long conversation between a user and an AI "
    "assistant. Messages that leave the assistant's recent context are replaced by this "
    "summary, so anything you leave out is lost to the assistant.\n\n"
    "Merge the previous summary and the new messages into one updated summary. Keep:\n"
    "- the user's goals and constraints, including later changes or withdrawals;\n"
    "- decisions made and conclusions reached;\n"
    "- open questions and pending next steps;\n"
    "- key facts and numbers, each with its source URL copied verbatim when one was given;\n"
    "- files, paths, commands and identifiers that were read, written or run.\n"
    "When newer messages contradict the previous summary, keep the newer information. "
    "Do not invent anything; drop greetings, filler and repetition.\n\n"
    "{language_rule} Output plain text only (short headed sections or bullet points), "
    "at most {max_chars} characters. Do not call tools and do not write tool-call markup, "
    "XML or JSON."
)


def make_model_compaction_summarizer(
    *,
    settings: Settings,
    model_for: Callable[[str, str], Any],
    known_tool_names: Iterable[str] = (),
    available_tools: Iterable[Any] = (),
) -> Callable[[AgentState], dict[str, Any]]:
    tool_names = frozenset(known_tool_names)
    tools = tuple(available_tools)

    def compact(
        state: AgentState, previous_meta: dict[str, Any], update: dict[str, Any]
    ) -> dict[str, Any]:
        pending = pending_model_compaction(state, previous_meta)
        if not pending.messages:
            if pending.stored is None:
                return with_heuristic_summary(update)
            return with_model_summary(update, values=state, summary_state=pending.stored)
        model_id = str(settings.helper_model or state.get("selected_model") or settings.model)
        if not _compaction_due(
            state,
            settings=settings,
            selected_model=str(state.get("selected_model") or settings.model),
            available_tools=tools,
        ):
            return with_heuristic_summary(update)
        text, fallback_reason = _write_summary(
            model_for(model_id, ""),
            _summary_prompt(pending, latest_user_text=_latest_human_message_text(state)),
            known_tool_names=tool_names,
        )
        update = {**update, "llm_calls": int(state.get("llm_calls", 0) or 0) + 1}
        if fallback_reason:
            return with_heuristic_summary(update, fallback_reason=fallback_reason)
        return with_model_summary(
            update,
            values=state,
            summary_state=model_summary_state(
                pending, text=text, model_id=model_id, written_at=utc_now().isoformat()
            ),
        )

    def summarize(state: AgentState) -> dict[str, Any]:
        previous = state.get("context_compaction")
        previous_meta = dict(previous) if isinstance(previous, dict) else {}
        update = build_incremental_compaction_update(
            state, previous_meta, trigger="turn_summary", force=False
        )
        if not settings.context_auto_compaction_enabled:
            return with_heuristic_summary(update)
        try:
            return compact(state, previous_meta, update)
        except Exception:  # noqa: BLE001 - compaction must never fail the turn
            logger.warning("model compaction failed; keeping the heuristic summary", exc_info=True)
            return with_heuristic_summary(update, fallback_reason="model_error")

    return summarize


def _compaction_due(
    state: AgentState,
    *,
    settings: Settings,
    selected_model: str,
    available_tools: tuple[Any, ...],
) -> bool:
    """Match the chat service's automatic post-turn compaction trigger."""

    usage = build_context_usage(
        dict(state),
        selected_model=selected_model,
        available_tools=available_tools,
    )
    numerator = usage.pretrim_tokens or usage.used_tokens
    denominator = usage.input_token_limit or usage.token_limit
    if denominator <= 0:
        return usage.required_overflow
    ratio = numerator / denominator
    return ratio >= settings.context_auto_compaction_post_turn_ratio


def _write_summary(
    model: Any, prompt: list[Any], *, known_tool_names: frozenset[str]
) -> tuple[str, str]:
    """Return ``(summary, "")`` or ``("", fallback_reason)``."""

    try:
        response = _with_stream_phase(model, STREAM_VISIBILITY_QUARANTINE).invoke(prompt)
        if getattr(response, "tool_calls", None) or _looks_like_textual_tool_call_artifact(
            response, known_tool_names=known_tool_names
        ):
            return "", "tool_call_markup"
        text = _message_text(response)
        if not text:
            return "", "empty_response"
        return _bounded(text, HISTORY_SUMMARY_MAX_CHARS), ""
    except ModelInvocationTimeoutError:
        logger.warning("compaction summary model call timed out")
        return "", "timeout"
    except Exception:  # noqa: BLE001 - the heuristic summary must remain available
        logger.warning("compaction summary model call failed", exc_info=True)
        return "", "model_error"


def _latest_human_message_text(state: AgentState) -> str:
    for message in reversed(list(state.get("messages") or [])):
        if _message_type(message) in _USER_ROLES:
            return _message_text(message)
    return ""


def _summary_prompt(pending: PendingModelCompaction, *, latest_user_text: str) -> list[Any]:
    language_rule = (
        "Write the summary in Chinese, the language of this conversation."
        if _requires_chinese_output(latest_user_text)
        else "Write the summary in the language the user writes in."
    )
    return [
        SystemMessage(
            content=_SYSTEM_PROMPT.format(
                language_rule=language_rule, max_chars=HISTORY_SUMMARY_MAX_CHARS
            )
        ),
        HumanMessage(
            content=(
                f"Previous summary:\n{pending.previous_summary or '(none yet)'}\n\n"
                "New messages to fold in, oldest first:\n"
                f"{_render_transcript(pending.messages)}"
            )
        ),
    ]


def _render_transcript(messages: Iterable[Any]) -> str:
    lines = [line for message in messages if (line := _render_message(message))]
    if sum(len(line) + 1 for line in lines) <= _TRANSCRIPT_MAX_CHARS:
        return "\n".join(lines)
    head: list[str] = []
    tail: list[str] = []
    half = _TRANSCRIPT_MAX_CHARS // 2
    used = 0
    for line in lines:
        if used + len(line) > half:
            break
        head.append(line)
        used += len(line) + 1
    used = 0
    for line in reversed(lines[len(head) :]):
        if used + len(line) > half:
            break
        tail.insert(0, line)
        used += len(line) + 1
    omitted = len(lines) - len(head) - len(tail)
    return "\n".join([*head, f"[... {omitted} messages omitted ...]", *tail])


def _render_message(message: Any) -> str:
    role = _message_type(message)
    label = _ROLE_LABELS.get(role, role or "Message")
    name = message.get("name") if isinstance(message, Mapping) else getattr(message, "name", None)
    if role == "tool" and name:
        label = f"{label} ({name})"
    lines = []
    text = _message_text(message)
    if text:
        lines.append(f"{label}: {clip_text(text, _MESSAGE_MAX_CHARS)}")
    calls = (
        message.get("tool_calls")
        if isinstance(message, Mapping)
        else getattr(message, "tool_calls", None)
    )
    for call in calls or []:
        args = json.dumps(call.get("args") or {}, ensure_ascii=False, default=str)
        lines.append(f"{label} called {call.get('name')}({clip_text(args, _TOOL_ARGS_MAX_CHARS)})")
    return "\n".join(lines)


def _bounded(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text.rfind("\n", 0, max_chars)
    return text[: cut if cut >= max_chars // 2 else max_chars].rstrip()


__all__ = ["make_model_compaction_summarizer"]
