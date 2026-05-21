from __future__ import annotations

import re
from typing import Any

_CONFIRM_MARKERS = {
    "直接切过去",
    "切过去",
    "确认",
    "可以",
    "好的",
    "是的",
    "yes",
    "y",
    "confirm",
    "go ahead",
}
_DISMISS_MARKERS = {
    "取消",
    "算了",
    "不用",
    "先不",
    "不要切",
    "别切",
    "dismiss",
    "cancel",
    "no",
}
_REQUEST_ACTION_MARKERS = (
    "切换",
    "切到",
    "新建",
    "创建",
    "开一个",
    "另开",
    "打开",
    "返回",
    "switch",
    "create",
    "open",
)
_REQUEST_BRANCH_MARKERS = ("分支", "branch", "同级", "平级", "子分支", "下级", "父分支", "parent")
_COPIED_BRANCH_CONTROL_AI_PREFIXES = (
    "已创建并切换到新分支：",
    "已创建并切换到新分支:",
    "Created and switched to the new branch:",
    "我已准备好分支切换确认项：",
    "I prepared a branch switch confirmation:",
    "已取消这次分支切换请求。",
    "Canceled this branch switch request.",
)


def _compact(message: str) -> str:
    return re.sub(r"\s+", "", str(message or "").strip().lower())


def _message_type_name(message: Any) -> str:
    if isinstance(message, dict):
        raw_type = message.get("type") or message.get("role") or message.get("_type") or ""
        message_type = str(raw_type or "").strip().lower()
        return {
            "assistant": "ai",
            "user": "human",
        }.get(message_type, message_type)
    return (
        str(
            getattr(message, "type", message.__class__.__name__.replace("Message", "").lower())
            or ""
        )
        .strip()
        .lower()
    )


def _is_ai_message_type(message_type: Any) -> bool:
    return str(message_type or "").strip().lower() in {"ai", "assistant"}


def _is_human_message_type(message_type: Any) -> bool:
    return str(message_type or "").strip().lower() in {"human", "user"}


def _is_tool_message_type(message_type: Any) -> bool:
    return str(message_type or "").strip().lower() == "tool"


def _message_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "")


def _message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, dict):
        for key in ("text", "content"):
            if key in content:
                return _message_content_to_text(content.get(key))
        return str(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return " ".join(parts).strip()
    return str(content)


def _is_branch_action_confirmation(message: str) -> bool:
    normalized = _compact(message)
    if not normalized:
        return False
    return normalized in _CONFIRM_MARKERS or any(
        marker in normalized for marker in ("直接切", "确认切", "goahead")
    )


def _is_branch_action_dismissal(message: str) -> bool:
    normalized = _compact(message)
    return bool(normalized) and (
        normalized in _DISMISS_MARKERS or any(marker in normalized for marker in _DISMISS_MARKERS)
    )


def _is_branch_action_request(message: str) -> bool:
    normalized = _compact(message)
    if not normalized:
        return False
    if _is_branch_action_confirmation(normalized) or _is_branch_action_dismissal(normalized):
        return False
    has_branch_marker = any(marker in normalized for marker in _REQUEST_BRANCH_MARKERS)
    has_action_marker = any(marker in normalized for marker in _REQUEST_ACTION_MARKERS)
    return has_branch_marker and has_action_marker


def _normalized_human_message_text(message: Any) -> str:
    if not _is_human_message_type(_message_type_name(message)):
        return ""
    return " ".join(_message_content_to_text(_message_content(message)).split())


def _is_copied_branch_control_ai_message(message: Any) -> bool:
    if not _is_ai_message_type(_message_type_name(message)):
        return False
    text = " ".join(_message_content_to_text(_message_content(message)).split())
    return any(text.startswith(prefix) for prefix in _COPIED_BRANCH_CONTROL_AI_PREFIXES)


def _is_copied_branch_control_human_message(message: Any) -> bool:
    if not _is_human_message_type(_message_type_name(message)):
        return False
    text = _message_content_to_text(_message_content(message))
    return (
        _is_branch_action_request(text)
        or _is_branch_action_confirmation(text)
        or _is_branch_action_dismissal(text)
    )


def _branch_action_handoff_texts(values: dict[str, Any]) -> set[str]:
    texts: set[str] = set()
    for item in list(values.get("branch_actions") or []):
        if isinstance(item, dict):
            raw_text = item.get("handoff_message")
        else:
            raw_text = getattr(item, "handoff_message", None)
        text = " ".join(str(raw_text or "").split())
        if text:
            texts.add(text)
    return texts


def _branch_action_kind(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("kind") or "").strip()
    return str(getattr(item, "kind", "") or "").strip()


def _has_sibling_branch_handoff(values: dict[str, Any]) -> bool:
    for item in list(values.get("branch_actions") or []):
        if _branch_action_kind(item) != "fork_sibling_branch":
            continue
        if isinstance(item, dict):
            raw_text = item.get("handoff_message")
        else:
            raw_text = getattr(item, "handoff_message", None)
        if str(raw_text or "").strip():
            return True
    return False


def branch_fork_message_count(values: dict[str, Any]) -> int | None:
    branch_meta = values.get("branch_meta")
    if not isinstance(branch_meta, dict):
        return None
    try:
        fork_message_count = int(branch_meta.get("branch_fork_message_count"))
    except (TypeError, ValueError):
        return None
    if fork_message_count <= 0:
        return None
    return fork_message_count


def _local_human_texts(messages: list[Any], *, copied_count: int) -> set[str]:
    return {
        text
        for message in messages[copied_count:]
        if (text := _normalized_human_message_text(message))
    }


def _is_copied_branch_recommendation_handoff(
    messages: list[Any],
    *,
    index: int,
    copied_count: int,
    local_human_texts: set[str],
) -> bool:
    if index >= copied_count:
        return False
    text = _normalized_human_message_text(messages[index])
    if not text or text not in local_human_texts:
        return False
    if index + 1 >= copied_count:
        return True
    return _is_copied_branch_control_ai_message(messages[index + 1])


def _is_local_duplicate_handoff_before_response(
    messages: list[Any],
    *,
    index: int,
    copied_count: int,
) -> bool:
    if index < copied_count:
        return False
    text = _normalized_human_message_text(messages[index])
    if not text:
        return False
    for later in messages[index + 1 :]:
        later_type = _message_type_name(later)
        if _is_human_message_type(later_type):
            return _normalized_human_message_text(later) == text
        if _is_ai_message_type(later_type) or _is_tool_message_type(later_type):
            return False
    return False


def branch_visible_messages(messages: list[Any], *, values: dict[str, Any]) -> list[Any]:
    fork_message_count = branch_fork_message_count(values)
    if fork_message_count is None:
        return messages
    copied_count = fork_message_count if fork_message_count <= len(messages) else 0
    local_human_texts = _local_human_texts(messages, copied_count=copied_count)
    visible_messages: list[Any] = []
    for index, message in enumerate(messages):
        if _is_copied_branch_control_ai_message(message):
            continue
        if index < copied_count and _is_copied_branch_control_human_message(message):
            continue
        if _is_copied_branch_recommendation_handoff(
            messages,
            index=index,
            copied_count=copied_count,
            local_human_texts=local_human_texts,
        ):
            continue
        if _is_local_duplicate_handoff_before_response(
            messages,
            index=index,
            copied_count=copied_count,
        ):
            continue
        visible_messages.append(message)
    return visible_messages


def branch_seed_messages(messages: list[Any], *, values: dict[str, Any]) -> list[Any]:
    if _has_sibling_branch_handoff(values):
        return []
    handoff_texts = _branch_action_handoff_texts(values)
    seed_messages: list[Any] = []
    for message in messages:
        if _is_copied_branch_control_ai_message(message):
            continue
        if _is_copied_branch_control_human_message(message):
            continue
        text = _normalized_human_message_text(message)
        if text and text in handoff_texts:
            continue
        seed_messages.append(message)
    return seed_messages
