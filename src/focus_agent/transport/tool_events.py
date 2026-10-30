"""Tool-call and tool-result event extraction for graph stream chunks and updates."""

from __future__ import annotations

from typing import Any

from .stream_events import TOOL_BLOCK_TYPES, _iter_blocks, _stringify


def _tool_call_chunk_payload(*, raw: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "args_delta": _stringify(raw.get("args") or raw.get("args_text") or raw.get("input")),
        "raw": raw,
    }
    tool_call_id = raw.get("id") or raw.get("tool_call_id") or raw.get("call_id")
    if tool_call_id is not None:
        payload["id"] = str(tool_call_id)
    name = raw.get("name")
    if name is not None:
        payload["name"] = str(name)
    return payload


def _tool_identity_payload(*, tool_call_id: Any = None, name: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if tool_call_id is not None:
        call_id = str(tool_call_id)
        payload["id"] = call_id
        payload["tool_call_id"] = call_id
    if name is not None:
        tool_name = str(name)
        payload["name"] = tool_name
        payload["tool_name"] = tool_name
    return payload


def extract_tool_call_chunks(message_chunk: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for chunk in getattr(message_chunk, "tool_call_chunks", []) or []:
        if not isinstance(chunk, dict):
            continue
        chunks.append(_tool_call_chunk_payload(raw=chunk))
    for call in getattr(message_chunk, "tool_calls", []) or []:
        if not isinstance(call, dict):
            continue
        chunks.append(_tool_call_chunk_payload(raw=call))
    for block in _iter_blocks(message_chunk):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type not in TOOL_BLOCK_TYPES:
            continue
        chunks.append(_tool_call_chunk_payload(raw=block))
    return chunks


def map_custom_payload_to_event(payload: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(payload, dict):
        if payload.get("event") == "tool":
            stage = str(payload.get("stage") or "delta")
            event_name = {
                "start": "tool.requested",
                "delta": "state.update",
                "progress": "state.update",
                "end": "tool.result",
                "error": "tool.error",
            }.get(stage, "state.update")
            normalized = dict(payload)
            normalized.update(
                _tool_identity_payload(
                    tool_call_id=payload.get("tool_call_id")
                    or payload.get("id")
                    or payload.get("call_id"),
                    name=payload.get("tool_name") or payload.get("name"),
                )
            )
            return event_name, normalized
        if payload.get("event") == "status":
            return "run.status", dict(payload)
        return "state.update", dict(payload)
    return "state.update", {"value": payload}


def extract_tool_requests_from_updates(data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node_name, node_state in (data or {}).items():
        messages = []
        if isinstance(node_state, dict):
            messages = list(node_state.get("messages") or [])
        for message in messages:
            for tool_call in getattr(message, "tool_calls", []) or []:
                results.append(
                    {
                        "node": node_name,
                        "tool_name": tool_call.get("name"),
                        "name": tool_call.get("name"),
                        "tool_call_id": tool_call.get("id"),
                        "id": tool_call.get("id"),
                        "args": tool_call.get("args"),
                    }
                )
    return results


def extract_tool_results_from_updates(data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node_name, node_state in (data or {}).items():
        messages = []
        tool_outcomes = []
        if isinstance(node_state, dict):
            messages = list(node_state.get("messages") or [])
            tool_outcomes = [
                item
                for item in list(node_state.get("tool_outcomes") or [])
                if isinstance(item, dict)
            ]
        tool_messages = [message for message in messages if getattr(message, "type", "") == "tool"]
        if tool_outcomes:
            latest_message_by_call_id = {
                str(getattr(message, "tool_call_id", None) or ""): message
                for message in tool_messages
                if str(getattr(message, "tool_call_id", None) or "")
            }
            latest_outcome_index_by_call_id = _latest_outcome_index_by_call_id(tool_outcomes)
            for index, tool_outcome in enumerate(tool_outcomes):
                call_id = str(tool_outcome.get("tool_call_id") or "").strip()
                message = (
                    latest_message_by_call_id.get(call_id)
                    if latest_outcome_index_by_call_id.get(call_id) == index
                    else None
                )
                results.append(
                    _tool_result_payload_from_outcome(
                        node_name=node_name,
                        tool_outcome=tool_outcome,
                        message=message,
                    )
                )
            continue

        for message in tool_messages:
            message_type = getattr(message, "type", "")
            if message_type != "tool":
                continue
            artifact = getattr(message, "artifact", None)
            artifact_payload = dict(artifact or {}) if isinstance(artifact, dict) else {}
            runtime_payload = artifact_payload.get("runtime")
            runtime_payload = (
                dict(runtime_payload or {}) if isinstance(runtime_payload, dict) else {}
            )
            tool_call_id = getattr(message, "tool_call_id", None)
            tool_outcome = _tool_outcome_for_call(tool_outcomes, tool_call_id)
            tool_name = (
                getattr(message, "name", None)
                or artifact_payload.get("tool_name")
                or (tool_outcome or {}).get("tool_name")
            )
            status = getattr(message, "status", None)
            results.append(
                {
                    "node": node_name,
                    "tool_call_id": tool_call_id,
                    "id": tool_call_id,
                    "content": _stringify(getattr(message, "content", "")),
                    "name": tool_name,
                    "tool_name": tool_name,
                    "status": status,
                    "runtime": runtime_payload,
                    "tool_outcome": tool_outcome,
                }
            )
    return results


def _latest_outcome_index_by_call_id(tool_outcomes: list[dict[str, Any]]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for index, outcome in enumerate(tool_outcomes):
        call_id = str(outcome.get("tool_call_id") or "").strip()
        if call_id:
            indexes[call_id] = index
    return indexes


def _tool_result_payload_from_outcome(
    *,
    node_name: str,
    tool_outcome: dict[str, Any],
    message: Any | None,
) -> dict[str, Any]:
    artifact_payload: dict[str, Any] = {}
    runtime_payload: dict[str, Any] = {}
    if message is not None:
        artifact = getattr(message, "artifact", None)
        artifact_payload = dict(artifact or {}) if isinstance(artifact, dict) else {}
        runtime = artifact_payload.get("runtime")
        runtime_payload = dict(runtime or {}) if isinstance(runtime, dict) else {}
    else:
        runtime_payload = _runtime_payload_from_tool_outcome(tool_outcome)

    tool_call_id = (
        getattr(message, "tool_call_id", None)
        if message is not None
        else tool_outcome.get("tool_call_id")
    )
    tool_name = (
        (getattr(message, "name", None) if message is not None else None)
        or artifact_payload.get("tool_name")
        or tool_outcome.get("tool_name")
    )
    status = (
        getattr(message, "status", None)
        if message is not None
        else _message_status_from_tool_outcome(tool_outcome)
    )
    content = (
        _stringify(getattr(message, "content", ""))
        if message is not None
        else _content_from_tool_outcome(tool_outcome)
    )
    return {
        "node": node_name,
        "tool_call_id": tool_call_id,
        "id": tool_call_id,
        "content": content,
        "name": tool_name,
        "tool_name": tool_name,
        "status": status,
        "runtime": runtime_payload,
        "tool_outcome": dict(tool_outcome),
    }


def _runtime_payload_from_tool_outcome(tool_outcome: dict[str, Any]) -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "tool_outcome": dict(tool_outcome),
        "attempt_index": tool_outcome.get("attempt_index"),
        "max_attempts": tool_outcome.get("max_attempts"),
        "retryable": tool_outcome.get("retryable"),
        "fallback_used": tool_outcome.get("fallback_used"),
        "fallback_group": tool_outcome.get("fallback_group"),
        "error_category": tool_outcome.get("error_category"),
    }
    if tool_outcome.get("duration_ms") is not None:
        runtime["duration_ms"] = tool_outcome.get("duration_ms")
    if tool_outcome.get("cache_hit") is not None:
        runtime["cache_hit"] = tool_outcome.get("cache_hit")
    return runtime


def _message_status_from_tool_outcome(tool_outcome: dict[str, Any]) -> str:
    status = str(tool_outcome.get("status") or "").strip().lower()
    return "error" if status in {"failed", "blocked"} else "success"


def _content_from_tool_outcome(tool_outcome: dict[str, Any]) -> str:
    error_message = str(tool_outcome.get("error_message") or "").strip()
    if error_message:
        return error_message
    status = str(tool_outcome.get("status") or "").strip()
    tool_name = str(tool_outcome.get("tool_name") or "tool").strip()
    attempt = tool_outcome.get("attempt_index")
    return f"{tool_name} attempt {attempt or '?'} {status or 'completed'}".strip()


def _tool_outcome_for_call(
    tool_outcomes: list[dict[str, Any]],
    tool_call_id: Any,
) -> dict[str, Any] | None:
    call_id = str(tool_call_id or "").strip()
    if not call_id:
        return None
    for outcome in reversed(tool_outcomes):
        if str(outcome.get("tool_call_id") or "").strip() == call_id:
            return dict(outcome)
    return None
