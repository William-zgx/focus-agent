from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from langchain.messages import AnyMessage

from .types import ContextBudget

DEFAULT_TOKENIZER_ID = "cl100k_base"


@dataclass(frozen=True, slots=True)
class TokenCountEstimate:
    tokens: int
    counting_backend: str
    tokenizer_id: str | None
    estimated: bool


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


def estimate_message_token_count(
    message: AnyMessage,
    *,
    budget: ContextBudget,
) -> TokenCountEstimate:
    return estimate_text_token_count(
        _text_for_budget(message),
        chars_per_token=budget.chars_per_token,
        tokenizer_id=budget.tokenizer_id,
        tokenizer_first=budget.token_budget_mode == "tokenizer_first",
    )


def estimate_messages_token_count(
    messages: list[AnyMessage],
    *,
    budget: ContextBudget,
) -> TokenCountEstimate:
    estimates = [estimate_message_token_count(message, budget=budget) for message in messages]
    tokens = sum(estimate.tokens for estimate in estimates)
    tokenizer_estimate = next((estimate for estimate in estimates if estimate.tokenizer_id), None)
    estimated = any(estimate.estimated for estimate in estimates)
    counting_backend = (
        "chars_fallback"
        if estimated
        else tokenizer_estimate.counting_backend
        if tokenizer_estimate is not None
        else "chars_fallback"
    )
    return TokenCountEstimate(
        tokens=tokens,
        counting_backend=counting_backend,
        tokenizer_id=tokenizer_estimate.tokenizer_id if tokenizer_estimate is not None else None,
        estimated=estimated,
    )


def _estimate_text_tokens(
    text: str,
    *,
    chars_per_token: int,
    tokenizer_id: str | None,
    tokenizer_first: bool,
) -> int:
    return estimate_text_token_count(
        text,
        chars_per_token=chars_per_token,
        tokenizer_id=tokenizer_id,
        tokenizer_first=tokenizer_first,
    ).tokens


def estimate_text_token_count(
    text: str,
    *,
    chars_per_token: int,
    tokenizer_id: str | None,
    tokenizer_first: bool,
) -> TokenCountEstimate:
    if not text:
        return TokenCountEstimate(
            tokens=0,
            counting_backend="tiktoken" if tokenizer_first else "chars_fallback",
            tokenizer_id=str(tokenizer_id or DEFAULT_TOKENIZER_ID) if tokenizer_first else None,
            estimated=False,
    )
    if tokenizer_first:
        patched_estimate = _estimate_with_tokenizer(text, tokenizer_id=tokenizer_id)
        if patched_estimate is not None:
            return TokenCountEstimate(
                tokens=patched_estimate,
                counting_backend="tiktoken",
                tokenizer_id=str(tokenizer_id or DEFAULT_TOKENIZER_ID),
                estimated=False,
            )
        tokenizer_estimate = _estimate_with_tokenizer_detail(text, tokenizer_id=tokenizer_id)
        if tokenizer_estimate is not None:
            return tokenizer_estimate
    divisor = max(chars_per_token, 1)
    return TokenCountEstimate(
        tokens=max(1, (len(text) + divisor - 1) // divisor),
        counting_backend="chars_fallback",
        tokenizer_id=str(tokenizer_id or DEFAULT_TOKENIZER_ID) if tokenizer_first else None,
        estimated=True,
    )


@lru_cache(maxsize=4)
def _resolve_tokenizer_detail(tokenizer_id: str | None):
    try:
        tiktoken = importlib.import_module("tiktoken")
    except Exception:  # noqa: BLE001
        return None, None

    normalized = str(tokenizer_id or "").strip()
    try:
        if normalized:
            return tiktoken.encoding_for_model(normalized), normalized
    except Exception:  # noqa: BLE001
        pass

    for fallback in (DEFAULT_TOKENIZER_ID, "o200k_base"):
        try:
            return tiktoken.get_encoding(fallback), fallback
        except Exception:  # noqa: BLE001
            continue
    return None, None


def _resolve_tokenizer(tokenizer_id: str | None):
    tokenizer, _resolved_id = _resolve_tokenizer_detail(tokenizer_id)
    return tokenizer


def _estimate_with_tokenizer(text: str, *, tokenizer_id: str | None) -> int | None:
    tokenizer, _resolved_id = _resolve_tokenizer_detail(tokenizer_id)
    if tokenizer is None:
        return None
    try:
        return max(1, len(tokenizer.encode(text)))
    except Exception:  # noqa: BLE001
        return None


def _estimate_with_tokenizer_detail(
    text: str,
    *,
    tokenizer_id: str | None,
) -> TokenCountEstimate | None:
    tokenizer, resolved_id = _resolve_tokenizer_detail(tokenizer_id)
    if tokenizer is None:
        return None
    try:
        return TokenCountEstimate(
            tokens=max(1, len(tokenizer.encode(text))),
            counting_backend="tiktoken",
            tokenizer_id=resolved_id or str(tokenizer_id or DEFAULT_TOKENIZER_ID),
            estimated=False,
        )
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
