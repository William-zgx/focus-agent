from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_URL_RE = re.compile(r"https?://[^\s<>()\"'，。！？、]+", re.IGNORECASE)
_ANCHOR_DATE_RE = re.compile(
    r"(?:当前\s*(?:UTC)?\s*时间|UTC\s*时间|today|current\s*UTC\s*time)"
    r"[^0-9]{0,24}?"
    r"(\d{4}(?:[-/]\d{1,2}[-/]\d{1,2}|年\d{1,2}月\d{1,2}日))",
    re.IGNORECASE,
)
_DATE_WITH_UTC_RE = re.compile(
    r"(\d{4}(?:[-/]\d{1,2}[-/]\d{1,2}|年\d{1,2}月\d{1,2}日))"
    r"(?:[ T]*(?:\d{1,2}:\d{2}(?::\d{2})?)?)?\s*(?:UTC|协调世界时)",
    re.IGNORECASE,
)
_CHINESE_OUTPUT_MARKERS = (
    "中文",
    "用中文",
    "以中文",
    "中文回答",
    "中文回复",
    "chinese",
    "in chinese",
)
_LANGUAGE_REPAIR_SYSTEM_NOTE = (
    "Rewrite the draft into a final Chinese answer. Preserve verified facts, "
    "source names, URLs, dates, numbers, and uncertainty. Do not call tools, "
    "do not add facts, and do not describe this rewrite. Keep every locked "
    "fact verbatim in the rewritten answer."
)


@dataclass(frozen=True, slots=True)
class LanguageRepairResult:
    response: AIMessage
    attempts: int


@dataclass(frozen=True, slots=True)
class TemporalAnchorRepairResult:
    response: AIMessage
    action: str


def _cjk_count(value: str) -> int:
    return len(_CJK_RE.findall(value))


def _ascii_letter_count(value: str) -> int:
    return sum(character.isascii() and character.isalpha() for character in value)


def _requires_chinese_output(user_text: str) -> bool:
    normalized = user_text.lower()
    return bool(_cjk_count(user_text)) or any(
        marker in normalized for marker in _CHINESE_OUTPUT_MARKERS
    )


def _is_english_dominant(value: str) -> bool:
    cjk_count = _cjk_count(value)
    ascii_letters = _ascii_letter_count(value)
    return ascii_letters >= 24 and ascii_letters > cjk_count * 4


def _locked_facts(
    *,
    draft: str,
    observed_at: str,
    source_urls: tuple[str, ...],
) -> tuple[str, ...]:
    values = [observed_at.strip()] if observed_at.strip() else []
    values.extend(match.rstrip(".,!?;:，。！？；：") for match in _URL_RE.findall(draft))
    values.extend(value.strip() for value in source_urls)
    return tuple(dict.fromkeys(value for value in values if value))


def _language_repair_messages(
    *,
    user_text: str,
    draft: str,
    locked_facts: tuple[str, ...],
    correction: bool,
) -> list[Any]:
    locked_block = "\n".join(f"- {value}" for value in locked_facts) or "- none"
    correction_note = (
        "Your previous rewrite omitted or changed a locked fact. Correct it now. "
        if correction
        else ""
    )
    return [
        SystemMessage(content=_LANGUAGE_REPAIR_SYSTEM_NOTE),
        HumanMessage(
            content=(
                f"{correction_note}User request:\n{user_text}\n\n"
                f"Draft:\n{draft}\n\n"
                f"Locked facts that must appear verbatim:\n{locked_block}"
            )
        ),
    ]


def _is_valid_chinese_rewrite(value: str, *, locked_facts: tuple[str, ...]) -> bool:
    return bool(value) and _cjk_count(value) >= 20 and all(fact in value for fact in locked_facts)


def _observed_date(value: str) -> str:
    normalized = value.strip()
    if "T" in normalized:
        return normalized.split("T", 1)[0]
    return normalized[:10]


def _has_conflicting_temporal_anchor(*, answer: str, observed_at: str) -> bool:
    expected = _observed_date(observed_at)
    if not expected:
        return False
    date_matches = [*_ANCHOR_DATE_RE.finditer(answer), *_DATE_WITH_UTC_RE.finditer(answer)]
    for match in date_matches:
        rendered = match.group(1).replace("/", "-")
        if (
            rendered != expected
            and rendered.replace("年", "-").replace("月", "-").replace("日", "") != expected
        ):
            return True
    return False


def _source_lines(source_refs: tuple[tuple[str, str], ...]) -> str:
    if not source_refs:
        return "- none"
    return (
        "\n".join(f"- {label or url}: {url}" for label, url in source_refs[:3] if url) or "- none"
    )


def _temporal_anchor_fallback(
    *,
    user_text: str,
    observed_at: str,
    source_refs: tuple[tuple[str, str], ...],
) -> AIMessage:
    if _requires_chinese_output(user_text):
        return AIMessage(
            content=(
                f"已验证当前 UTC 时间：{observed_at}\n\n"
                "本次实时检索已完成，但返回材料不足以可靠确认与该时间点对应的具体结论。"
                "为避免把历史报道或索引摘要误写成今日事实，我不复述未经当前时间点验证的日期或新闻标题。\n\n"
                "可核验来源：\n"
                f"{_source_lines(source_refs)}\n\n"
                "不确定性：请以来源页面的最新发布时间和官方公告为准。"
            )
        )
    return AIMessage(
        content=(
            f"Verified current UTC time: {observed_at}\n\n"
            "The live search completed, but the returned material is insufficient to confirm a "
            "specific conclusion at that time. To avoid presenting historical reports or index "
            "summaries as current facts, I am not repeating an unverified date or headline.\n\n"
            "Verifiable sources:\n"
            f"{_source_lines(source_refs)}\n\n"
            "Uncertainty: verify the latest publication time and official announcement on the source page."
        )
    )


def enforce_temporal_anchor(
    *,
    response: AIMessage,
    user_text: str,
    observed_at: str,
    source_refs: tuple[tuple[str, str], ...] = (),
) -> TemporalAnchorRepairResult | None:
    """Prevent final answers from omitting or contradicting a verified UTC anchor."""

    answer = str(getattr(response, "content", "") or "").strip()
    if getattr(response, "tool_calls", None) or not answer or not observed_at.strip():
        return None
    if _has_conflicting_temporal_anchor(answer=answer, observed_at=observed_at) or (
        _requires_chinese_output(user_text) and _is_english_dominant(answer)
    ):
        return TemporalAnchorRepairResult(
            response=_temporal_anchor_fallback(
                user_text=user_text,
                observed_at=observed_at,
                source_refs=source_refs,
            ),
            action="answer_with_verified_temporal_anchor",
        )
    if observed_at not in answer:
        prefix = (
            f"已验证当前 UTC 时间：{observed_at}"
            if _requires_chinese_output(user_text)
            else f"Verified current UTC time: {observed_at}"
        )
        return TemporalAnchorRepairResult(
            response=AIMessage(content=f"{prefix}\n\n{answer}"),
            action="prepend_verified_temporal_anchor",
        )
    return None


def repair_chinese_output(
    *,
    response: AIMessage,
    user_text: str,
    model: Any,
    observed_at: str = "",
    source_urls: tuple[str, ...] = (),
) -> LanguageRepairResult | None:
    """Return one safe Chinese rewrite when a Chinese request gets an English-heavy draft."""

    draft = str(getattr(response, "content", "") or "").strip()
    if (
        getattr(response, "tool_calls", None)
        or not draft
        or not _requires_chinese_output(user_text)
        or not _is_english_dominant(draft)
        or not callable(getattr(model, "invoke", None))
    ):
        return None

    locked_facts = _locked_facts(
        draft=draft,
        observed_at=observed_at,
        source_urls=source_urls,
    )
    for correction in (False, True):
        try:
            rewritten = model.invoke(
                _language_repair_messages(
                    user_text=user_text,
                    draft=draft,
                    locked_facts=locked_facts,
                    correction=correction,
                )
            )
        except Exception:  # noqa: BLE001 - preserve an already valid answer on rewrite failure.
            return None
        rewritten_text = str(getattr(rewritten, "content", "") or "").strip()
        if getattr(rewritten, "tool_calls", None):
            continue
        if _is_valid_chinese_rewrite(rewritten_text, locked_facts=locked_facts):
            return LanguageRepairResult(
                response=AIMessage(content=rewritten_text),
                attempts=2 if correction else 1,
            )
    return None


__all__ = [
    "LanguageRepairResult",
    "TemporalAnchorRepairResult",
    "enforce_temporal_anchor",
    "repair_chinese_output",
]
