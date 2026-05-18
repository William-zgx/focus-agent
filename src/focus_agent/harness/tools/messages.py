from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.messages import ToolMessage

from ...capabilities.tool_messages import build_tool_message
from .envelope import ToolResultContent, ToolResultEnvelope, ToolResultStatus

_NORMALIZED_ARTIFACT_KEYS = frozenset({"runtime", "tool_name", "prompt_observation"})


def tool_message_to_envelope(
    message: ToolMessage,
    *,
    tool_name: str | None = None,
) -> ToolResultEnvelope:
    artifact = _mapping_from(getattr(message, "artifact", None))
    runtime = _mapping_from(artifact.get("runtime"))
    prompt_observation = artifact.get("prompt_observation")
    extra_artifact = {
        str(key): value
        for key, value in artifact.items()
        if str(key) not in _NORMALIZED_ARTIFACT_KEYS
    }
    return ToolResultEnvelope(
        tool_call_id=str(getattr(message, "tool_call_id", "")),
        tool_name=_resolve_tool_name(message=message, artifact=artifact, override=tool_name),
        content=_coerce_content(getattr(message, "content", "")),
        status=_coerce_status(getattr(message, "status", "success")),
        runtime=runtime,
        prompt_observation=prompt_observation if isinstance(prompt_observation, str) else None,
        artifact=extra_artifact,
        message_id=_optional_str(getattr(message, "id", None)),
        name=_optional_str(getattr(message, "name", None)),
        additional_kwargs=_mapping_from(getattr(message, "additional_kwargs", None)),
        response_metadata=_mapping_from(getattr(message, "response_metadata", None)),
    )


def envelope_to_tool_message(envelope: ToolResultEnvelope | Mapping[str, Any]) -> ToolMessage:
    normalized = (
        envelope
        if isinstance(envelope, ToolResultEnvelope)
        else ToolResultEnvelope.model_validate(envelope)
    )
    artifact = _artifact_for_envelope(normalized)
    if isinstance(normalized.content, str):
        message = build_tool_message(
            content=normalized.content,
            tool_call_id=normalized.tool_call_id,
            tool_name=normalized.tool_name,
            prompt_observation=normalized.prompt_observation,
            status=normalized.status,
            runtime_info=normalized.runtime,
        )
        message.artifact = artifact
    else:
        message = ToolMessage(
            content=normalized.content,
            tool_call_id=normalized.tool_call_id,
            status=normalized.status,
            artifact=artifact,
        )
    if normalized.message_id is not None:
        message.id = normalized.message_id
    if normalized.name is not None:
        message.name = normalized.name
    if normalized.additional_kwargs:
        message.additional_kwargs = dict(normalized.additional_kwargs)
    if normalized.response_metadata:
        message.response_metadata = dict(normalized.response_metadata)
    return message


def _artifact_for_envelope(envelope: ToolResultEnvelope) -> dict[str, Any]:
    artifact = {
        str(key): value
        for key, value in envelope.artifact.items()
        if str(key) not in _NORMALIZED_ARTIFACT_KEYS
    }
    artifact["runtime"] = dict(envelope.runtime)
    artifact["tool_name"] = envelope.tool_name
    if envelope.prompt_observation is not None:
        artifact["prompt_observation"] = envelope.prompt_observation
    return artifact


def _resolve_tool_name(
    *,
    message: ToolMessage,
    artifact: Mapping[str, Any],
    override: str | None,
) -> str:
    if override is not None and override.strip():
        return override.strip()
    artifact_tool_name = artifact.get("tool_name")
    if isinstance(artifact_tool_name, str) and artifact_tool_name.strip():
        return artifact_tool_name.strip()
    tool_payload = artifact.get("tool")
    if isinstance(tool_payload, Mapping):
        nested_name = tool_payload.get("name")
        if isinstance(nested_name, str) and nested_name.strip():
            return nested_name.strip()
    message_name = getattr(message, "name", None)
    return message_name.strip() if isinstance(message_name, str) and message_name.strip() else ""


def _coerce_content(value: object) -> ToolResultContent:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        content: list[str | dict[str, Any]] = []
        for item in value:
            if isinstance(item, str):
                content.append(item)
            elif isinstance(item, Mapping):
                content.append({str(key): nested for key, nested in item.items()})
            else:
                content.append(str(item))
        return content
    return "" if value is None else str(value)


def _coerce_status(value: object) -> ToolResultStatus:
    return "error" if str(value).strip().lower() == "error" else "success"


def _mapping_from(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): nested for key, nested in value.items()}


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
