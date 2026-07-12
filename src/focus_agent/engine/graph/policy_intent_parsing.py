from __future__ import annotations

import re
from typing import Any

from .policy_markers import _contains_any, _skill_install_hits

_HTTP_URL_RE = re.compile(r"https?://[^\s<>()\"'，。！？、]+", re.IGNORECASE)
_SKILL_ID_RE = r"[A-Za-z0-9][A-Za-z0-9_.:/-]*"


def _preferred_first_args(tool_name: str | None, text: str) -> dict[str, Any]:
    if tool_name == "web_search":
        return {"query": text}
    if tool_name == "web_fetch":
        url = _first_http_url(text)
        return {"url": url} if url else {}
    if tool_name == "search_code":
        return {"query": _workspace_search_query(text)}
    if tool_name == "skills_search":
        if _skill_install_hits(text):
            skill_name = _skill_install_name_from_text(text)
            args: dict[str, Any] = {"query": skill_name or text, "scope": "all"}
            return args
        return {"query": text}
    if tool_name == "skill_view":
        skill_name = _skill_view_name_from_text(text)
        return {"name": skill_name} if skill_name else {}
    if tool_name == "skill_install":
        skill_name = _skill_install_name_from_text(text)
        return {"skill_id": skill_name} if skill_name else {}
    return {}


def _skill_view_name_from_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return ""
    patterns = (
        rf"(?i)(?<![a-z0-9_])skill_view(?![a-z0-9_])\s*"
        rf"(?:查看|打开|读取|加载|view|inspect|open|read|name|名称|for|of|:|：)?\s*"
        rf"`?(?P<name>{_SKILL_ID_RE})`?",
        rf"(?:查看|打开|读取|加载)\s+`?(?P<name>{_SKILL_ID_RE})`?\s*(?:这个)?(?:skill|技能)",
    )
    ignored = {
        "查看",
        "打开",
        "读取",
        "加载",
        "view",
        "inspect",
        "open",
        "read",
        "name",
        "for",
        "of",
    }
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        name = str(match.group("name") or "").strip("`.,!?;:，。！？；：")
        if name and name.lower() not in ignored:
            return name
    return ""


def _skill_install_name_from_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return ""
    patterns = (
        rf"(?i)(?<![a-z0-9_])skill_install(?![a-z0-9_])\s*"
        rf"(?:安装|install|add|name|名称|for|of|:|：)?\s*"
        rf"`?(?P<name>{_SKILL_ID_RE})`?",
        rf"`?(?P<name>{_SKILL_ID_RE})`?\s*(?:，|,|:|：)?\s*"
        rf"(?:想办法|帮我|请)?\s*(?:安装|装一下|添加|加入|install|add)\s*"
        rf"(?:这个|this)?\s*(?:skill|skills|技能)?",
        rf"(?:安装|装一下|添加|加入|install|add)\s+"
        rf"`?(?P<name>{_SKILL_ID_RE})`?\s*(?:这个|this)?\s*(?:skill|skills|技能)?",
    )
    ignored = {
        "安装",
        "装一下",
        "添加",
        "加入",
        "install",
        "add",
        "skill",
        "skills",
        "技能",
        "这个",
        "this",
        "name",
        "for",
        "of",
    }
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        name = str(match.group("name") or "").strip("`.,!?;:，。！？；：")
        if name and name.lower() not in ignored:
            return name
    return ""


def _should_prefer_web_fetch(text: str) -> bool:
    if not _first_http_url(text):
        return False
    return _contains_any(
        text,
        (
            "fetch",
            "open",
            "read",
            "打开",
            "读取",
            "抓取",
            "获取",
            "看一下",
            "查看",
            "网页",
            "页面",
            "标题",
            "summary",
            "summarize",
        ),
    )


def _first_http_url(text: str) -> str:
    match = _HTTP_URL_RE.search(str(text or ""))
    if not match:
        return ""
    return match.group(0).rstrip(".,!?;:，。！？；：")


def _workspace_search_query(text: str) -> str:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?", text)
    seen: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in {"repo", "repository", "codebase", "source", "file", "function", "class"}:
            continue
        if token not in seen:
            seen.append(token)
    if seen:
        return " ".join(seen[:6])
    return text.strip()
