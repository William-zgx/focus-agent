from __future__ import annotations

import json
from typing import Any


def _collapse_inline(text: str) -> str:
    return " ".join(text.split())


def _truncate_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 32:
        return text[:max_chars]
    marker = "\n...[tool output trimmed]...\n"
    keep = max_chars - len(marker)
    head = max(1, keep // 2)
    tail = max(1, keep - head)
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def _truncate_json_payload(payload: Any, *, max_chars: int) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(rendered) <= max_chars:
        return rendered
    if isinstance(payload, dict):
        compact = {
            key: value
            for key, value in payload.items()
            if key
            in {
                "query",
                "path",
                "start_line",
                "end_line",
                "total_lines",
                "results",
                "hits",
                "tool",
                "artifact_ref",
                "summary",
                "reference",
                "refs",
                "truncated_by_context_policy",
                "original_chars",
            }
        }
        compact = _shrink_json_payload(compact, max_chars=max_chars)
        rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(rendered) <= max_chars:
        return rendered
    base_summary = payload.get("summary") if isinstance(payload, dict) else "Tool output trimmed."
    fallback_variants = [
        {
            "tool": payload.get("tool") if isinstance(payload, dict) else "tool",
            "artifact_ref": payload.get("artifact_ref") if isinstance(payload, dict) else None,
            "refs": (
                payload.get("refs")[:1]
                if isinstance(payload, dict) and isinstance(payload.get("refs"), list)
                else []
            ),
            "summary": _collapse_inline(str(base_summary or "Tool output trimmed."))[:48],
            "truncated_by_context_policy": True,
            "original_chars": payload.get("original_chars") if isinstance(payload, dict) else None,
        },
        {
            "tool": payload.get("tool") if isinstance(payload, dict) else "tool",
            "artifact_ref": payload.get("artifact_ref") if isinstance(payload, dict) else None,
            "refs": (
                payload.get("refs")[:1]
                if isinstance(payload, dict) and isinstance(payload.get("refs"), list)
                else []
            ),
            "summary": _collapse_inline(str(base_summary or "Tool output trimmed."))[:24],
            "truncated_by_context_policy": True,
        },
        {
            "artifact_ref": payload.get("artifact_ref") if isinstance(payload, dict) else None,
            "refs": (
                payload.get("refs")[:1]
                if isinstance(payload, dict) and isinstance(payload.get("refs"), list)
                else []
            ),
            "truncated_by_context_policy": True,
        },
        {"truncated_by_context_policy": True},
    ]
    for fallback in fallback_variants:
        fallback = {key: value for key, value in fallback.items() if value not in (None, [], "")}
        rendered = json.dumps(fallback, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(rendered) <= max_chars:
            return rendered
    return "{}" if max_chars >= 2 else ""


def _shrink_json_payload(payload: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    compact = dict(payload)
    inline_limit = max(24, min(120, max_chars // 3))
    for key in ("summary", "reference", "excerpt", "content", "diff"):
        value = compact.get(key)
        if isinstance(value, str):
            compact[key] = _collapse_inline(value)[:inline_limit]
    for key in ("refs",):
        value = compact.get(key)
        if isinstance(value, list):
            compact[key] = [str(item)[: max(32, min(96, max_chars // 2))] for item in value[:4]]
    for key in ("results", "hits", "items"):
        value = compact.get(key)
        if isinstance(value, list):
            compact[key] = _shrink_json_result_list(value, max_chars=max_chars // 2)
    rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(rendered) <= max_chars:
        return compact

    optional_keys = [
        "content",
        "diff",
        "excerpt",
        "query",
        "path",
        "start_line",
        "end_line",
        "total_lines",
        "tool",
        "original_chars",
        "hits",
        "items",
        "reference",
        "summary",
        "results",
    ]
    for key in optional_keys:
        if key not in compact:
            continue
        trimmed = dict(compact)
        trimmed.pop(key, None)
        rendered = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(rendered) <= max_chars:
            return trimmed
        compact = trimmed
    return compact


def _shrink_json_result_list(results: list[Any], *, max_chars: int) -> list[Any]:
    compact_results: list[Any] = []
    for result in results[:4]:
        if isinstance(result, dict):
            compact_item: dict[str, Any] = {}
            for key, value in result.items():
                if isinstance(value, str):
                    compact_item[key] = _collapse_inline(value)[:120]
                else:
                    compact_item[key] = value
            compact_results.append(compact_item)
        else:
            compact_results.append(_collapse_inline(str(result))[:120])
        rendered = json.dumps(
            compact_results, ensure_ascii=False, separators=(",", ":"), default=str
        )
        if len(rendered) > max_chars:
            if len(compact_results) == 1 and isinstance(result, dict):
                slim_item: dict[str, Any] = {}
                for key, value in compact_item.items():
                    if isinstance(value, str):
                        slim_item[key] = value[: max(24, min(72, max_chars // 2))]
                    else:
                        slim_item[key] = value
                compact_results[0] = slim_item
                rendered = json.dumps(
                    compact_results, ensure_ascii=False, separators=(",", ":"), default=str
                )
                if len(rendered) <= max_chars:
                    continue
            compact_results.pop()
            break
    return compact_results
