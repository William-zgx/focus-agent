from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from langchain.messages import HumanMessage

from ..core.branching import (
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
_REQUEST_ACTION_MARKERS = ("切换", "切到", "新建", "创建", "开一个", "另开", "打开", "返回", "switch", "create", "open")
_REQUEST_BRANCH_MARKERS = ("分支", "branch", "同级", "平级", "子分支", "下级", "父分支", "parent")
_SIBLING_MARKERS = ("同级", "平级", "sibling")
_CHILD_MARKERS = ("子分支", "下级", "child")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return normalized in _CONFIRM_MARKERS or any(marker in normalized for marker in ("直接切", "确认切", "goahead"))


def is_branch_action_dismissal(message: str) -> bool:
    normalized = _compact(message)
    return bool(normalized) and (normalized in _DISMISS_MARKERS or any(marker in normalized for marker in _DISMISS_MARKERS))


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
    if branch_meta is not None and branch_meta.parent_thread_id:
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
    if kind == BranchActionKind.RETURN_PARENT_BRANCH and branch_meta is not None and branch_meta.parent_thread_id:
        return kind, branch_meta.parent_thread_id
    return kind, source_thread_id


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
        name = f"「{action.suggested_branch_name}」" if action.suggested_branch_name else "一个新分支"
        return f"我已准备好分支切换确认项：创建{target} {name}。请点击确认，或回复“直接切过去”。"
    target = "sibling branch" if action.kind == BranchActionKind.FORK_SIBLING_BRANCH else "child branch"
    name = f" “{action.suggested_branch_name}”" if action.suggested_branch_name else ""
    return f"I prepared a branch switch confirmation: create a new {target}{name}. Confirm it in the card, or reply “go ahead”."


def execution_message(action: BranchActionProposal, *, branch_name: str | None, is_chinese: bool) -> str:
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
