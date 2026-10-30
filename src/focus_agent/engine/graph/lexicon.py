"""Shared lexical patterns and term groups for graph intent classification."""

from __future__ import annotations

import re

HTTP_URL_RE = re.compile(r"https?://[^\s<>()\"'，。！？、]+", re.IGNORECASE)
CJK_CHAR_CLASS = "一-鿿"
CJK_RE = re.compile(f"[{CJK_CHAR_CLASS}]")


def contains_cjk(text: object) -> bool:
    """Return True when ``text`` contains at least one CJK unified ideograph."""

    return bool(CJK_RE.search(str(text or "")))


__all__ = ["CJK_CHAR_CLASS", "CJK_RE", "HTTP_URL_RE", "contains_cjk"]
