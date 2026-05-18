"""Shared helpers for memory/context report scripts."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_REDACTION_TYPES = ("email", "bearer_token", "jwt", "token_literal", "secret", "phone")

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{10,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_TOKEN_LITERAL_RE = re.compile(
    r"\b(?:sk|pk|rk|ghp|gho|github_pat|xoxb|xoxp|ya29|pat|tok)[-_A-Za-z0-9.]{10,}\b"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?P<key>api[_-]?key|secret|access[_-]?token|refresh[_-]?token|token|"
    r"password|passwd|pwd)(?P<sep>\s*[:=]\s*)(?P<quote>[\"']?)(?P<value>[^\s\"',;)}\]]+)"
)
_PHONE_CANDIDATE_RE = re.compile(r"(?<![\w/])(?:\+?\d[\d .()/-]{8,}\d)(?![\w/])")


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _load_json_or_jsonl(path: Path) -> Any:
    source = path.expanduser()
    text = source.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        records: list[Any] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            candidate = line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            try:
                records.append(json.loads(candidate))
            except json.JSONDecodeError:
                try:
                    records.append(ast.literal_eval(candidate))
                except (SyntaxError, ValueError) as exc:
                    raise ValueError(f"{source}:{line_no} invalid JSON/JSONL: {exc}") from exc
        return records


def _sanitize_json(value: Any) -> Any:
    sanitized, _summary = _sanitize_json_with_summary(value)
    return sanitized


def _sanitize_json_with_summary(value: Any) -> tuple[Any, dict[str, int]]:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        summary = _empty_redaction_summary()
        for key, item in value.items():
            redacted_item, item_summary = _sanitize_json_with_summary(item)
            sanitized[str(key)] = redacted_item
            summary = _merge_redaction_summaries(summary, item_summary)
        return sanitized, summary
    if isinstance(value, list):
        sanitized_items: list[Any] = []
        summary = _empty_redaction_summary()
        for item in value:
            redacted_item, item_summary = _sanitize_json_with_summary(item)
            sanitized_items.append(redacted_item)
            summary = _merge_redaction_summaries(summary, item_summary)
        return sanitized_items, summary
    if isinstance(value, str):
        return _sanitize_text_with_summary(value)
    return value, _empty_redaction_summary()


def _sanitize_text(value: str) -> str:
    sanitized, _summary = _sanitize_text_with_summary(value)
    return sanitized


def _sanitize_text_with_summary(value: str) -> tuple[str, dict[str, int]]:
    summary = _empty_redaction_summary()
    sanitized, count = _BEARER_TOKEN_RE.subn("Bearer [REDACTED_TOKEN]", value)
    summary["bearer_token"] += count
    sanitized, count = _JWT_RE.subn("[REDACTED_TOKEN]", sanitized)
    summary["jwt"] += count
    sanitized, count = _SECRET_ASSIGNMENT_RE.subn(_redact_secret_assignment, sanitized)
    summary["secret"] += count
    sanitized, count = _TOKEN_LITERAL_RE.subn("[REDACTED_TOKEN]", sanitized)
    summary["token_literal"] += count
    sanitized, count = _EMAIL_RE.subn("[REDACTED_EMAIL]", sanitized)
    summary["email"] += count
    phone_count = 0

    def redact_phone(match: re.Match[str]) -> str:
        nonlocal phone_count
        redacted = _redact_phone_like(match)
        if redacted == "[REDACTED_PHONE]":
            phone_count += 1
        return redacted

    sanitized = _PHONE_CANDIDATE_RE.sub(redact_phone, sanitized)
    summary["phone"] += phone_count
    return sanitized, summary


def _empty_redaction_summary() -> dict[str, int]:
    return {name: 0 for name in _REDACTION_TYPES}


def _merge_redaction_summaries(
    left: dict[str, int],
    right: dict[str, int],
) -> dict[str, int]:
    return {name: int(left.get(name, 0)) + int(right.get(name, 0)) for name in _REDACTION_TYPES}


def _redaction_summary_payload(summary: dict[str, int]) -> dict[str, int]:
    payload = {name: int(summary.get(name, 0)) for name in _REDACTION_TYPES}
    payload["total"] = sum(payload.values())
    return payload


def _with_privacy_summary(case: Any, redactions: dict[str, int]) -> Any:
    if not isinstance(case, dict):
        return case
    updated = dict(case)
    existing = updated.get("privacy") if isinstance(updated.get("privacy"), dict) else {}
    payload = _redaction_summary_payload(redactions)
    updated["privacy"] = {
        **existing,
        "redacted": payload["total"] > 0,
        "redaction_summary": payload,
    }
    return updated


def _duplicate_reason(
    case: dict[str, Any],
    *,
    duplicate_of: str,
    dedupe_key: str,
    operation: str,
) -> dict[str, Any]:
    origin = case.get("origin") if isinstance(case.get("origin"), dict) else {}
    return {
        "operation": operation,
        "candidate_id": str(case.get("id") or ""),
        "duplicate_of": duplicate_of,
        "reason": "same sanitized input and expected assertions",
        "dedupe_key": dedupe_key[:12],
        "source_type": str(origin.get("source_type") or ""),
        "source_name": str(origin.get("source_name") or ""),
        "source_record_id": str(origin.get("source_record_id") or ""),
    }


def _redact_secret_assignment(match: re.Match[str]) -> str:
    quote = match.group("quote") or ""
    return f"{match.group('key')}{match.group('sep')}{quote}[REDACTED_SECRET]{quote}"


def _redact_phone_like(match: re.Match[str]) -> str:
    value = match.group(0)
    digits = re.sub(r"\D", "", value)
    if 10 <= len(digits) <= 15:
        return "[REDACTED_PHONE]"
    return value


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _nested_text(mapping: dict[str, Any], path: Sequence[str]) -> str:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current or "")


def _slug(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "")).strip("-").lower()


def _contains(haystack: str, needle: str) -> bool:
    normalized_haystack = _normalize_text(haystack)
    normalized_needle = _normalize_text(needle)
    return normalized_needle in normalized_haystack


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _candidate_aging(
    candidate_created_at: datetime,
    *,
    now: datetime,
    promotion_review_sla_days: int,
) -> dict[str, Any]:
    age_days = max(0.0, (now - candidate_created_at).total_seconds() / 86400)
    sla_days = max(0, int(promotion_review_sla_days))
    due_at = candidate_created_at + timedelta(days=sla_days)
    overdue = now > due_at
    if overdue:
        age_bucket = "over_sla"
    elif age_days >= max(1, sla_days * 0.75):
        age_bucket = "aging"
    else:
        age_bucket = "fresh"
    return {
        "age_days": round(age_days, 4),
        "age_bucket": age_bucket,
        "promotion_review_sla": {
            "sla_days": sla_days,
            "candidate_created_at": _isoformat_z(candidate_created_at),
            "review_due_at": _isoformat_z(due_at),
            "age_days": round(age_days, 4),
            "overdue": overdue,
            "status": "overdue" if overdue else "within_sla",
        },
    }


def _candidate_age_summary(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ages: list[float] = []
    buckets: dict[str, int] = {}
    overdue = 0
    for case in cases:
        candidate_ops = case.get("candidate_ops") if isinstance(case.get("candidate_ops"), dict) else {}
        age = candidate_ops.get("candidate_age_days")
        if age is not None:
            ages.append(_number(age))
        bucket = str(candidate_ops.get("candidate_age_bucket") or "")
        if bucket:
            buckets[bucket] = buckets.get(bucket, 0) + 1
        sla = candidate_ops.get("promotion_review_sla")
        if isinstance(sla, dict) and sla.get("overdue") is True:
            overdue += 1
    return {
        "total": len(cases),
        "avg_age_days": round(sum(ages) / len(ages), 4) if ages else 0.0,
        "max_age_days": round(max(ages), 4) if ages else 0.0,
        "age_buckets": buckets,
        "promotion_review_overdue": overdue,
    }


def _promotion_sla_summary(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    reviewed = 0
    overdue = 0
    pending_overdue = 0
    for case in cases:
        review = case.get("promotion_review") if isinstance(case.get("promotion_review"), dict) else {}
        sla = review.get("sla") if isinstance(review.get("sla"), dict) else {}
        if not sla:
            continue
        reviewed += 1
        is_overdue = bool(sla.get("overdue") or sla.get("reviewed_after_due"))
        if is_overdue:
            overdue += 1
            if review.get("status") == "pending":
                pending_overdue += 1
    return {
        "reviewed": reviewed,
        "overdue": overdue,
        "pending_overdue": pending_overdue,
    }


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        parsed = datetime.fromtimestamp(seconds, tz=UTC)
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return _coerce_datetime(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
