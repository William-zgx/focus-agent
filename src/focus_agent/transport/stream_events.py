from __future__ import annotations

import json
import re
from typing import Any

from ..core.tool_protocol import (
    looks_like_potential_textual_tool_call_prefix,
    looks_like_textual_tool_call_artifact,
    safe_visible_text_transition,
)

VISIBLE_TEXT_BLOCK_TYPES = {
    "text",
    "text_delta",
    "output_text",
    "output_text_delta",
}

INPUT_TEXT_BLOCK_TYPES = {
    "input_text",
    "input_text_delta",
}

REASONING_BLOCK_TYPES = {
    "reasoning",
    "reasoning_delta",
    "reasoning_content",
    "reasoningcontent",
    "thinking",
    "thinking_delta",
}

TOOL_BLOCK_TYPES = {
    "tool_call",
    "tool_call_chunk",
    "server_tool_call",
    "server_tool_call_chunk",
}

STREAM_VISIBILITY_QUARANTINE = "quarantine"
STREAM_VISIBILITY_VISIBLE = "visible"
_STREAM_VISIBILITY_PHASES = {
    STREAM_VISIBILITY_QUARANTINE,
    STREAM_VISIBILITY_VISIBLE,
}
_STREAM_PHASE_METADATA_KEYS = ("stream_phase", "focus_agent_stream_phase")
_STREAM_PHASE_TAG_PREFIXES = ("stream_phase:", "focus_agent_stream_phase:")
_INTERNAL_ENGLISH_PROCESS_NARRATION_RE = re.compile(
    r"(?ims)^\s*(?:"
    r"let\s+me(?:\s+\w+){0,8}\s+"
    r"(?:fetch|search|look|browse|check|inspect|open|query|calculate|use|call|try|"
    r"produce\s+(?:the\s+)?final\s+answer|draft\s+(?:the\s+)?final\s+answer|write\s+(?:the\s+)?final\s+answer)|"
    r"i\s+(?:should|need\s+to|will|can|am\s+going\s+to|must|have\s+to)\s+"
    r"(?:fetch|search|look|browse|check|inspect|open|query|calculate|use|call|try|continue|retry)|"
    r"i\s+must\s+not\s+call\s+more\s+tools|"
    r"wait(?:,|\b).{0,160}(?:tool|fetch|search|look|browse|check|need|should|actually|final)|"
    r"(?:analysis|assistant\s+final|final\s+answer)\s*[:：]\s*(?:$|<|```|tool|function)"
    r")"
)
_INTERNAL_FINAL_ANSWER_BOUNDARY_RE = re.compile(
    r"(?is)\b(?:"
    r"let['’]s\s+go|"
    r"final\s+answer|"
    r"assistant\s+final|"
    r"here(?:'s|\s+is)\s+(?:the\s+)?(?:final\s+)?answer"
    r")\s*[:：.\-]*\s*"
)
_INTERNAL_FINAL_ANSWER_UNSAFE_SUFFIX_RE = re.compile(
    r"(?is)^\s*(?:"
    r"tool\b|"
    r"function\b|"
    r"call\b|"
    r"invoke\b|"
    r"parameter\b|"
    r"tool_?calls?\b|"
    r"<|```"
    r")"
)
_INTERNAL_ENGLISH_PROCESS_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:"
    r"l|le|let|let\s+m|let\s+me|"
    r"i|i\s+(?:s|sh|sho|shou|shoul|should|n|ne|nee|need|need\s+t|need\s+to|"
    r"w|wi|wil|will|c|ca|can|a|am|am\s+g|am\s+go|am\s+going|"
    r"m|mu|mus|must|h|ha|hav|have|have\s+t|have\s+to)|"
    r"w|wa|wai|wait|"
    r"f|fi|fin|fina|final|final\s+a|final\s+an|final\s+answer|"
    r"analysis|assistant\s+f|assistant\s+final"
    r")$"
)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        for key in (
            "text",
            "content",
            "value",
            "chunk",
            "reasoning",
            "reasoning_content",
            "reasoningcontent",
            "summary",
        ):
            if key in value and value[key] is not None:
                return _stringify(value[key])
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _iter_blocks(message_chunk: Any) -> list[Any]:
    for attr in ("content_blocks", "content"):
        value = getattr(message_chunk, attr, None)
        if isinstance(value, list):
            return value
    return []


def _message_type(message_chunk: Any) -> str:
    return str(getattr(message_chunk, "type", "") or "").strip().lower()


def _should_hide_visible_text(message_chunk: Any) -> bool:
    message_type = _message_type(message_chunk)
    if not message_type:
        return False
    return any(token in message_type for token in ("human", "user", "system", "tool"))


def looks_like_stream_visible_text_artifact(text: Any) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return (
        looks_like_textual_tool_call_artifact(value) or sanitize_stream_visible_text(value) != value
    )


def looks_like_potential_stream_visible_text_artifact_prefix(text: Any) -> bool:
    value = str(text or "").strip()
    if not value or len(value) > 512:
        return False
    return looks_like_potential_textual_tool_call_prefix(value) or bool(
        _INTERNAL_ENGLISH_PROCESS_PREFIX_RE.match(value)
    )


def _suffix_after_internal_final_answer_boundary(text: str) -> str:
    last_suffix = ""
    for match in _INTERNAL_FINAL_ANSWER_BOUNDARY_RE.finditer(text):
        suffix = text[match.end() :].lstrip(".… \t\r\n")
        if suffix:
            last_suffix = suffix
    return last_suffix


def sanitize_stream_visible_text(text: Any) -> str:
    value = text if isinstance(text, str) else ""
    if not value.strip():
        return ""
    if looks_like_textual_tool_call_artifact(value):
        return ""
    if not _INTERNAL_ENGLISH_PROCESS_NARRATION_RE.search(value):
        return value

    suffix = _suffix_after_internal_final_answer_boundary(value)
    if not suffix:
        return ""
    if (
        looks_like_textual_tool_call_artifact(suffix)
        or _INTERNAL_FINAL_ANSWER_UNSAFE_SUFFIX_RE.search(suffix)
        or _INTERNAL_ENGLISH_PROCESS_NARRATION_RE.search(suffix)
    ):
        return ""
    return suffix


def safe_stream_visible_text_transition(
    current_text: str,
    value: object,
    *,
    pending_text: str = "",
) -> tuple[str, str]:
    delta = value if isinstance(value, str) else ""
    if not delta:
        return current_text, pending_text

    candidate_pending = f"{pending_text}{delta}"
    candidate_visible = f"{current_text}{candidate_pending}"
    if looks_like_stream_visible_text_artifact(
        candidate_pending
    ) or looks_like_stream_visible_text_artifact(candidate_visible):
        safe_pending = sanitize_stream_visible_text(candidate_pending)
        if safe_pending:
            return current_text + safe_pending, ""
        if not current_text:
            safe_visible = sanitize_stream_visible_text(candidate_visible)
            if safe_visible:
                return safe_visible, ""
        current_looks_internal = looks_like_stream_visible_text_artifact(
            current_text
        ) or looks_like_potential_stream_visible_text_artifact_prefix(current_text)
        return ("" if current_looks_internal else current_text), ""

    if looks_like_potential_stream_visible_text_artifact_prefix(candidate_pending):
        return current_text, candidate_pending

    next_text, next_pending = safe_visible_text_transition(
        current_text,
        delta,
        pending_text=pending_text,
    )
    if next_text and looks_like_stream_visible_text_artifact(next_text):
        return "", ""
    return next_text, next_pending


def _extract_visible_text_delta(message_chunk: Any, *, filter_textual_artifacts: bool) -> str:
    if _should_hide_visible_text(message_chunk):
        return ""

    content = getattr(message_chunk, "content", None)
    if isinstance(content, str):
        if filter_textual_artifacts:
            return sanitize_stream_visible_text(content)
        return content

    parts: list[str] = []
    for block in _iter_blocks(message_chunk):
        if isinstance(block, str):
            text = sanitize_stream_visible_text(block) if filter_textual_artifacts else block
            if text:
                parts.append(text)
            continue
        if not isinstance(block, dict):
            text = _stringify(block)
            if filter_textual_artifacts:
                text = sanitize_stream_visible_text(text)
            if text:
                parts.append(text)
            continue
        block_type = str(block.get("type") or "")
        if block_type in REASONING_BLOCK_TYPES or block_type in TOOL_BLOCK_TYPES:
            continue
        if block_type in INPUT_TEXT_BLOCK_TYPES:
            continue
        if block_type in VISIBLE_TEXT_BLOCK_TYPES or (
            "text" in block and block_type not in TOOL_BLOCK_TYPES
        ):
            text = _stringify(block.get("text") or block.get("content") or block.get("value"))
            if filter_textual_artifacts:
                text = sanitize_stream_visible_text(text)
            if text:
                parts.append(text)
    return "".join(parts)


def extract_visible_text_candidate_delta(message_chunk: Any) -> str:
    return _extract_visible_text_delta(message_chunk, filter_textual_artifacts=False)


def extract_visible_text_delta(message_chunk: Any) -> str:
    return _extract_visible_text_delta(message_chunk, filter_textual_artifacts=True)


def extract_reasoning_delta(message_chunk: Any) -> str:
    parts: list[str] = []
    additional_reasoning = _stringify(
        getattr(message_chunk, "additional_kwargs", {}).get("reasoning_content")
    )
    if additional_reasoning and not looks_like_textual_tool_call_artifact(additional_reasoning):
        parts.append(additional_reasoning)
    for block in _iter_blocks(message_chunk):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type not in REASONING_BLOCK_TYPES:
            continue
        text = _stringify(
            block.get("reasoning")
            or block.get("reasoning_content")
            or block.get("reasoningcontent")
            or block.get("summary")
            or block.get("text")
            or block.get("content")
            or block.get("value")
        )
        if text and not looks_like_textual_tool_call_artifact(text):
            parts.append(text)
    return "".join(parts)


def extract_text_delta(message_chunk: Any) -> str:
    return extract_visible_text_delta(message_chunk)


def _tool_call_chunk_payload(*, raw: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "args_delta": _stringify(raw.get("args") or raw.get("args_text") or raw.get("input")),
        "raw": raw,
    }
    tool_call_id = raw.get("id") or raw.get("tool_call_id") or raw.get("call_id")
    if tool_call_id is not None:
        payload["id"] = str(tool_call_id)
    name = raw.get("name")
    if name is not None:
        payload["name"] = str(name)
    return payload


def _tool_identity_payload(*, tool_call_id: Any = None, name: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if tool_call_id is not None:
        call_id = str(tool_call_id)
        payload["id"] = call_id
        payload["tool_call_id"] = call_id
    if name is not None:
        tool_name = str(name)
        payload["name"] = tool_name
        payload["tool_name"] = tool_name
    return payload


def _normalize_stream_visibility_phase(value: Any) -> str | None:
    phase = str(value or "").strip().lower()
    return phase if phase in _STREAM_VISIBILITY_PHASES else None


def _stream_visibility_phase_from_tag(value: Any) -> str | None:
    tag = str(value or "").strip().lower()
    for prefix in _STREAM_PHASE_TAG_PREFIXES:
        if tag.startswith(prefix):
            return _normalize_stream_visibility_phase(tag[len(prefix) :])
    return None


def _iter_metadata_tags(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def stream_visibility_phase_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    if not isinstance(metadata, dict):
        return STREAM_VISIBILITY_QUARANTINE
    for key in _STREAM_PHASE_METADATA_KEYS:
        phase = _normalize_stream_visibility_phase(metadata.get(key))
        if phase is not None:
            return phase
    for tag in _iter_metadata_tags(metadata.get("tags")):
        phase = _stream_visibility_phase_from_tag(tag)
        if phase is not None:
            return phase
    return STREAM_VISIBILITY_QUARANTINE


def _is_internal_stream_phase_tag(value: Any) -> bool:
    return _stream_visibility_phase_from_tag(value) is not None


def _sanitize_metadata_tags(value: Any) -> Any:
    if isinstance(value, str):
        return None if _is_internal_stream_phase_tag(value) else value
    if not isinstance(value, (list, tuple, set)):
        return value
    tags = [tag for tag in value if not _is_internal_stream_phase_tag(tag)]
    return tags or None


def extract_tool_call_chunks(message_chunk: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for chunk in getattr(message_chunk, "tool_call_chunks", []) or []:
        if not isinstance(chunk, dict):
            continue
        chunks.append(_tool_call_chunk_payload(raw=chunk))
    for call in getattr(message_chunk, "tool_calls", []) or []:
        if not isinstance(call, dict):
            continue
        chunks.append(_tool_call_chunk_payload(raw=call))
    for block in _iter_blocks(message_chunk):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type not in TOOL_BLOCK_TYPES:
            continue
        chunks.append(_tool_call_chunk_payload(raw=block))
    return chunks


def sanitize_stream_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = dict(metadata or {})
    allowed_keys = {
        "langgraph_node",
        "langgraph_path",
        "langgraph_step",
        "tags",
        "run_id",
        "model_name",
        "ls_provider",
    }
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        if key not in allowed_keys or value is None:
            continue
        if key == "tags":
            value = _sanitize_metadata_tags(value)
            if value is None:
                continue
        sanitized[key] = value
    return sanitized


def map_custom_payload_to_event(payload: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(payload, dict):
        if payload.get("event") == "tool":
            stage = str(payload.get("stage") or "delta")
            event_name = {
                "start": "tool.requested",
                "delta": "state.update",
                "progress": "state.update",
                "end": "tool.result",
                "error": "tool.error",
            }.get(stage, "state.update")
            normalized = dict(payload)
            normalized.update(
                _tool_identity_payload(
                    tool_call_id=payload.get("tool_call_id")
                    or payload.get("id")
                    or payload.get("call_id"),
                    name=payload.get("tool_name") or payload.get("name"),
                )
            )
            return event_name, normalized
        if payload.get("event") == "status":
            return "run.status", dict(payload)
        return "state.update", dict(payload)
    return "state.update", {"value": payload}


def extract_tool_requests_from_updates(data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node_name, node_state in (data or {}).items():
        messages = []
        if isinstance(node_state, dict):
            messages = list(node_state.get("messages") or [])
        for message in messages:
            for tool_call in getattr(message, "tool_calls", []) or []:
                results.append(
                    {
                        "node": node_name,
                        "tool_name": tool_call.get("name"),
                        "name": tool_call.get("name"),
                        "tool_call_id": tool_call.get("id"),
                        "id": tool_call.get("id"),
                        "args": tool_call.get("args"),
                    }
                )
    return results


def extract_tool_results_from_updates(data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node_name, node_state in (data or {}).items():
        messages = []
        if isinstance(node_state, dict):
            messages = list(node_state.get("messages") or [])
        for message in messages:
            message_type = getattr(message, "type", "")
            if message_type != "tool":
                continue
            results.append(
                {
                    "node": node_name,
                    "tool_call_id": getattr(message, "tool_call_id", None),
                    "id": getattr(message, "tool_call_id", None),
                    "content": _stringify(getattr(message, "content", "")),
                    "name": getattr(message, "name", None),
                    "tool_name": getattr(message, "name", None),
                }
            )
    return results
