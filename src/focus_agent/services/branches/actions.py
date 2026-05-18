from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langchain.messages import HumanMessage, SystemMessage

from ...core.branching import (
    BranchActionKind,
    BranchActionNavigation,
    BranchActionProposal,
    BranchActionStatus,
    BranchMeta,
    BranchRole,
)

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
_SIBLING_MARKERS = ("同级", "平级", "sibling")
_CHILD_MARKERS = ("子分支", "下级", "child")
_BRANCH_HANDOFF_PATTERNS = (
    r"^(?:请|帮我|麻烦你)?(?:新建|创建|新开)(?:一个)?(?:同级|平级|子|下级|新的|新)?分支[，,。；;：:\s]*(?P<task>.+)$",
    r"^(?:请|帮我|麻烦你)?(?:开一个|另开)(?:同级|平级|子|下级|新的|新)?分支[，,。；;：:\s]*(?P<task>.+)$",
    r"^(?:请|帮我|麻烦你)?(?:切换|切到)(?:到|一个)?(?:同级|平级|子|下级|新的|新)?分支[，,。；;：:\s]*(?P<task>.+)$",
    r"^(?:create|open|switch(?:\s+to)?)(?:\s+a|\s+an)?(?:\s+new|\s+sibling|\s+child)?\s+branch(?:\s+for|\s+to|\s+and|,|:)?\s*(?P<task>.+)$",
)
_TOPIC_DRIFT_HANDOFF_PATTERNS = (
    r"^(?:换个主题|换个方向|另一个问题|另外一个问题|不相关的问题)[，,。；;：:\s]*(?P<task>.+)$",
    r"^(?:先看|先研究|先探索|单独看|单独研究|单独探索)(?:一下)?(?:另一个|另外一个|新的)?问题[，,。；;：:\s]*(?P<task>.+)$",
)
_HANDOFF_LEADING_FILLER_RE = re.compile(
    r"^(?:然后|并且|来|去|用于|用来|继续|先|单独|帮我|请|麻烦你|and|then|to|for)\s*",
    flags=re.IGNORECASE,
)
_HANDOFF_NESTED_TOPIC_RE = re.compile(
    r"^(?:看|研究|探索)?(?:一下)?(?:另一个|另外一个|新的)?问题[，,。；;：:\s]*(?P<task>.+)$"
)


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_branch_actions(raw: Any) -> list[BranchActionProposal]:
    actions: list[BranchActionProposal] = []
    for item in list(raw or []):
        try:
            actions.append(BranchActionProposal.model_validate(item))
        except Exception:
            continue
    return actions


def serialize_branch_actions(actions: list[BranchActionProposal]) -> list[dict[str, Any]]:
    return [action.model_dump(mode="json") for action in actions]


def latest_pending_branch_action(raw: Any) -> BranchActionProposal | None:
    for action in reversed(normalize_branch_actions(raw)):
        if action.status == BranchActionStatus.PENDING:
            return action
    return None


def is_branch_action_confirmation(message: str) -> bool:
    normalized = _compact(message)
    if not normalized:
        return False
    return normalized in _CONFIRM_MARKERS or any(
        marker in normalized for marker in ("直接切", "确认切", "goahead")
    )


def is_branch_action_dismissal(message: str) -> bool:
    normalized = _compact(message)
    return bool(normalized) and (
        normalized in _DISMISS_MARKERS or any(marker in normalized for marker in _DISMISS_MARKERS)
    )


def is_branch_action_request(message: str) -> bool:
    normalized = _compact(message)
    if not normalized:
        return False
    if is_branch_action_confirmation(normalized) or is_branch_action_dismissal(normalized):
        return False
    has_branch_marker = any(marker in normalized for marker in _REQUEST_BRANCH_MARKERS)
    has_action_marker = any(marker in normalized for marker in _REQUEST_ACTION_MARKERS)
    return has_branch_marker and has_action_marker


def requested_branch_action_kind(message: str, branch_meta: BranchMeta | None) -> BranchActionKind:
    normalized = _compact(message)
    if any(marker in normalized for marker in _CHILD_MARKERS):
        return BranchActionKind.FORK_CHILD_BRANCH
    if branch_meta is not None and any(marker in normalized for marker in _SIBLING_MARKERS):
        return BranchActionKind.FORK_SIBLING_BRANCH
    return BranchActionKind.FORK_CHILD_BRANCH


def target_parent_thread_id(
    *,
    source_thread_id: str,
    branch_meta: BranchMeta | None,
    kind: BranchActionKind,
) -> tuple[BranchActionKind, str]:
    if kind == BranchActionKind.FORK_SIBLING_BRANCH:
        if branch_meta is not None and branch_meta.parent_thread_id:
            return kind, branch_meta.parent_thread_id
        return BranchActionKind.FORK_CHILD_BRANCH, source_thread_id
    if (
        kind == BranchActionKind.RETURN_PARENT_BRANCH
        and branch_meta is not None
        and branch_meta.parent_thread_id
    ):
        return kind, branch_meta.parent_thread_id
    return kind, source_thread_id


def branch_handoff_message_from_text(message: str | None) -> str | None:
    text = str(message or "").strip()
    if not text:
        return None
    for pattern in (*_BRANCH_HANDOFF_PATTERNS, *_TOPIC_DRIFT_HANDOFF_PATTERNS):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        task = _clean_handoff_message(match.group("task"))
        if task:
            return task
    if _is_branch_action_control_only(text):
        return None
    return _clean_handoff_message(text)


def _clean_handoff_message(value: str | None) -> str | None:
    task = str(value or "").strip(" ：:，,。；;")
    for _ in range(3):
        next_task = _HANDOFF_LEADING_FILLER_RE.sub("", task).strip(" ：:，,。；;")
        nested_topic = _HANDOFF_NESTED_TOPIC_RE.search(next_task)
        if nested_topic:
            next_task = nested_topic.group("task").strip(" ：:，,。；;")
        if next_task == task:
            break
        task = next_task
    if not task or task in {"吧", "呀", "啦", "呢", "一下", "看看", "可以吗", "好吗"}:
        return None
    if is_branch_action_request(task) or _is_branch_action_control_only(task):
        return None
    return task


def _is_branch_action_control_only(message: str) -> bool:
    normalized = _compact(message)
    if not normalized:
        return False
    if normalized in _CONFIRM_MARKERS or normalized in _DISMISS_MARKERS:
        return True
    return any(marker in normalized for marker in ("直接切", "确认切", "goahead", "不要切", "别切"))


def infer_suggested_branch_name(message: str, recent_messages: list[Any]) -> str | None:
    direct = _extract_branch_name(message)
    if direct:
        return direct
    for item in reversed(recent_messages):
        if not isinstance(item, HumanMessage):
            continue
        text = str(getattr(item, "content", "") or "")
        if is_branch_action_request(text) or is_branch_action_confirmation(text):
            continue
        extracted = _extract_topic_name(text)
        if extracted:
            return extracted
    return None


def build_branch_action_proposal(
    *,
    kind: BranchActionKind,
    root_thread_id: str,
    source_thread_id: str,
    target_parent_thread_id: str,
    suggested_branch_name: str | None,
    branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES,
    reason: str,
    handoff_message: str | None = None,
) -> BranchActionProposal:
    return BranchActionProposal(
        action_id=f"branch-action-{uuid4()}",
        kind=kind,
        status=BranchActionStatus.PENDING,
        root_thread_id=root_thread_id,
        source_thread_id=source_thread_id,
        target_parent_thread_id=target_parent_thread_id,
        suggested_branch_name=suggested_branch_name,
        branch_role=branch_role,
        reason=reason,
        handoff_message=branch_handoff_message_from_text(handoff_message),
        created_at=utc_iso(),
    )


def replace_branch_action(
    actions: list[BranchActionProposal],
    updated: BranchActionProposal,
) -> list[BranchActionProposal]:
    return [updated if action.action_id == updated.action_id else action for action in actions]


def mark_branch_action_executed(
    action: BranchActionProposal,
    *,
    navigation: BranchActionNavigation,
) -> BranchActionProposal:
    return action.model_copy(
        update={
            "status": BranchActionStatus.EXECUTED,
            "executed_at": utc_iso(),
            "navigation": navigation,
            "error": None,
        }
    )


def mark_branch_action_dismissed(action: BranchActionProposal) -> BranchActionProposal:
    return action.model_copy(
        update={
            "status": BranchActionStatus.DISMISSED,
            "dismissed_at": utc_iso(),
            "error": None,
        }
    )


def mark_branch_action_failed(action: BranchActionProposal, error: str) -> BranchActionProposal:
    return action.model_copy(
        update={
            "status": BranchActionStatus.FAILED,
            "failed_at": utc_iso(),
            "error": error,
        }
    )


def branch_action_audit_event(
    *,
    user_id: str,
    thread_id: str,
    action: BranchActionProposal,
    decision: str,
    reason: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "created_at": utc_iso(),
        "principal": user_id,
        "thread_id": thread_id,
        "action_id": action.action_id,
        "kind": action.kind.value,
        "decision": decision,
        "reason": reason,
        "request_id": request_id,
    }


def proposal_message(action: BranchActionProposal, *, is_chinese: bool) -> str:
    if is_chinese:
        target = "同级新分支" if action.kind == BranchActionKind.FORK_SIBLING_BRANCH else "子分支"
        name = (
            f"「{action.suggested_branch_name}」" if action.suggested_branch_name else "一个新分支"
        )
        return f"我已准备好分支切换确认项：创建{target} {name}。请点击确认，或回复“直接切过去”。"
    target = (
        "sibling branch" if action.kind == BranchActionKind.FORK_SIBLING_BRANCH else "child branch"
    )
    name = f" “{action.suggested_branch_name}”" if action.suggested_branch_name else ""
    return f"I prepared a branch switch confirmation: create a new {target}{name}. Confirm it in the card, or reply “go ahead”."


def execution_message(
    action: BranchActionProposal, *, branch_name: str | None, is_chinese: bool
) -> str:
    name = branch_name or action.suggested_branch_name or action.target_parent_thread_id
    if is_chinese:
        return f"已创建并切换到新分支：{name}。"
    return f"Created and switched to the new branch: {name}."


def dismissal_message(*, is_chinese: bool) -> str:
    return "已取消这次分支切换请求。" if is_chinese else "Canceled this branch switch request."


def _compact(message: str) -> str:
    return re.sub(r"\s+", "", str(message or "").strip().lower())


def _extract_branch_name(message: str) -> str | None:
    text = str(message or "").strip()
    patterns = [
        r"切换到(?P<name>[^，。！？\n]+)",
        r"创建(?:一个)?(?P<name>[^，。！？\n]+?)分支",
        r"新建(?:一个)?(?P<name>[^，。！？\n]+?)分支",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        name = _clean_name(match.group("name"))
        if name:
            return name
    return _extract_topic_name(text)


def _extract_topic_name(text: str) -> str | None:
    compact = str(text or "").strip()
    for pattern in [
        r"(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()]{2,24})(?:下周|本周|走势|分析|深度|怎么样|会是什么)",
        r"(?:关于|研究|分析)(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()]{2,24})",
    ]:
        match = re.search(pattern, compact)
        if match:
            name = _clean_name(match.group("name"))
            if name:
                return name
    return None


def _clean_name(value: str) -> str | None:
    cleaned = str(value or "").strip(" ：:「」『』“”\"'`，。！？ \n\t")
    cleaned = re.sub(r"(同级|子|新的|新|一个|到)$", "", cleaned).strip()
    if not cleaned or cleaned in {"分支", "同级分支", "子分支"}:
        return None
    return cleaned[:80]


logger = logging.getLogger("focus_agent.branches")


class BranchNamingPolicyMixin:
    """Branch name generation and role inference helpers."""

    _DEFAULT_PENDING_BRANCH_NAME = "New Branch"
    _DEFAULT_PENDING_BRANCH_NAME_ZH = "新分支"
    _ROLE_FALLBACK_NAMES = {
        BranchRole.MAIN: "Main",
        BranchRole.EXPLORE_ALTERNATIVES: "Alternative Path",
        BranchRole.DEEP_DIVE: "Deep Dive",
        BranchRole.EXECUTE: "Execution",
        BranchRole.VERIFY: "Verification",
        BranchRole.WRITEUP: "Writeup",
    }
    _ROLE_FALLBACK_NAMES_ZH = {
        BranchRole.MAIN: "主线",
        BranchRole.EXPLORE_ALTERNATIVES: "备选方案",
        BranchRole.DEEP_DIVE: "深入分析",
        BranchRole.EXECUTE: "执行",
        BranchRole.VERIFY: "验证",
        BranchRole.WRITEUP: "整理",
    }
    _ROLE_CLASSIFICATION_OPTIONS = (
        BranchRole.EXPLORE_ALTERNATIVES,
        BranchRole.DEEP_DIVE,
        BranchRole.EXECUTE,
        BranchRole.VERIFY,
        BranchRole.WRITEUP,
    )
    _EXECUTE_SKILL_IDS = {
        "autopilot",
        "code-documentation",
        "eco",
        "ralph",
        "systematic-debugging",
        "tdd",
        "ultrawork",
    }
    _ROLE_KEYWORD_HINTS = {
        BranchRole.WRITEUP: (
            "documentation",
            "document",
            "draft",
            "summary",
            "summarize",
            "writeup",
            "整理",
            "总结",
            "文档",
            "汇总",
            "草稿",
        ),
        BranchRole.EXECUTE: (
            "build",
            "code",
            "fix",
            "implement",
            "integrate",
            "patch",
            "refactor",
            "wire",
            "开发",
            "实现",
            "修复",
            "接入",
            "编码",
            "重构",
        ),
        BranchRole.VERIFY: (
            "check",
            "compare",
            "confirm",
            "reproduce",
            "test",
            "validate",
            "verify",
            "复现",
            "对比",
            "核对",
            "测试",
            "确认",
            "验证",
        ),
        BranchRole.DEEP_DIVE: (
            "analyze",
            "debug",
            "deep dive",
            "inspect",
            "investigate",
            "root cause",
            "trace",
            "分析",
            "定位",
            "排查",
            "根因",
            "深挖",
            "调试",
            "调用链",
        ),
    }
    _BRANCH_NAME_STOPWORDS = {
        "a",
        "an",
        "and",
        "analyze",
        "branch",
        "chat",
        "deep",
        "dive",
        "explore",
        "focus",
        "for",
        "from",
        "help",
        "if",
        "in",
        "into",
        "investigate",
        "main",
        "need",
        "needed",
        "on",
        "only",
        "path",
        "please",
        "recent",
        "review",
        "the",
        "this",
        "thread",
        "topic",
        "user",
        "use",
        "verify",
        "with",
        "draft",
        "writeup",
    }

    @staticmethod
    def _message_content_to_text(content: object) -> str:
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
        if content is None:
            return ""
        return str(content).strip()

    @staticmethod
    def _thread_values_after_branch_fork(thread_values: dict) -> dict:
        branch_meta = thread_values.get("branch_meta")
        if not isinstance(branch_meta, dict):
            return thread_values
        try:
            fork_message_count = int(branch_meta.get("branch_fork_message_count"))
        except (TypeError, ValueError):
            return thread_values
        messages = list(thread_values.get("messages") or [])
        if fork_message_count <= 0:
            return thread_values
        values = dict(thread_values)
        values["messages"] = messages[min(fork_message_count, len(messages)) :]
        return values

    @staticmethod
    def _detect_naming_language(raw_text: str) -> str:
        text = str(raw_text or "").strip()
        if not text:
            return "en"
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        latin_count = len(re.findall(r"[A-Za-z]", text))
        if cjk_count >= max(2, latin_count):
            return "zh"
        return "en"

    @classmethod
    def _fallback_role_name(cls, *, branch_role: BranchRole, language: str) -> str:
        if language == "zh":
            return cls._ROLE_FALLBACK_NAMES_ZH[branch_role]
        return cls._ROLE_FALLBACK_NAMES[branch_role]

    @classmethod
    def _sanitize_branch_name(cls, value: str | None, *, branch_role: BranchRole) -> str:
        text = str(value or "").strip()
        if not text:
            return cls._ROLE_FALLBACK_NAMES[branch_role]
        text = re.sub(r"^[^A-Za-z0-9\u4e00-\u9fff]+", "", text)
        text = re.sub(r"^(branch\s*name|name)\s*:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[`\"“”‘’]+", "", text)
        text = re.sub(r"\s+", " ", text).strip(" -–—.,;:!?")
        if re.search(r"[\u4e00-\u9fff]", text):
            compact = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text))
            return (compact[:12] or cls._ROLE_FALLBACK_NAMES[branch_role]).strip()
        words = text.split()
        if len(words) > 4:
            text = " ".join(words[:4])
        return (text[:36].strip() or cls._ROLE_FALLBACK_NAMES[branch_role]).strip()

    @classmethod
    def _fallback_branch_name(cls, raw_text: str, branch_role: BranchRole, *, language: str) -> str:
        cjk_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", raw_text or "")
        if cjk_chunks:
            return cls._sanitize_branch_name("".join(cjk_chunks), branch_role=branch_role)
        tokens = re.findall(r"[A-Za-z0-9]+", raw_text or "")
        meaningful = [
            token.lower()
            for token in tokens
            if len(token) > 1 and token.lower() not in cls._BRANCH_NAME_STOPWORDS
        ]
        if meaningful:
            label = " ".join(word.capitalize() for word in meaningful[:4])
            return cls._sanitize_branch_name(label, branch_role=branch_role)
        return cls._fallback_role_name(branch_role=branch_role, language=language)

    def _collect_branch_name_seed(
        self, *, thread_values: dict, name_source: str | None = None
    ) -> str:
        thread_values = self._thread_values_after_branch_fork(thread_values)
        parts: list[str] = []
        if name_source and name_source.strip():
            parts.append(name_source.strip())
        summary = str(thread_values.get("rolling_summary") or "").strip()
        if summary:
            parts.append(summary)
        messages = thread_values.get("messages") or []
        for message in reversed(messages):
            content = self._message_content_to_text(getattr(message, "content", ""))
            if content:
                parts.append(content)
            if len(parts) >= 6:
                break
        return "\n".join(parts).strip()

    def _collect_branch_name_context(
        self,
        *,
        thread_values: dict,
        name_source: str | None = None,
        language: str = "en",
    ) -> str:
        thread_values = self._thread_values_after_branch_fork(thread_values)
        sections: list[str] = []
        if name_source and name_source.strip():
            heading = "命名线索" if language == "zh" else "Draft focus"
            sections.append(f"{heading}:\n{name_source.strip()}")
        messages = thread_values.get("messages") or []
        recent_messages: list[str] = []
        for message in reversed(messages):
            message_type = (
                getattr(message, "type", None)
                or message.__class__.__name__.replace("Message", "").lower()
            )
            content = self._message_content_to_text(getattr(message, "content", ""))
            if not content:
                continue
            if language == "zh":
                speaker = (
                    "用户"
                    if message_type == "human"
                    else "助手"
                    if message_type == "ai"
                    else "系统"
                )
            else:
                speaker = (
                    "User"
                    if message_type == "human"
                    else "Assistant"
                    if message_type == "ai"
                    else message_type.title()
                )
            recent_messages.append(f"{speaker}: {content}")
            if len(recent_messages) == 4:
                break
        if recent_messages:
            heading = "最近对话" if language == "zh" else "Recent branch conversation"
            sections.append(f"{heading}:\n" + "\n".join(reversed(recent_messages)))
        summary = str(thread_values.get("rolling_summary") or "").strip()
        if summary:
            heading = "对话摘要" if language == "zh" else "Branch summary"
            sections.append(f"{heading}:\n{summary[:400]}")
        return "\n\n".join(section for section in sections if section.strip())

    @staticmethod
    def _normalize_branch_role_candidate(value: object) -> BranchRole | None:
        text = str(value or "").strip().strip("`\"'").lower()
        if not text:
            return None
        normalized = text.replace("-", "_").replace(" ", "_")
        aliases = {
            "deepdive": "deep_dive",
            "explore": "explore_alternatives",
            "exploration": "explore_alternatives",
            "execution": "execute",
            "implement": "execute",
            "verification": "verify",
            "writing": "writeup",
            "write_up": "writeup",
            "summary": "writeup",
        }
        normalized = aliases.get(normalized, normalized)
        try:
            role = BranchRole(normalized)
        except ValueError:
            return None
        if role == BranchRole.MAIN:
            return None
        return role

    def _collect_branch_role_context(self, *, thread_values: dict) -> str:
        seed_text = self._collect_branch_name_seed(thread_values=thread_values)
        language = self._detect_naming_language(seed_text)
        sections: list[str] = []
        prompt_mode = getattr(
            thread_values.get("prompt_mode"), "value", thread_values.get("prompt_mode")
        )
        if prompt_mode:
            label = "当前模式" if language == "zh" else "Prompt mode"
            sections.append(f"{label}: {prompt_mode}")
        active_skill_ids = [
            str(item).strip()
            for item in thread_values.get("active_skill_ids", [])
            if str(item).strip()
        ]
        if active_skill_ids:
            label = "激活技能" if language == "zh" else "Active skills"
            sections.append(f"{label}: {', '.join(active_skill_ids[:6])}")
        conversation = self._collect_branch_name_context(
            thread_values=thread_values,
            language=language,
        )
        if conversation:
            sections.append(conversation)
        return "\n\n".join(section for section in sections if section.strip())

    def _fallback_branch_role(self, *, thread_values: dict, current_role: BranchRole) -> BranchRole:
        thread_values = self._thread_values_after_branch_fork(thread_values)
        prompt_mode = getattr(
            thread_values.get("prompt_mode"), "value", thread_values.get("prompt_mode")
        )
        normalized_prompt_mode = str(prompt_mode or "").strip().lower()
        if normalized_prompt_mode == "execute":
            return BranchRole.EXECUTE
        if normalized_prompt_mode == "synthesize":
            return BranchRole.WRITEUP

        active_skill_ids = {
            str(item).strip().lower()
            for item in thread_values.get("active_skill_ids", [])
            if str(item).strip()
        }
        if active_skill_ids & self._EXECUTE_SKILL_IDS:
            return BranchRole.EXECUTE

        text_parts = [
            str(thread_values.get("task_brief") or "").strip(),
            str(thread_values.get("rolling_summary") or "").strip(),
        ]
        for message in thread_values.get("messages", [])[-6:]:
            content = self._message_content_to_text(getattr(message, "content", ""))
            if content:
                text_parts.append(content)
        lowered = "\n".join(part for part in text_parts if part).lower()

        for role in (
            BranchRole.WRITEUP,
            BranchRole.EXECUTE,
            BranchRole.VERIFY,
            BranchRole.DEEP_DIVE,
        ):
            if any(keyword in lowered for keyword in self._ROLE_KEYWORD_HINTS[role]):
                return role
        if current_role != BranchRole.MAIN:
            return current_role
        return BranchRole.EXPLORE_ALTERNATIVES

    def _classify_branch_role(self, *, thread_values: dict, current_role: BranchRole) -> BranchRole:
        context = self._collect_branch_role_context(thread_values=thread_values)
        model = getattr(self, "proposal_model", None)
        if model and context:
            try:
                options = ", ".join(role.value for role in self._ROLE_CLASSIFICATION_OPTIONS)
                response = model.invoke(
                    [
                        SystemMessage(
                            content=(
                                "Classify the branch by its dominant work mode after the first completed turn. "
                                f"Return exactly one role id from: {options}. "
                                "Use execute for implementation or direct changes, verify for checking or testing, "
                                "deep_dive for focused investigation, writeup for summarizing or documentation, "
                                "and explore_alternatives for open-ended branching or option discovery."
                            )
                        ),
                        HumanMessage(content=context),
                    ]
                )
                candidate = self._normalize_branch_role_candidate(
                    self._message_content_to_text(getattr(response, "content", response))
                )
                if candidate is not None:
                    return candidate
            except Exception:  # noqa: BLE001 - helper model failures fall back to deterministic role inference
                logger.warning("failed to classify branch role with helper model", exc_info=True)
        return self._fallback_branch_role(thread_values=thread_values, current_role=current_role)

    def _generate_branch_name(
        self,
        *,
        thread_values: dict,
        branch_role: BranchRole,
        name_source: str | None = None,
        language: str | None = None,
    ) -> str:
        seed_text = self._collect_branch_name_seed(
            thread_values=thread_values, name_source=name_source
        )
        language_code = str(language or "").strip().lower()
        language = (
            language_code
            if language_code in {"en", "zh"}
            else self._detect_naming_language(seed_text)
        )
        context = self._collect_branch_name_context(
            thread_values=thread_values,
            name_source=name_source,
            language=language,
        )
        model = getattr(self, "proposal_model", None)
        if model and context:
            try:
                language_label = "Chinese" if language == "zh" else "English"
                response = model.invoke(
                    [
                        SystemMessage(
                            content=(
                                "Generate a concise branch name for a research assistant. "
                                "Return only the name, 2 to 4 words, with no quotes or punctuation unless a hyphen is necessary. "
                                f"Use {language_label} to match the conversation language."
                            )
                        ),
                        HumanMessage(
                            content=(
                                f"Branch role: {branch_role.value.replace('_', ' ')}\n\n{context}"
                            )
                        ),
                    ]
                )
                candidate = self._message_content_to_text(getattr(response, "content", response))
                if candidate:
                    return self._sanitize_branch_name(candidate, branch_role=branch_role)
            except Exception:  # noqa: BLE001 - helper model failures fall back to deterministic naming
                logger.warning("failed to generate branch name with helper model", exc_info=True)
        return self._fallback_branch_name(seed_text or context, branch_role, language=language)

    def _resolve_branch_name(
        self,
        *,
        preferred_name: str | None,
        thread_values: dict,
        branch_role: BranchRole,
    ) -> str:
        if preferred_name and preferred_name.strip():
            return self._sanitize_branch_name(preferred_name, branch_role=branch_role)
        return self._generate_branch_name(
            thread_values=thread_values,
            branch_role=branch_role,
        )

    def _resolve_initial_branch_name(
        self,
        *,
        preferred_name: str | None,
        parent_values: dict,
        name_source: str | None,
        branch_role: BranchRole,
        language: str | None = None,
    ) -> str:
        if preferred_name and preferred_name.strip():
            return self._sanitize_branch_name(preferred_name, branch_role=branch_role)
        del parent_values, name_source, branch_role
        if str(language or "").strip().lower() == "zh":
            return self._DEFAULT_PENDING_BRANCH_NAME_ZH
        return self._DEFAULT_PENDING_BRANCH_NAME

    def _generate_conversation_name(self, *, thread_values: dict) -> str:
        return self._generate_branch_name(thread_values=thread_values, branch_role=BranchRole.MAIN)


__all__ = [
    "utc_iso",
    "normalize_branch_actions",
    "serialize_branch_actions",
    "latest_pending_branch_action",
    "is_branch_action_confirmation",
    "is_branch_action_dismissal",
    "is_branch_action_request",
    "requested_branch_action_kind",
    "target_parent_thread_id",
    "branch_handoff_message_from_text",
    "infer_suggested_branch_name",
    "build_branch_action_proposal",
    "replace_branch_action",
    "mark_branch_action_executed",
    "mark_branch_action_dismissed",
    "mark_branch_action_failed",
    "branch_action_audit_event",
    "proposal_message",
    "execution_message",
    "dismissal_message",
    "BranchNamingPolicyMixin",
]
