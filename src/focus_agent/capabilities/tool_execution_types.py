from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from langchain.messages import ToolMessage

from .tool_registry import ToolRuntimeMeta

TOOL_APPROVAL_INTERRUPT_KIND = "tool_approval"
TOOL_APPROVAL_POLICY_VERSION = "tool_approval.v2"
REDACTED_ARG_VALUE = "[REDACTED]"
_COMMON_SENSITIVE_ARG_MARKERS = (
    "api_key",
    "apikey",
    "auth",
    "credential",
    "password",
    "secret",
    "token",
)


@dataclass(slots=True)
class ToolExecutionInput:
    index: int
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    tool: Any
    runtime: ToolRuntimeMeta


@dataclass(slots=True)
class ToolExecutionResult:
    index: int
    message: ToolMessage
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class ToolParallelClassification:
    mode: Literal["parallel_safe", "serialized_side_effect", "serialized_runtime"]
    reason: str

    @property
    def can_run_in_parallel(self) -> bool:
        return self.mode == "parallel_safe"


def build_tool_approval_interrupt_payload(item: ToolExecutionInput) -> dict[str, Any]:
    redacted_args = redact_tool_args(item.args, item.runtime)
    interrupt_id = build_tool_approval_interrupt_id(item)
    return {
        "kind": TOOL_APPROVAL_INTERRUPT_KIND,
        "interrupt_id": interrupt_id,
        "tool_name": item.tool_name,
        "tool_call_id": item.tool_call_id,
        "args": redacted_args,
        "redacted_args": redacted_args,
        "risk_level": item.runtime.risk_level or "low",
        "policy_version": TOOL_APPROVAL_POLICY_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def build_tool_approval_interrupt_id(item: ToolExecutionInput) -> str:
    fingerprint = json.dumps(
        {
            "tool_call_id": item.tool_call_id,
            "tool_name": item.tool_name,
            "args": item.args,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"tool-approval:{item.tool_call_id}:{digest}"


def redact_tool_args(args: dict[str, Any], runtime: ToolRuntimeMeta) -> dict[str, Any]:
    sensitive_args = {
        str(item).strip()
        for item in (getattr(runtime, "sensitive_args", ()) or ())
        if str(item).strip()
    }
    policy = str(getattr(runtime, "redaction_policy", "") or "mask").strip().lower()
    if policy == "none" and not sensitive_args:
        return _copy_json_safe(args)
    return {
        str(key): _redact_arg_value(
            key=str(key),
            value=value,
            sensitive_args=sensitive_args,
            policy=policy,
        )
        for key, value in args.items()
    }


def tool_approval_response_error(
    response: Any,
    *,
    interrupt_id: str,
    tool_call_id: str,
) -> str | None:
    if not isinstance(response, dict):
        return "Tool approval response must be an object."
    kind = response.get("kind")
    if kind != TOOL_APPROVAL_INTERRUPT_KIND:
        return "Tool approval response kind is invalid."
    if response.get("interrupt_id") != interrupt_id:
        return "Tool approval response interrupt_id does not match the pending approval."
    if response.get("tool_call_id") != tool_call_id:
        return "Tool approval response tool_call_id does not match the pending approval."
    if not isinstance(response.get("approved"), bool):
        return "Tool approval response approved must be a boolean."
    return None


def is_tool_approval_approved(
    response: Any,
    *,
    interrupt_id: str | None = None,
    tool_call_id: str | None = None,
) -> bool:
    if interrupt_id is not None or tool_call_id is not None:
        if tool_approval_response_error(
            response,
            interrupt_id=interrupt_id or "",
            tool_call_id=tool_call_id or "",
        ):
            return False
    if not isinstance(response, dict):
        return False
    if response.get("kind") != TOOL_APPROVAL_INTERRUPT_KIND:
        return False
    return response.get("approved") is True


def _redact_arg_value(
    *,
    key: str,
    value: Any,
    sensitive_args: set[str],
    policy: str,
) -> Any:
    if key in sensitive_args or _key_looks_sensitive(key):
        return None if policy == "omit" else REDACTED_ARG_VALUE
    if isinstance(value, dict):
        return {
            str(nested_key): _redact_arg_value(
                key=str(nested_key),
                value=nested_value,
                sensitive_args=sensitive_args,
                policy=policy,
            )
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_arg_value(
                key=key,
                value=item,
                sensitive_args=sensitive_args,
                policy=policy,
            )
            for item in value
        ]
    return _copy_json_safe(value)


def _key_looks_sensitive(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return any(marker in normalized for marker in _COMMON_SENSITIVE_ARG_MARKERS)


def _copy_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _copy_json_safe(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_copy_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_copy_json_safe(item) for item in value]
    return value


def _approval_text_is_approved(value: str) -> bool:
    return value.strip().lower() in {
        "approve",
        "approved",
        "allow",
        "allowed",
        "yes",
        "true",
    }
