from __future__ import annotations

import math
import re

from .models import SkillDefinition

_SEMANTIC_CANDIDATE_LIMIT = 3
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "before",
    "but",
    "by",
    "for",
    "from",
    "has",
    "in",
    "into",
    "is",
    "it",
    "needs",
    "of",
    "on",
    "or",
    "should",
    "skill",
    "skills",
    "that",
    "the",
    "this",
    "to",
    "tool",
    "tools",
    "use",
    "user",
    "wants",
    "when",
    "with",
    "work",
    "you",
}

_QUERY_ALIAS_MARKERS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("发布前", "发布", "发版", "上线", "里程碑"), ("release", "readiness", "checklist")),
    (("构建失败", "构建", "编译"), ("build", "failure", "fix")),
    (("修复", "报错", "失败"), ("fix", "failure")),
    (("测试", "单测", "回归"), ("test", "tdd", "regression")),
    (("评审", "审查", "复查"), ("review",)),
    (("安全", "权限", "漏洞"), ("security", "review")),
    (("文档", "说明", "readme"), ("documentation", "docs")),
    (("计划", "方案", "拆解"), ("plan", "planning")),
    (("调研", "研究", "资料"), ("research",)),
    (("提交", "合并", "拉取请求"), ("git", "pr", "workflow")),
)


def _semantic_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _TOKEN_RE.findall(value.lower().replace("_", " "))
        if len(token) > 1 and token not in _STOPWORDS
    )


def _body_headings(body: str) -> tuple[str, ...]:
    return tuple(
        match.group(1).strip().strip("#").strip()
        for match in _HEADING_RE.finditer(body)
        if match.group(1).strip()
    )


def _add_weighted_tokens(vector: dict[str, float], value: str, weight: float) -> None:
    for token in _tokens(value):
        vector[token] = vector.get(token, 0.0) + weight
    lowered = value.lower()
    for markers, aliases in _QUERY_ALIAS_MARKERS:
        if not any(marker in lowered for marker in markers):
            continue
        for alias in aliases:
            if alias not in _STOPWORDS:
                vector[alias] = vector.get(alias, 0.0) + weight


def _skill_semantic_vector(skill: SkillDefinition) -> dict[str, float]:
    vector: dict[str, float] = {}
    _add_weighted_tokens(vector, skill.description, 3.0)
    for item in skill.when_to_use:
        _add_weighted_tokens(vector, item, 4.0)
    for item in skill.recommended_tools:
        _add_weighted_tokens(vector, item, 1.5)
    for heading in _body_headings(skill.body):
        _add_weighted_tokens(vector, heading, 2.0)
    return vector


def _cosine_score(query: dict[str, float], document: dict[str, float]) -> float:
    if not query or not document:
        return 0.0
    dot = sum(weight * document.get(token, 0.0) for token, weight in query.items())
    if dot <= 0:
        return 0.0
    query_norm = math.sqrt(sum(weight * weight for weight in query.values()))
    document_norm = math.sqrt(sum(weight * weight for weight in document.values()))
    if query_norm <= 0 or document_norm <= 0:
        return 0.0
    return dot / (query_norm * document_norm)


def _selection_source(
    *,
    explicit_matched: bool,
    prefix_matched: bool,
    semantic_matched: bool,
) -> str:
    sources = [
        source
        for source, matched in (
            ("explicit", explicit_matched),
            ("prefix", prefix_matched),
            ("semantic", semantic_matched),
        )
        if matched
    ]
    if not sources:
        return "none"
    if len(sources) == 1:
        return sources[0]
    return "mixed"


__all__ = [
    "_SEMANTIC_CANDIDATE_LIMIT",
    "_add_weighted_tokens",
    "_body_headings",
    "_cosine_score",
    "_selection_source",
    "_semantic_enabled",
    "_skill_semantic_vector",
    "_tokens",
]
