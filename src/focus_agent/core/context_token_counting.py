from __future__ import annotations

from functools import lru_cache
import importlib
import json
from typing import Any

from langchain.messages import AnyMessage

from .types import ContextBudget


def approximate_token_count(
    value: Any,
    *,
    chars_per_token: int = 4,
    tokenizer_id: str | None = None,
) -> int:
    text = _text_for_budget(value)
    if not text:
        return 0
    return _estimate_text_tokens(
        text,
        chars_per_token=chars_per_token,
        tokenizer_id=tokenizer_id,
        tokenizer_first=bool(tokenizer_id),
    )


def _message_budget_units(message: AnyMessage, *, budget: ContextBudget) -> int:
    return _estimate_text_tokens(
        _text_for_budget(message),
        chars_per_token=budget.chars_per_token,
        tokenizer_id=budget.tokenizer_id,
        tokenizer_first=budget.token_budget_mode == "tokenizer_first",
    )


def _estimate_text_tokens(
    text: str,
    *,
    chars_per_token: int,
    tokenizer_id: str | None,
    tokenizer_first: bool,
) -> int:
    if not text:
        return 0
    if tokenizer_first:
        estimated = _estimate_with_tokenizer(text, tokenizer_id=tokenizer_id)
        if estimated is not None:
            return estimated
    divisor = max(chars_per_token, 1)
    return max(1, (len(text) + divisor - 1) // divisor)


@lru_cache(maxsize=4)
def _resolve_tokenizer(tokenizer_id: str | None):
    try:
        tiktoken = importlib.import_module("tiktoken")
    except Exception:  # noqa: BLE001
        return None

    normalized = str(tokenizer_id or "").strip()
    try:
        if normalized:
            return tiktoken.encoding_for_model(normalized)
    except Exception:  # noqa: BLE001
        pass

    for fallback in ("cl100k_base", "o200k_base"):
        try:
            return tiktoken.get_encoding(fallback)
        except Exception:  # noqa: BLE001
            continue
    return None


def _estimate_with_tokenizer(text: str, *, tokenizer_id: str | None) -> int | None:
    tokenizer = _resolve_tokenizer(tokenizer_id)
    if tokenizer is None:
        return None
    try:
        return max(1, len(tokenizer.encode(text)))
    except Exception:  # noqa: BLE001
        return None


def _text_for_budget(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, default=str)
    content = getattr(value, "content", value)
    text = (
        json.dumps(content, ensure_ascii=False, default=str)
        if isinstance(content, list)
        else str(content or "")
    )
    tool_calls = getattr(value, "tool_calls", None)
    if tool_calls:
        text += "\n" + json.dumps(tool_calls, ensure_ascii=False, default=str)
    return text
