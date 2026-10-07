"""Prompt and policy-note assembly helpers for the agent loop node."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from langchain.messages import AIMessage, SystemMessage

from ...core.types import Plan
from ..graph_plan_nodes import _format_plan_block

_logger = logging.getLogger(__name__)

_LIVE_WEB_TOOL_LIMIT_NOTE = (
    "\nResearch has reached its tool limit. No more tools are available. "
    "Now answer the original question using the evidence already collected across ALL "
    "searches and page reads. Do not output tool calls or internal processing notices. "
    "Cite the sources actually supporting your statements. If evidence is incomplete, "
    "give the supported findings and clearly identify the unresolved parts; do not "
    "pretend the research is complete."
)

# Efficiency guidance for multi-part questions: minimize tool calls by
# reusing one tool result to answer multiple sub-questions.
_MULTIPART_TOOL_NOTE = (
    "For multi-part questions (e.g. asking about status, history, and "
    "branches at once), minimize tool calls:\n"
    "- If one tool result can answer multiple sub-questions, use it once.\n"
    "- Prefer the most specific tool (e.g. git_status covers both status and branches).\n"
    "- If you have already called a tool whose output can answer a sub-question, "
    "do not call another tool for that sub-question.\n"
    "- If the user asks a simple question that one tool call can answer, "
    "just call that tool directly -- do not follow the full multi-step workflow."
)

_LIVE_WEB_SEARCH_START_NOTE = (
    "Start the research now with concise, topic-specific search queries. "
    "Rephrase the user's conversational wording into searchable concepts. "
    "Use the verified current date and supported time_range filter for recency. "
    "If results are irrelevant, reformulate the query before giving up."
)


def _apply_agent_definition(
    agent_def: Any,
    agent_name: Any,
    *,
    selected_model: str,
    assembled: str,
) -> tuple[str, str]:
    """Apply AgentDefinition model and system-prompt overrides."""

    agent_system_prompt_extra = ""
    if agent_def is not None:
        try:
            if getattr(agent_def, "model", None):
                selected_model = str(agent_def.model)
            agent_system_prompt_extra = str(getattr(agent_def, "system_prompt", "") or "").strip()
        except Exception:  # noqa: BLE001
            _logger.debug("Failed to apply AgentDefinition '%s'", agent_name, exc_info=True)
            agent_system_prompt_extra = ""

    if agent_system_prompt_extra and agent_system_prompt_extra not in assembled:
        assembled = f"{agent_system_prompt_extra}\n\n{assembled}".strip()
    return selected_model, assembled


def _root_thread_id(runtime: Any) -> Any:
    try:
        ctx = getattr(runtime, "context", None)
        return getattr(ctx, "root_thread_id", None)
    except Exception:  # noqa: BLE001
        return None


def _steer_block(steer_messages: Sequence[Any]) -> str:
    if not steer_messages:
        return ""
    joined = "\n\n".join(m.strip() for m in steer_messages if str(m).strip())
    if not joined:
        return ""
    return f"[User guidance]\n{joined}"


def _compose_policy_note(policy_note: str, *sections: str) -> str:
    for section in sections:
        if section:
            policy_note = f"{policy_note}\n\n{section}".strip()
    if _MULTIPART_TOOL_NOTE not in (policy_note or ""):
        policy_note = (
            f"{policy_note}\n\n{_MULTIPART_TOOL_NOTE}".strip()
            if policy_note
            else _MULTIPART_TOOL_NOTE
        )
    return policy_note


def _build_prompt_messages(
    assembled: str,
    messages: Sequence[Any],
    *,
    plan: Any,
    current_step_id: str,
    steer_block: str,
    policy_note: str,
) -> list[Any]:
    if isinstance(plan, Plan) and plan.steps:
        plan_block = _format_plan_block(plan, current_step_id)
        if plan_block and plan_block not in assembled:
            assembled = f"{assembled}\n\n{plan_block}".strip()
    prompt_messages = [SystemMessage(content=assembled), *messages]
    # Inject drained steer messages as an additional system-style block so
    # they are visible to the LLM but don't replace any user message.
    if steer_block:
        try:
            # Insert steer block right after the first system message so it
            # sits near the top of context and is easy to attend to.
            prompt_messages = [
                prompt_messages[0],
                SystemMessage(content=steer_block),
                *prompt_messages[1:],
            ]
        except Exception:  # noqa: BLE001
            _logger.debug("Failed to inject steer block", exc_info=True)
    if policy_note:
        prompt_messages = [
            prompt_messages[0],
            SystemMessage(content=policy_note),
            *prompt_messages[1:],
        ]
    return prompt_messages


def _context_overflow_response(tool_intent_text: str) -> AIMessage:
    return AIMessage(
        content=(
            "必需的会话上下文已超出可用预算，本次未调用模型。请缩短输入、调整预算或新建会话。"
            if any("一" <= character <= "鿿" for character in tool_intent_text)
            else "The model was not invoked because the required conversation context "
            "exceeds the available prompt budget. Please shorten the request or start "
            "a new thread."
        )
    )


def _context_overflow_execution_contract(execution_contract: dict[str, Any]) -> dict[str, Any]:
    return {
        **execution_contract,
        "status": "blocked",
        "blocked_reason": "Required conversation context exceeds the available prompt budget.",
        "blocked_reason_code": "required_context_overflow",
    }


__all__ = [
    "_LIVE_WEB_SEARCH_START_NOTE",
    "_LIVE_WEB_TOOL_LIMIT_NOTE",
    "_MULTIPART_TOOL_NOTE",
    "_apply_agent_definition",
    "_build_prompt_messages",
    "_compose_policy_note",
    "_context_overflow_execution_contract",
    "_context_overflow_response",
    "_root_thread_id",
    "_steer_block",
]
