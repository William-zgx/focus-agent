from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse

from langgraph.config import get_config

from ...config import Settings
from ...storage import LocalArtifactStore
from .artifact import build_artifact_tools
from .common import _apply_tool_metadata, build_utility_tools
from .conversation import build_conversation_tools
from .git import build_git_tools
from .memory import build_memory_tools
from .productivity import build_productivity_tools
from .web import build_web_tools
from .workspace import build_workspace_tools


def _get_current_thread_id() -> str | None:
    try:
        config = get_config()
    except Exception:  # noqa: BLE001
        return None
    configurable = dict(config.get("configurable") or {})
    value = configurable.get("thread_id")
    return str(value) if value else None


def _get_current_user_id() -> str | None:
    try:
        config = get_config()
    except Exception:  # noqa: BLE001
        return None
    configurable = dict(config.get("configurable") or {})
    value = configurable.get("user_id")
    if value:
        return str(value)
    metadata = dict(config.get("metadata") or {})
    metadata_user = metadata.get("user_id")
    return str(metadata_user) if metadata_user else None


def get_default_tools(
    settings: Settings,
    *,
    store=None,
    checkpointer=None,
    artifact_metadata_repository=None,
    memory_repository=None,
    memory_embedding_service=None,
    productivity_repository=None,
    artifact_store=None,
):
    artifact_dir = Path(settings.artifact_dir).expanduser()
    if artifact_store is None:
        if settings.artifact_store_type != "local":
            raise ValueError(f"Unsupported artifact_store_type: {settings.artifact_store_type}")
        artifact_store = LocalArtifactStore(artifact_dir)
    workspace_root = Path(settings.workspace_root).expanduser().resolve()
    resolved_env = settings.resolved_env or os.environ
    tool_catalog = settings.tool_catalog
    web_search_config = settings.web_search
    tool_configs = {**tool_catalog.by_name, "web_search": web_search_config}
    _base_emit_tool_event = __getattr__("_emit_tool_event")

    tool_display_names = {tool_name: config.label for tool_name, config in tool_configs.items()}

    def _emit_tool_event(*, tool_name: str, stage: str, **payload: Any) -> None:
        display_name = tool_display_names.get(tool_name)
        if display_name:
            payload.setdefault("display_name", display_name)
        _base_emit_tool_event(tool_name=tool_name, stage=stage, **payload)

    grouped_tools: dict[str, Any] = {}
    grouped_runtime_metadata: dict[str, dict[str, Any]] = {}

    def _merge_tool_group(
        tools_by_name: dict[str, Any],
        runtime_metadata_by_name: dict[str, dict[str, Any]],
    ) -> None:
        grouped_tools.update(tools_by_name)
        grouped_runtime_metadata.update(runtime_metadata_by_name)

    _merge_tool_group(*build_utility_tools(emit_tool_event=_emit_tool_event))
    _merge_tool_group(
        *build_workspace_tools(
            workspace_root=workspace_root,
            tool_catalog=tool_catalog,
            emit_tool_event=_emit_tool_event,
        )
    )
    _merge_tool_group(
        *build_git_tools(
            workspace_root=workspace_root,
            tool_catalog=tool_catalog,
            emit_tool_event=_emit_tool_event,
        )
    )
    _merge_tool_group(
        *build_web_tools(
            web_search_config=web_search_config,
            tool_catalog=tool_catalog,
            resolved_env=resolved_env,
            emit_tool_event=_emit_tool_event,
            urllib_parse_module=urllib_parse,
        )
    )
    _merge_tool_group(
        *build_artifact_tools(
            artifact_dir=artifact_dir,
            workspace_root=workspace_root,
            settings=settings,
            tool_catalog=tool_catalog,
            artifact_store=artifact_store,
            artifact_metadata_repository=artifact_metadata_repository,
            emit_tool_event=_emit_tool_event,
            get_current_thread_id=_get_current_thread_id,
        )
    )
    _merge_tool_group(
        *build_memory_tools(
            store=store,
            memory_repository=memory_repository,
            memory_embedding_service=memory_embedding_service,
            tool_catalog=tool_catalog,
            emit_tool_event=_emit_tool_event,
            get_current_thread_id=_get_current_thread_id,
        )
    )
    _merge_tool_group(
        *build_conversation_tools(
            checkpointer=checkpointer,
            tool_catalog=tool_catalog,
            emit_tool_event=_emit_tool_event,
            get_current_thread_id=_get_current_thread_id,
        )
    )
    _merge_tool_group(
        *build_productivity_tools(
            productivity_repository=productivity_repository,
            emit_tool_event=_emit_tool_event,
            get_current_thread_id=_get_current_thread_id,
            get_current_user_id=_get_current_user_id,
        )
    )
    registered_tools = {
        **grouped_tools,
    }
    tool_runtime_metadata: dict[str, dict[str, Any]] = {
        **grouped_runtime_metadata,
    }

    tools: list[Any] = []
    for tool_name in tool_catalog.section_names:
        tool_obj = registered_tools.get(tool_name)
        if tool_obj is None:
            continue
        config = tool_configs[tool_name]
        tool_obj = _apply_tool_metadata(
            tool_obj,
            label=config.label,
            description=config.description,
            runtime=tool_runtime_metadata.get(tool_name),
        )
        if config.enabled:
            tools.append(tool_obj)

    return tools


_COMPAT_HELPER_MODULES = {
    "_emit_tool_event": ".common",
    "_coerce_relative_posix": ".common",
    "_collapse_whitespace": ".common",
    "_looks_binary": ".common",
    "_make_display_event_emitter": ".common",
    "_read_text_file": ".common",
    "_require_non_empty_text_arg": ".common",
    "_run_git_command": ".git",
    "_ReadableHTMLExtractor": ".web",
    "_is_blocked_fetch_host": ".web",
    "_normalize_search_result": ".web",
    "_TEXT_FILE_SUFFIX_TO_LANGUAGE": ".workspace",
    "_SKIP_DIR_NAMES": ".workspace",
    "_format_numbered_lines": ".workspace",
    "_iter_workspace_files": ".workspace",
    "_language_for_path": ".workspace",
    "_matches_glob_pattern": ".workspace",
    "_resolve_workspace_path": ".workspace",
}


def __getattr__(name: str) -> Any:
    module_name = _COMPAT_HELPER_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    from importlib import import_module

    return getattr(import_module(module_name, package=__package__), name)
