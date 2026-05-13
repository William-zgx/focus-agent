from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def normalize_token_usage(raw: dict[str, Any] | None = None) -> dict[str, int]:
    payload = dict(raw or {})
    input_tokens = _int_value(
        payload.get("input_tokens"),
        payload.get("prompt_tokens"),
        payload.get("prompt_token_count"),
    )
    output_tokens = _int_value(
        payload.get("output_tokens"),
        payload.get("completion_tokens"),
        payload.get("completion_token_count"),
    )
    total_tokens = _int_value(
        payload.get("total_tokens"),
        payload.get("total_token_count"),
    )
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def accumulate_token_usage(
    current: dict[str, int], delta: dict[str, Any] | None = None
) -> dict[str, int]:
    normalized = normalize_token_usage(delta)
    return {
        "input_tokens": int(current.get("input_tokens") or 0) + normalized["input_tokens"],
        "output_tokens": int(current.get("output_tokens") or 0) + normalized["output_tokens"],
        "total_tokens": int(current.get("total_tokens") or 0) + normalized["total_tokens"],
    }


def message_token_usage(message: Any) -> dict[str, int] | None:
    merged = _merge_usage_candidates(_message_usage_candidates(message))
    if merged is not None:
        return merged
    return None


def messages_token_usage(messages: list[Any]) -> dict[str, int]:
    total = normalize_token_usage()
    for message in messages or []:
        usage = message_token_usage(message)
        if usage is not None:
            total = accumulate_token_usage(total, usage)
    return total


def _message_usage_candidates(message: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for value in (
        getattr(message, "usage_metadata", None),
        getattr(message, "response_metadata", None),
        getattr(message, "additional_kwargs", None),
    ):
        candidates.extend(_usage_payloads(value))
    return candidates


def _usage_payloads(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    payloads: list[dict[str, Any]] = []
    for key in ("token_usage", "usage", "usage_metadata"):
        nested = value.get(key)
        if isinstance(nested, dict):
            payloads.append(dict(nested))
    payloads.append(dict(value))
    return payloads


def _merge_usage_candidates(candidates: list[dict[str, Any]]) -> dict[str, int] | None:
    merged: dict[str, int] = {}
    for candidate in candidates:
        input_tokens = _usage_component(
            candidate,
            ("input_tokens", "prompt_tokens", "prompt_token_count"),
        )
        output_tokens = _usage_component(
            candidate,
            ("output_tokens", "completion_tokens", "completion_token_count"),
        )
        total_tokens = _usage_component(candidate, ("total_tokens", "total_token_count"))
        if input_tokens and "input_tokens" not in merged:
            merged["input_tokens"] = input_tokens
        if output_tokens and "output_tokens" not in merged:
            merged["output_tokens"] = output_tokens
        if total_tokens and "total_tokens" not in merged:
            merged["total_tokens"] = total_tokens
        if all(key in merged for key in ("input_tokens", "output_tokens", "total_tokens")):
            break
    if not merged:
        return None
    normalized = normalize_token_usage(merged)
    return normalized if any(normalized.values()) else None


def _usage_component(payload: dict[str, Any], keys: tuple[str, ...]) -> int:
    return _int_value(*(payload.get(key) for key in keys))


def _int_value(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            try:
                decimal = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
            if not decimal.is_finite() or decimal != decimal.to_integral_value():
                continue
            number = int(decimal)
        return max(number, 0)
    return 0


__all__ = [
    "accumulate_token_usage",
    "message_token_usage",
    "messages_token_usage",
    "normalize_token_usage",
]
