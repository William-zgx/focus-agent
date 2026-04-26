from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from langchain.tools import tool
from langgraph.config import get_config, get_stream_writer


def _emit_tool_event(*, tool_name: str, stage: str, **payload: Any) -> None:
    try:
        writer = get_stream_writer()
    except Exception:  # noqa: BLE001
        return
    writer(
        {
            "event": "tool",
            "tool_name": tool_name,
            "stage": stage,
            **payload,
        }
    )


def _get_current_thread_id() -> str | None:
    try:
        config = get_config()
    except Exception:  # noqa: BLE001
        return None
    configurable = dict(config.get("configurable") or {})
    value = configurable.get("thread_id")
    return str(value) if value else None


def _coerce_relative_posix(path: Path, workspace_root: Path) -> str:
    try:
        relative = path.relative_to(workspace_root)
    except ValueError:
        return str(path)
    rendered = relative.as_posix()
    return rendered or "."


def _looks_binary(chunk: bytes) -> bool:
    return b"\x00" in chunk


def _read_text_file(path: Path) -> str:
    with path.open("rb") as handle:
        chunk = handle.read(4096)
        if _looks_binary(chunk):
            raise ValueError(f"Refusing to read binary file: {path.name}")
        remainder = handle.read()
    return (chunk + remainder).decode("utf-8", errors="replace")


def _collapse_whitespace(value: str) -> str:
    lines = [line.strip() for line in value.splitlines()]
    normalized = [" ".join(line.split()) for line in lines]
    return "\n".join(line for line in normalized if line)


def _require_non_empty_text_arg(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must not be empty.")
    return value.strip()


def _make_display_event_emitter(
    *,
    base_emit_tool_event: Callable[..., None],
    tool_display_names: dict[str, str],
) -> Callable[..., None]:
    def _emit_with_display_name(*, tool_name: str, stage: str, **payload: Any) -> None:
        display_name = tool_display_names.get(tool_name)
        if display_name:
            payload.setdefault("display_name", display_name)
        base_emit_tool_event(tool_name=tool_name, stage=stage, **payload)

    return _emit_with_display_name


def _apply_tool_metadata(
    tool_obj: Any,
    *,
    label: str,
    description: str,
    runtime: dict[str, Any] | None = None,
) -> Any:
    tool_obj.description = description
    merged_runtime = dict(runtime or {})
    if hasattr(tool_obj, "metadata") and isinstance(getattr(tool_obj, "metadata"), dict):
        tool_obj.metadata = {**tool_obj.metadata, "display_name": label, **merged_runtime}
    else:
        tool_obj.metadata = {"display_name": label, **merged_runtime}
    return tool_obj


def build_utility_tools(
    *,
    emit_tool_event: Callable[..., None],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    @tool
    def current_utc_time() -> str:
        """Return the current UTC timestamp in ISO-8601 format."""
        tool_name = "current_utc_time"
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            value = datetime.now(timezone.utc).isoformat()
            emit_tool_event(tool_name=tool_name, stage="end", output=value)
            return value
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    return (
        {"current_utc_time": current_utc_time},
        {
            "current_utc_time": {
                "parallel_safe": True,
                "max_observation_chars": 256,
            },
        },
    )
