from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from focus_agent.core.repo_call import has_repo_method
from focus_agent.transport.stream_events import sanitize_stream_visible_text

_TOOL_RESULT_FALLBACK_VISIBLE_PREFIX = "我先根据已拿到的工具结果给出一个保守整理："


def _source_node(metadata: dict[str, Any], namespace: list[str]) -> str:
    return str(metadata.get("langgraph_node") or (namespace[-1] if namespace else "") or "harness")


def _canonical_custom_event(event: str, payload: dict[str, Any]) -> str:
    if event in {"tool.requested", "tool.result", "tool.error"}:
        if not (payload.get("tool_call_id") or payload.get("id")):
            return "state.update"
        return event
    if event in {"run.status", "state.update"}:
        return event
    return "state.update"


def _canonical_payload_extras(data: dict[str, Any]) -> dict[str, Any]:
    reserved = {"run_id", "thread_id", "turn_id", "sequence", "source_node"}
    return {key: value for key, value in data.items() if key not in reserved}


def _tool_result_is_error(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").strip().lower()
    if status in {"error", "failed"}:
        return True
    tool_outcome = item.get("tool_outcome")
    if isinstance(tool_outcome, dict):
        return str(tool_outcome.get("status") or "").strip().lower() in {
            "failed",
            "blocked",
        }
    content = str(item.get("content") or "").lower()
    return '"status": "error"' in content or '"status":"error"' in content


def _is_tool_result_fallback_visible_delta(delta: str) -> bool:
    return delta.lstrip().startswith(_TOOL_RESULT_FALLBACK_VISIBLE_PREFIX)


def _should_hide_completed_visible_text(text: str) -> bool:
    return not sanitize_stream_visible_text(text)


def _safe_completed_visible_text(text: str) -> str:
    return sanitize_stream_visible_text(text)


def _json_safe(value: Any) -> Any:
    if hasattr(value, "value") and hasattr(value, "interrupts"):
        return _json_safe(value.value)
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _run_record_payload(record: Any) -> dict[str, Any]:
    if hasattr(record, "to_dict"):
        return _json_safe(record.to_dict())
    return _json_safe(record)


def _event_store_for_runtime(runtime: Any) -> Any:
    return getattr(runtime, "event_store", None) or getattr(
        getattr(runtime, "harness", None),
        "event_store",
        None,
    )


def _journal_method(runtime: Any, name: str) -> Any:
    method = _journal_method_optional(runtime, name)
    if method is None:
        raise HTTPException(status_code=503, detail="Harness run journal is unavailable.")
    return method


def _journal_method_optional(runtime: Any, name: str) -> Any:
    event_store = _event_store_for_runtime(runtime)
    return getattr(event_store, name) if has_repo_method(event_store, name) else None


async def _get_persisted_run(runtime: Any, run_id: str) -> dict[str, Any] | None:
    get_run = _journal_method_optional(runtime, "get_run")
    if get_run is None:
        return None
    run = await get_run(run_id)
    if run is None:
        return None
    if hasattr(run, "to_dict"):
        return _json_safe(run.to_dict())
    return _json_safe(run)


__all__ = [
    "_canonical_custom_event",
    "_canonical_payload_extras",
    "_event_store_for_runtime",
    "_get_persisted_run",
    "_is_tool_result_fallback_visible_delta",
    "_journal_method",
    "_journal_method_optional",
    "_json_safe",
    "_run_record_payload",
    "_safe_completed_visible_text",
    "_should_hide_completed_visible_text",
    "_source_node",
    "_tool_result_is_error",
]
