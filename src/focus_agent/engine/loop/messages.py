"""Message, citation, and prompt assembly helpers for the agent loop node."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage

from ..tools.lexicon import contains_cjk
from ..tools.messages import iter_tool_results

_logger = logging.getLogger(__name__)

_IMPORT_NOTICE_HEADER_PREFIX = "Imported conclusion from branch '"
_IMPORT_DECISIONS_FRAMING_EN = (
    "Decisions I settled while looking into the side question '{branch_name}' (these are final):"
)
_IMPORT_DECISIONS_FRAMING_ZH = "我在旁支问题「{branch_name}」里已经定下的决定（这些是最终结论）："
_IMPORT_ACK_EN = "Noted."
_IMPORT_ACK_ZH = "收到。"


def _latest_tool_result_content(messages: list[Any], tool_name: str) -> str:
    latest = ""
    for message, name, _args in iter_tool_results(messages):
        if name == tool_name:
            latest = _message_content_text(message)
    return latest


def _message_content_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block.strip() if isinstance(block, str) else str(block.get("text") or "").strip()
            for block in content
            if isinstance(block, (str, Mapping))
            and (isinstance(block, str) or block.get("type") in {None, "text", "output_text"})
        ]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, Mapping) and content.get("type") in {None, "text", "output_text"}:
        return str(content.get("text") or "").strip()
    return str(content or "").strip()


def _new_citation_refs(
    citation_refs: list[dict[str, str | None]],
    *,
    existing: list[Any],
) -> list[dict[str, str | None]]:
    seen = {_citation_key(item) for item in existing}
    unique: list[dict[str, str | None]] = []
    for item in citation_refs:
        key = _citation_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _citation_key(item: Any) -> tuple[str, str]:
    if isinstance(item, Mapping):
        return (str(item.get("uri") or ""), str(item.get("label") or ""))
    return (
        str(getattr(item, "uri", "") or ""),
        str(getattr(item, "label", "") or ""),
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


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or block.get("content") or "")
            if isinstance(block, Mapping)
            else str(block)
            for block in content
        ).strip()
    return str(content or "")


def _branch_import_metadata(message: Any) -> Mapping[str, Any] | None:
    """Return the ``focus_agent.metadata.branch_import`` mapping, when present."""
    metadata = getattr(message, "response_metadata", None)
    if not isinstance(metadata, Mapping):
        return None
    focus_agent = metadata.get("focus_agent")
    if not isinstance(focus_agent, Mapping):
        return None
    inner = focus_agent.get("metadata")
    if not isinstance(inner, Mapping):
        return None
    branch_import = inner.get("branch_import")
    return branch_import if isinstance(branch_import, Mapping) else None


def _import_notice_text(message: Any) -> str | None:
    """Return the notice text when ``message`` is a branch import notice."""
    if not isinstance(message, SystemMessage):
        return None
    text = _message_text(message)
    # The chat-side backfill notice carries no metadata, so match its header too.
    if _branch_import_metadata(message) is not None:
        return text
    if text.lstrip().startswith(_IMPORT_NOTICE_HEADER_PREFIX):
        return text
    return None


def _import_notice_branch_name(message: Any, text: str) -> str:
    branch_name = str((_branch_import_metadata(message) or {}).get("branch_name") or "").strip()
    if branch_name:
        return branch_name
    first_line = text.lstrip().splitlines()[0].strip() if text.strip() else ""
    if not first_line.startswith(_IMPORT_NOTICE_HEADER_PREFIX):
        return "unknown branch"
    tail = first_line[len(_IMPORT_NOTICE_HEADER_PREFIX) :].strip()
    if tail.endswith(":"):
        tail = tail[:-1].strip()
    if tail.endswith("'"):
        tail = tail[:-1].strip()
    return tail or "unknown branch"


def _import_notice_body(text: str) -> str:
    """Drop the notice's own header line; the framing replaces it."""
    lines = text.lstrip().splitlines()
    if not lines:
        return ""
    if not lines[0].strip().startswith(_IMPORT_NOTICE_HEADER_PREFIX):
        return "\n".join(lines).strip()
    return "\n".join(lines[1:]).strip()


def _import_notice_as_user_turn(message: Any, text: str) -> list[Any]:
    """Present one imported branch conclusion as a user-confirmed decision turn."""
    branch_name = _import_notice_branch_name(message, text)
    body = _import_notice_body(text)
    if contains_cjk(body):
        framing = _IMPORT_DECISIONS_FRAMING_ZH.format(branch_name=branch_name)
        acknowledgement = _IMPORT_ACK_ZH
    else:
        framing = _IMPORT_DECISIONS_FRAMING_EN.format(branch_name=branch_name)
        acknowledgement = _IMPORT_ACK_EN
    content = f"{framing}\n\n{body}" if body else framing
    return [HumanMessage(content=content), AIMessage(content=acknowledgement)]


def _import_notices_as_user_turns(messages: Sequence[Any]) -> list[Any]:
    """Rewrite branch import notices for the model without touching stored state."""
    rewritten: list[Any] = []
    for message in messages:
        text = _import_notice_text(message)
        if text is None:
            rewritten.append(message)
            continue
        rewritten.extend(_import_notice_as_user_turn(message, text))
    return rewritten


def _build_prompt_messages(
    assembled: str,
    messages: Sequence[Any],
    *,
    steer_block: str,
    policy_note: str,
) -> list[Any]:
    # Imported branch conclusions are restated as a user turn plus a short
    # acknowledgement: the same text presented as a system notice is ignored by
    # the model when it resumes on the main thread.
    prompt_messages = [SystemMessage(content=assembled), *_import_notices_as_user_turns(messages)]
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
    "_apply_agent_definition",
    "_build_prompt_messages",
    "_context_overflow_execution_contract",
    "_context_overflow_response",
    "_import_notices_as_user_turns",
    "_latest_tool_result_content",
    "_message_content_text",
    "_new_citation_refs",
    "_root_thread_id",
    "_steer_block",
]
