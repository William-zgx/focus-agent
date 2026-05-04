from __future__ import annotations

import json
from typing import Any

from .context_tool_observation_json import _collapse_inline, _truncate_text
from .context_tool_observation_references import (
    _artifact_like_ref_from_mapping,
    _collect_artifact_like_refs,
    _format_textual_tool_reference,
    _structured_tool_reference,
    _tool_observation_ref,
)


def _compact_structured_observation(
    payload: Any,
    *,
    tool_name: str,
    tool_call_id: str,
    max_chars: int,
    reference_chars: int,
    artifactize_for_prompt: bool,
) -> Any:
    if isinstance(payload, list):
        compact = {
            "tool": tool_name or "tool",
            "summary": f"Structured tool output trimmed to {len(payload[:3]) if payload else 0} representative items.",
            "items": _compact_result_list(
                payload,
                max_chars=max_chars,
                artifactize_for_prompt=artifactize_for_prompt,
            ),
            "reference": f"Prompt view keeps representative items only; original observation had {len(payload)} list entries.",
            "truncated_by_context_policy": True,
        }
        if artifactize_for_prompt:
            compact["artifact_ref"] = _tool_observation_ref(
                tool_name=tool_name, tool_call_id=tool_call_id
            )
            refs = _collect_artifact_like_refs(payload)
            if refs:
                compact["refs"] = refs[:6]
            compact["summary"] = f"Prompt-only artifactized view of {len(payload)} list item(s)."
            compact["reference"] = _truncate_text(
                "Representative refs: " + "; ".join(refs[:6]) if refs else compact["reference"],
                max_chars=reference_chars,
            )
            compact["original_chars"] = len(json.dumps(payload, ensure_ascii=False, default=str))
        return compact
    if not isinstance(payload, dict):
        if not artifactize_for_prompt:
            return _truncate_text(str(payload), max_chars=max_chars)
        return _format_textual_tool_reference(
            str(payload),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            max_chars=max_chars,
            reference_chars=reference_chars,
        )

    compact: dict[str, Any] = {}
    for key in (
        "query",
        "path",
        "glob",
        "literal",
        "case_sensitive",
        "start_line",
        "end_line",
        "total_lines",
        "url",
        "final_url",
        "title",
        "content_type",
        "truncated",
    ):
        if key in payload:
            compact[key] = payload[key]

    if "results" in payload and isinstance(payload["results"], list):
        compact["results"] = _compact_result_list(
            payload["results"],
            max_chars=max_chars,
            artifactize_for_prompt=artifactize_for_prompt,
        )
    elif "hits" in payload and isinstance(payload["hits"], list):
        compact["hits"] = _compact_result_list(
            payload["hits"],
            max_chars=max_chars,
            artifactize_for_prompt=artifactize_for_prompt,
        )

    if "content" in payload:
        compact["content"] = _trim_numbered_content(
            str(payload.get("content") or ""), max_chars=max_chars // 2
        )
    if "diff" in payload:
        compact["diff"] = _trim_diff(str(payload.get("diff") or ""), max_chars=max_chars // 2)

    if tool_name and "tool" not in compact:
        compact["tool"] = tool_name
    compact["summary"] = _structured_tool_summary(
        payload,
        tool_name=tool_name,
        artifactize_for_prompt=artifactize_for_prompt,
    )
    compact["reference"] = _structured_tool_reference(
        payload,
        tool_name=tool_name,
        max_chars=reference_chars,
        artifactize_for_prompt=artifactize_for_prompt,
    )
    if artifactize_for_prompt:
        compact["artifact_ref"] = _tool_observation_ref(
            tool_name=tool_name, tool_call_id=tool_call_id
        )
        refs = _collect_artifact_like_refs(payload)
        if refs:
            compact["refs"] = refs[:6]
    compact["truncated_by_context_policy"] = True
    compact["original_chars"] = len(json.dumps(payload, ensure_ascii=False, default=str))
    return compact


def _compact_result_list(
    results: list[Any],
    *,
    max_chars: int,
    artifactize_for_prompt: bool,
) -> list[Any]:
    compact_results: list[Any] = []
    for result in results:
        if isinstance(result, dict):
            compact = {}
            ref = _artifact_like_ref_from_mapping(result) if artifactize_for_prompt else None
            if artifactize_for_prompt and ref:
                compact["ref"] = ref
                compact_results.append(compact)
                rendered = json.dumps(
                    compact_results, ensure_ascii=False, separators=(",", ":"), default=str
                )
                if len(rendered) >= max_chars // 2:
                    break
                continue
            for key in (
                "path",
                "line_number",
                "start_line",
                "end_line",
                "title",
                "url",
                "final_url",
            ):
                if key in result:
                    compact[key] = result[key]
            for key in ("line", "snippet", "content", "text"):
                if key in result:
                    compact[key] = _collapse_inline(str(result[key]))[:240]
                    break
            if artifactize_for_prompt and ref:
                compact["ref"] = ref
            compact_results.append(compact or _collapse_inline(str(result))[:240])
        else:
            compact_results.append(_collapse_inline(str(result))[:240])
        if len(json.dumps(compact_results, ensure_ascii=False, default=str)) >= max_chars // 2:
            break
    return compact_results


def _trim_numbered_content(content: str, *, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    lines = content.splitlines()
    kept: list[str] = []
    used = 0
    for line in lines:
        candidate = line[:400]
        extra = len(candidate) + (1 if kept else 0)
        if kept and used + extra > max_chars:
            break
        kept.append(candidate)
        used += extra
        if used >= max_chars:
            break
    return "\n".join(kept) + "\n...[tool output trimmed]..."


def _trim_diff(diff: str, *, max_chars: int) -> str:
    important = [
        line
        for line in diff.splitlines()
        if line.startswith(("diff --git", "+++", "---", "@@", "+", "-"))
    ]
    text = "\n".join(important or diff.splitlines())
    return _truncate_text(text, max_chars=max_chars)


def _structured_tool_summary(
    payload: dict[str, Any],
    *,
    tool_name: str,
    artifactize_for_prompt: bool,
) -> str:
    if tool_name == "search_code":
        count = len(payload.get("results") or [])
        query = str(payload.get("query") or "").strip()
        if artifactize_for_prompt:
            return f"artifactized search_code view: {count} hit(s) for {query or 'query'}."
        return f"search_code: {count} hit(s) for {query or 'query'}."
    if tool_name == "read_file":
        path = str(payload.get("path") or "the requested file").strip()
        start_line = payload.get("start_line")
        end_line = payload.get("end_line")
        if start_line is not None and end_line is not None:
            verb = "artifactized" if artifactize_for_prompt else "returned"
            return f"read_file {verb} {path} lines {start_line}-{end_line}."
        verb = "artifactized" if artifactize_for_prompt else "returned content from"
        return f"read_file {verb} {path}."
    if tool_name:
        if artifactize_for_prompt:
            return f"{tool_name} output was compressed into an artifact-like prompt reference."
        return f"{tool_name} output was compressed for prompt budgeting."
    if artifactize_for_prompt:
        return "Structured tool output was compressed into an artifact-like prompt reference."
    return "Structured tool output was compressed for prompt budgeting."
