from __future__ import annotations

import json
from typing import Any

from langchain.messages import AIMessage


def _known_tool_names(available_tools: list[Any] | tuple[Any, ...] | None = None) -> set[str]:
    return {
        str(getattr(tool, "name", "")).strip()
        for tool in available_tools or []
        if str(getattr(tool, "name", "")).strip()
    }


def _canonicalize_tool_call_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return dict(args)
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {"_raw_args": args}
        if isinstance(parsed, dict):
            return parsed
        return {"_raw_args": parsed}
    if args is None:
        return {}
    return {"_raw_args": args}


def _tool_call_signature(tool_call: dict[str, Any]) -> str:
    args_json = json.dumps(
        _canonicalize_tool_call_args(tool_call.get("args")),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"{str(tool_call.get('name') or '').strip()}:{args_json}"


def _repair_and_dedupe_tool_calls(message: Any) -> Any:
    if not isinstance(message, AIMessage) or not getattr(message, "tool_calls", None):
        return message

    repaired_calls: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    changed = False
    for index, raw_call in enumerate(getattr(message, "tool_calls", []) or []):
        if not isinstance(raw_call, dict):
            changed = True
            continue
        name = str(raw_call.get("name") or "").strip()
        if not name:
            changed = True
            continue
        args = _canonicalize_tool_call_args(raw_call.get("args"))
        call_id = str(raw_call.get("id") or "").strip() or f"repaired-tool-call-{index + 1}"
        repaired = {"id": call_id, "name": name, "args": args}
        signature = _tool_call_signature(repaired)
        if signature in seen_signatures:
            changed = True
            continue
        seen_signatures.add(signature)
        if repaired != raw_call:
            changed = True
        repaired_calls.append(repaired)

    if not changed:
        return message

    return AIMessage(
        content=getattr(message, "content", ""),
        additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
        response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
        name=getattr(message, "name", None),
        id=getattr(message, "id", None),
        tool_calls=repaired_calls,
        invalid_tool_calls=list(getattr(message, "invalid_tool_calls", []) or []),
        usage_metadata=getattr(message, "usage_metadata", None),
    )


__all__ = [
    "_known_tool_names",
    "_canonicalize_tool_call_args",
    "_tool_call_signature",
    "_repair_and_dedupe_tool_calls",
]
