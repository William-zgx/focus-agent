from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from focus_agent.engine.graph.tool_messages import iter_tool_results


def _latest_tool_result_content(messages: list[Any], tool_name: str) -> str:
    latest = ""
    for message, name, _args in iter_tool_results(messages):
        if name == tool_name:
            latest = _message_content_text(message)
    return latest


def _message_content_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block.strip() if isinstance(block, str) else str(block.get("text") or "").strip()
            for block in content
            if isinstance(block, (str, Mapping))
            and (isinstance(block, str) or block.get("type") in {None, "text", "output_text"})
        ]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, Mapping) and content.get("type") in {None, "text", "output_text"}:
        return str(content.get("text") or "").strip()
    return str(content or "").strip()


def _new_citation_refs(
    citation_refs: list[dict[str, str | None]],
    *,
    existing: list[Any],
) -> list[dict[str, str | None]]:
    seen = {_citation_key(item) for item in existing}
    unique: list[dict[str, str | None]] = []
    for item in citation_refs:
        key = _citation_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _citation_key(item: Any) -> tuple[str, str]:
    if isinstance(item, Mapping):
        return (str(item.get("uri") or ""), str(item.get("label") or ""))
    return (
        str(getattr(item, "uri", "") or ""),
        str(getattr(item, "label", "") or ""),
    )
