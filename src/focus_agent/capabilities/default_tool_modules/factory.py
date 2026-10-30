from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib import parse as urllib_parse

from ...config import Settings
from ...storage import LocalArtifactStore
from .artifact import build_artifact_tools
from .artifact_backend import ArtifactBackend
from .build_context import ToolBuildContext
from .common import (
    _apply_tool_metadata,
    _emit_tool_event,
    _make_display_event_emitter,
    build_utility_tools,
)
from .conversation import build_conversation_tools
from .git import build_git_tools
from .memory import build_memory_tools
from .productivity import build_productivity_tools
from .web import build_web_tools
from .workspace import build_workspace_tools


def get_default_tools(
    settings: Settings,
    *,
    store=None,
    checkpointer=None,
    artifact_metadata_repository=None,
    memory_repository=None,
    memory_embedding_service=None,
    retrieval_index=None,
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

    tool_display_names = {tool_name: config.label for tool_name, config in tool_configs.items()}

    _emit_display_tool_event = _make_display_event_emitter(
        base_emit_tool_event=_emit_tool_event,
        tool_display_names=tool_display_names,
    )

    grouped_tools: dict[str, Any] = {}
    grouped_runtime_metadata: dict[str, dict[str, Any]] = {}

    def _merge_tool_group(
        tools_by_name: dict[str, Any],
        runtime_metadata_by_name: dict[str, dict[str, Any]],
    ) -> None:
        grouped_tools.update(tools_by_name)
        grouped_runtime_metadata.update(runtime_metadata_by_name)

    backend = ArtifactBackend(
        artifact_dir=artifact_dir,
        artifact_store=artifact_store,
        artifact_metadata_repository=artifact_metadata_repository,
        database_uri=settings.database_uri,
    )
    context = ToolBuildContext(
        workspace_root=workspace_root,
        tool_catalog=tool_catalog,
        emit_tool_event=_emit_display_tool_event,
        memory_embedding_service=memory_embedding_service,
        retrieval_index=retrieval_index,
        save_tool_observation=backend.save_tool_observation,
    )

    _merge_tool_group(*build_utility_tools(context))
    _merge_tool_group(
        *build_workspace_tools(
            context,
            trusted_skill_collection_roots=(
                *settings.skill_directories,
                settings.skill_install_directory,
            ),
        )
    )
    _merge_tool_group(*build_git_tools(context))
    _merge_tool_group(*build_artifact_tools(context, backend=backend))
    _merge_tool_group(
        *build_web_tools(
            context,
            web_search_config=web_search_config,
            resolved_env=resolved_env,
            urllib_parse_module=urllib_parse,
        )
    )
    _merge_tool_group(
        *build_memory_tools(context, store=store, memory_repository=memory_repository)
    )
    _merge_tool_group(*build_conversation_tools(context, checkpointer=checkpointer))
    _merge_tool_group(
        *build_productivity_tools(context, productivity_repository=productivity_repository)
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
