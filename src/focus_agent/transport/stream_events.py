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
_INTERNAL_TOOL_DELIBERATION_RE = re.compile(
    r"(?ims)(?=.{0,360}(?:web[_\s-]?search|web[_\s-]?fetch|工具|tool|搜索结果))"
    r"(?:"
    r"我(?:因为|之前|刚才).{0,180}(?:搜索结果|重复调用|工具|web[_\s-]?search|web[_\s-]?fetch)|"
    r"我(?:现在|直接|将|会|需要|必须|要).{0,120}(?:执行|调用).{0,120}"
    r"(?:web[_\s-]?search|web[_\s-]?fetch|工具|tool|搜索|抓取|获取)|"
    r"(?:这是不对的|不应该这样|不再重复调用).{0,180}"
    r"(?:执行|调用|工具|web[_\s-]?search|web[_\s-]?fetch)|"
    r"现在我(?:直接)?执行\s*[:：]|"
    r"(?:搜索结果).{0,120}(?:犹豫|重复调用|不满意)"
    r")"
)
_INTERNAL_TOOL_DELIBERATION_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:"
    r"我|我因|我因为|我之|我之前|我刚|我刚才|"
    r"现在我|现在我直|现在我直接|现在我直接执|现在我直接执行|"
    r"这是|这是不|这是不对|这是不对的|"
    r"不再|不再重复|搜索结果|搜|搜索"
    r")$"
)
_INTERNAL_TOOL_REFERENCE_FRAGMENT_RE = re.compile(
    r"(?is)^\s*(?:和|与|及|、|,|，)?\s*web[_\s-]?(?:search|fetch)\s*[。.,，;；]?\s*$"
)
_COMPLETED_TOOL_OBSERVATION_REF_RE = re.compile(
    r"(?is)(?:(?:artifact[_ -]?(?:read|ref)|refs?|reference)\s*[:=]?\s*)?"
    r"tool-observation://[^\s<>\"'`]+"
)
_COMPLETED_TOOL_INVOCATION_RE = re.compile(
    r"(?is)\b(?:artifact_read|web_fetch|web_search|search_code|read_file)\s*\("
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
_CHINESE_PROCESS_OPENINGS = (
    "现在让我",
    "接下来我",
    "我需要",
    "我必须",
    "我打算",
    "我准备",
    "我想要",
    "让我",
    "我来",
    "我先",
    "我再",
    "我会",
    "我将",
)
_CHINESE_PROCESS_MODIFIERS = ("先", "再", "继续", "进一步", "直接", "马上")
_CHINESE_PROCESS_ACTIONS = (
    "尝试",
    "查询",
    "搜索",
    "检索",
    "获取",
    "访问",
    "抓取",
    "浏览",
    "查看",
    "打开",
    "调用",
    "执行",
    "读取",
    "查找",
    "重试",
)
_QUARANTINED_CHINESE_PROCESS_PENDING = "\x00focus-agent:quarantined-chinese-process"


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
        or _INTERNAL_TOOL_DELIBERATION_PREFIX_RE.match(value)
        or _chinese_process_prefix_state(value) != "safe"
    )


def _chinese_process_prefix_state(text: str) -> str:
    value = text.strip()
    if not value:
        return "safe"
    for opening in _CHINESE_PROCESS_OPENINGS:
        if opening.startswith(value):
            return "pending"
        if not value.startswith(opening):
            continue
        remaining = value[len(opening) :]
        if not remaining:
            return "pending"
        for modifier in _CHINESE_PROCESS_MODIFIERS:
            if modifier.startswith(remaining):
                return "pending"
            if remaining.startswith(modifier):
                remaining = remaining[len(modifier) :]
                if not remaining:
                    return "pending"
                break
        for action in _CHINESE_PROCESS_ACTIONS:
            if action.startswith(remaining) or remaining.startswith(action):
                return "quarantine"
    return "safe"


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
    if _INTERNAL_TOOL_DELIBERATION_RE.search(value) or _INTERNAL_TOOL_REFERENCE_FRAGMENT_RE.search(
        value
    ):
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


def sanitize_completed_visible_text(text: Any) -> str:
    """Keep answer prose while removing embedded internal observation refs."""
    value = text if isinstance(text, str) else ""
    safe_text = sanitize_stream_visible_text(value)
    if safe_text:
        return safe_text
    if "tool-observation://" not in value:
        return ""
    cleaned = _COMPLETED_TOOL_OBSERVATION_REF_RE.sub("", value)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n[ \t]*\n[ \t]*", "\n\n", cleaned)
    if not cleaned.strip() or _COMPLETED_TOOL_INVOCATION_RE.search(cleaned):
        return ""
    return sanitize_stream_visible_text(cleaned)


def safe_stream_visible_text_transition(
    current_text: str,
    value: object,
    *,
    pending_text: str = "",
) -> tuple[str, str]:
    delta = value if isinstance(value, str) else ""
    if not delta:
        return current_text, pending_text

    if pending_text == _QUARANTINED_CHINESE_PROCESS_PENDING:
        return current_text, pending_text

    candidate_pending = f"{pending_text}{delta}"
    candidate_visible = f"{current_text}{candidate_pending}"
    chinese_process_state = _chinese_process_prefix_state(candidate_pending)
    if chinese_process_state == "quarantine":
        return current_text, _QUARANTINED_CHINESE_PROCESS_PENDING
    if chinese_process_state == "pending":
        return current_text, candidate_pending

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
