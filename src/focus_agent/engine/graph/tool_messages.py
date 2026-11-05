"""Shared helpers for reading tool calls and tool results out of message history."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from langchain.messages import ToolMessage

from focus_agent.core.context_tool_observation_references import _tool_observation_ref
from focus_agent.core.runtime_outcome import payload_failure

PUBLISHED_AT_KEYS = (
    "published_at",
    "published",
    "published_date",
    "publishedDate",
    "publication_date",
    "published_on",
    "published_time",
    "date",
)


def _tool_calls(message: Any) -> Iterator[tuple[str, Mapping[str, Any]]]:
    for call in getattr(message, "tool_calls", None) or ():
        if not isinstance(call, Mapping):
            continue
        call_id = str(call.get("id") or "").strip()
        if call_id:
            yield call_id, call


def tool_call_names_by_id(messages: Iterable[Any]) -> dict[str, str]:
    """Map tool-call id to tool name for every named tool call in ``messages``."""

    names: dict[str, str] = {}
    for message in messages:
        for call_id, call in _tool_calls(message):
            name = str(call.get("name") or "").strip()
            if name:
                names[call_id] = name
    return names


def iter_tool_results(
    messages: Iterable[Any],
) -> Iterator[tuple[ToolMessage, str, Mapping[str, Any]]]:
    """Yield ``(tool_message, tool_name, tool_args)`` in message order.

    Each result is matched against the tool calls seen *before* it. Results
    without a matching named call yield an empty name and empty args.
    """

    calls: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for message in messages:
        for call_id, call in _tool_calls(message):
            name = str(call.get("name") or "").strip()
            if name:
                args = call.get("args")
                calls[call_id] = (name, args if isinstance(args, Mapping) else {})
        if isinstance(message, ToolMessage):
            call_id = str(getattr(message, "tool_call_id", "") or "").strip()
            name, args = calls.get(call_id, ("", {}))
            yield message, name, args


def tool_message_json(message: Any) -> Any:
    """Return the JSON value carried by a tool message, or ``None`` if it has none.

    Structured (list/dict) content is returned as-is; string content is parsed.
    """

    content = getattr(message, "content", "")
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except ValueError:
        return None


def prompt_observation_json(message: Any) -> Any | None:
    """Return the JSON prompt view saved on a tool message artifact, if any."""

    artifact = getattr(message, "artifact", None)
    if not isinstance(artifact, Mapping):
        return None
    prompt_observation = artifact.get("prompt_observation")
    if not isinstance(prompt_observation, str) or not prompt_observation.strip():
        return None
    try:
        return json.loads(prompt_observation)
    except ValueError:
        return None


def tool_message_failed(message: Any, payload: Any = None) -> bool:
    """Single rule for "this tool result is a failure" across the research path.

    A result fails when the transport marked it ``status="error"`` or when its
    JSON payload reports a failure (``status`` error/failed, ``error`` set,
    ``ok``/``success`` false, ``timed_out``, non-zero ``exit_code``, or an
    embedded failing command payload). ``payload`` may be passed when the
    caller already parsed the message.
    """

    status = str(getattr(message, "status", "") or "").strip().lower()
    if status in {"error", "failed"}:
        return True
    if payload is None:
        payload = tool_message_json(message)
    return payload_failure(payload) is not None


def payload_published_at(payload: Any) -> str | None:
    """Return the first publication date found on a payload or its metadata."""

    if not isinstance(payload, Mapping):
        return None
    for source in (payload, payload.get("metadata"), payload.get("meta")):
        if not isinstance(source, Mapping):
            continue
        for key in PUBLISHED_AT_KEYS:
            value = " ".join(str(source.get(key) or "").split())
            if value:
                return value
    return None


def artifact_source_refs(
    *, tool_name: str, tool_call_id: str, payload: Any, prompt_payload: Any = None
) -> list[str]:
    """Refs under which an ``artifact_read`` call can later name this fetched page.

    Covers the prompt-only observation ref and any ``artifact_ref`` the tool or
    its prompt view advertised for continuation.
    """

    refs = [_tool_observation_ref(tool_name=tool_name, tool_call_id=tool_call_id)]
    for view in (payload, prompt_payload):
        if isinstance(view, Mapping) and view.get("artifact_ref"):
            refs.append(str(view["artifact_ref"]))
    return list(dict.fromkeys(refs))


__all__ = [
    "PUBLISHED_AT_KEYS",
    "artifact_source_refs",
    "iter_tool_results",
    "payload_published_at",
    "prompt_observation_json",
    "tool_call_names_by_id",
    "tool_message_failed",
    "tool_message_json",
]
