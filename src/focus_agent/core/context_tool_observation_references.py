from __future__ import annotations

from typing import Any

from .context_tool_observation_json import (
    _collapse_inline,
    _truncate_json_payload,
    _truncate_text,
)


def _tool_observation_ref(*, tool_name: str, tool_call_id: str) -> str:
    normalized_tool = (tool_name or "tool").strip() or "tool"
    normalized_call = (tool_call_id or "latest").strip() or "latest"
    return f"tool-observation://{normalized_tool}/{normalized_call}"


def _collect_artifact_like_refs(payload: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(payload, dict):
        top_level_ref = _artifact_like_ref_from_mapping(payload)
        if top_level_ref:
            refs.append(top_level_ref)
        for key in ("results", "hits", "items"):
            values = payload.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                ref = _artifact_like_ref_from_mapping(value)
                if ref:
                    refs.append(ref)
    elif isinstance(payload, list):
        for value in payload:
            ref = _artifact_like_ref_from_mapping(value)
            if ref:
                refs.append(ref)
    return list(dict.fromkeys(refs))


def _artifact_like_ref_from_mapping(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    path = value.get("path")
    line_number = value.get("line_number")
    start_line = value.get("start_line")
    end_line = value.get("end_line")
    url = value.get("final_url") or value.get("url")
    if path:
        if line_number is not None:
            return f"{path}:{line_number}"
        if start_line is not None and end_line is not None:
            return f"{path}:{start_line}-{end_line}"
        if start_line is not None:
            return f"{path}:{start_line}"
        return str(path)
    if url:
        return str(url)
    return None


def _format_textual_tool_reference(
    text: str,
    *,
    tool_name: str,
    tool_call_id: str,
    max_chars: int,
    reference_chars: int,
) -> str:
    reference_budget = max(18, min(max_chars // 3, reference_chars, 36))
    payload = {
        "summary": f"{tool_name or 'tool'} trimmed.",
        "reference": _truncate_text(_collapse_inline(text), max_chars=reference_budget),
        "original_chars": len(text),
    }
    if tool_call_id or tool_name in {"search_code", "read_file"}:
        payload["tool"] = tool_name or "tool"
    if tool_call_id:
        payload["artifact_ref"] = _tool_observation_ref(
            tool_name=tool_name, tool_call_id=tool_call_id
        )
    payload = {key: value for key, value in payload.items() if value is not None}
    return _truncate_json_payload(payload, max_chars=max_chars)


def _structured_tool_reference(
    payload: dict[str, Any],
    *,
    tool_name: str,
    max_chars: int,
    artifactize_for_prompt: bool,
) -> str:
    details: list[str] = []
    if tool_name == "search_code":
        query = str(payload.get("query") or "").strip()
        if query:
            details.append(f"query={query}")
        results = payload.get("results")
        if isinstance(results, list):
            details.append(f"hits={len(results)}")
    elif tool_name == "read_file":
        path = str(payload.get("path") or "").strip()
        if path:
            details.append(f"path={path}")
        start_line = payload.get("start_line")
        end_line = payload.get("end_line")
        if start_line is not None and end_line is not None:
            details.append(f"lines={start_line}-{end_line}")
        total_lines = payload.get("total_lines")
        if total_lines is not None:
            details.append(f"total_lines={total_lines}")
        sample_line = next(
            (
                line.strip()
                for line in str(payload.get("content") or "").splitlines()
                if line.strip()
            ),
            "",
        )
        if sample_line:
            details.append(f"sample={_collapse_inline(sample_line)[:120]}")
    else:
        for key in ("path", "url", "title", "query"):
            value = str(payload.get(key) or "").strip()
            if value:
                details.append(f"{key}={value}")
    if artifactize_for_prompt:
        refs = _collect_artifact_like_refs(payload)
        if refs:
            details[:0] = [f"refs={', '.join(refs[:4])}"]
    if not details:
        details.append("original observation omitted from prompt body")
    return _collapse_inline("; ".join(details))[:max_chars]
