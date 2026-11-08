from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import anyio
from langchain_core.tools import StructuredTool, ToolException

from ..config_parts.catalog_config_types import MCPServerConfig
from .tool_manifest import StaticToolProvider

logger = logging.getLogger(__name__)

_MAX_TOOL_NAME_CHARS = 64
_MAX_DESCRIPTION_CHARS = 1024
_MAX_OBSERVATION_CHARS = 20000
_AsyncResultT = TypeVar("_AsyncResultT")


def _run_async(
    func: Callable[..., Awaitable[_AsyncResultT]],
    *args: Any,
) -> _AsyncResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return anyio.run(func, *args)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(anyio.run, func, *args).result()


def build_mcp_tool_provider(servers: Iterable[MCPServerConfig]) -> StaticToolProvider:
    tools: list[StructuredTool] = []
    exposed_names: set[str] = set()
    for server in servers:
        if not server.enabled:
            continue
        try:
            discovered = _run_async(_list_tools, server)
        except Exception as exc:
            logger.warning(
                "MCP server %r discovery failed (%s); skipping",
                server.name,
                type(exc).__name__,
            )
            continue
        allowed_tools = set(server.allowed_tools)
        for remote_tool in discovered:
            remote_name = str(getattr(remote_tool, "name", "") or "")
            if not remote_name or (allowed_tools and remote_name not in allowed_tools):
                continue
            exposed_name = _exposed_tool_name(server.name, remote_name)
            if exposed_name in exposed_names:
                logger.warning(
                    "MCP tool name collision on server %r; skipping duplicate tool",
                    server.name,
                )
                continue
            try:
                tools.append(_build_tool(server, remote_tool, exposed_name))
            except Exception as exc:
                logger.warning(
                    "MCP tool registration failed on server %r (%s); skipping",
                    server.name,
                    type(exc).__name__,
                )
                continue
            exposed_names.add(exposed_name)
    return StaticToolProvider(provider_id="mcp", tools=tuple(tools))


async def _list_tools(server: MCPServerConfig) -> list[Any]:
    with anyio.fail_after(server.timeout_seconds):
        async with _open_session(server) as session:
            await session.initialize()
            result = await session.list_tools()
            return list(result.tools)


def _build_tool(
    server: MCPServerConfig,
    remote_tool: Any,
    exposed_name: str,
) -> StructuredTool:
    remote_name = str(remote_tool.name)
    read_only = bool(getattr(getattr(remote_tool, "annotations", None), "readOnlyHint", False))
    description = str(
        getattr(remote_tool, "description", None)
        or f"MCP tool {remote_name} on server {server.name}."
    )[:_MAX_DESCRIPTION_CHARS]
    input_schema = getattr(remote_tool, "inputSchema", None)
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}}

    def invoke(**arguments: Any) -> str:
        return _call_tool(server, remote_name, exposed_name, arguments)

    return StructuredTool.from_function(
        invoke,
        name=exposed_name,
        description=description,
        args_schema=dict(input_schema),
        infer_schema=False,
        metadata={
            "side_effect": not read_only,
            "parallel_safe": read_only,
            "cacheable": False,
            "requires_approval": server.requires_approval,
            "risk_level": (
                "high" if server.requires_approval else ("low" if read_only else "medium")
            ),
            "timeout_seconds": server.timeout_seconds,
            "max_observation_chars": _MAX_OBSERVATION_CHARS,
            "toolset": "mcp",
            "intent_policies": ("execution",),
        },
    )


def _call_tool(
    server: MCPServerConfig,
    remote_name: str,
    exposed_name: str,
    arguments: Mapping[str, Any],
) -> str:
    try:
        return _run_async(_call_tool_async, server, remote_name, dict(arguments))
    except ToolException:
        raise
    except Exception as exc:
        raise ToolException(f"MCP tool {exposed_name!r} failed ({type(exc).__name__}).") from exc


async def _call_tool_async(
    server: MCPServerConfig,
    remote_name: str,
    arguments: dict[str, Any],
) -> str:
    with anyio.fail_after(server.timeout_seconds):
        async with _open_session(server) as session:
            await session.initialize()
            result = await session.call_tool(remote_name, arguments=arguments)
    if bool(getattr(result, "isError", False)):
        detail = _text_content(result).strip()
        message = f"MCP tool {remote_name!r} returned an error"
        if detail:
            message = f"{message}: {detail[:2000]}"
        raise ToolException(message)
    return _format_result(result)


@asynccontextmanager
async def _open_session(server: MCPServerConfig) -> AsyncIterator[Any]:
    if server.transport == "stdio":
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(
            command=str(server.command or ""),
            args=list(server.args),
            env={**server.env, **_environment_values(server.env_from)},
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                yield session
        return

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = _environment_values(server.headers_from_env)
    async with streamablehttp_client(
        str(server.url or ""),
        headers=headers,
        timeout=server.timeout_seconds,
        sse_read_timeout=server.timeout_seconds,
    ) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            yield session


def _environment_values(references: Mapping[str, str]) -> dict[str, str]:
    missing = sorted({source for source in references.values() if source not in os.environ})
    if missing:
        raise ValueError("Required MCP environment variables are not set.")
    return {target: os.environ[source] for target, source in references.items()}


def _exposed_tool_name(server_name: str, remote_name: str) -> str:
    raw_name = f"mcp__{server_name}__{remote_name}"
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw_name.lower()).strip("_")
    if len(normalized) <= _MAX_TOOL_NAME_CHARS:
        return normalized
    digest = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()[:8]
    return f"{normalized[:54].rstrip('_')}__{digest}"


def _format_result(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", None) or ():
        content_type = str(getattr(item, "type", "content"))
        if content_type == "text":
            parts.append(str(getattr(item, "text", "")))
        elif content_type in {"image", "audio"}:
            mime_type = str(getattr(item, "mimeType", "unknown"))
            parts.append(f"[MCP {content_type} content: {mime_type}]")
        elif content_type == "resource_link":
            name = str(getattr(item, "name", "resource"))
            uri = str(getattr(item, "uri", ""))
            parts.append(f"[MCP resource link: {name} <{uri}>]")
        elif content_type == "resource":
            resource = getattr(item, "resource", None)
            mime_type = str(getattr(resource, "mimeType", None) or "unknown")
            parts.append(f"[MCP embedded resource: {mime_type}]")
        else:
            parts.append(f"[MCP {content_type} content]")
    structured_content = getattr(result, "structuredContent", None)
    if structured_content is not None:
        parts.append(json.dumps(structured_content, ensure_ascii=False, default=str))
    return "\n".join(part for part in parts if part)


def _text_content(result: Any) -> str:
    return "\n".join(
        str(getattr(item, "text", ""))
        for item in getattr(result, "content", None) or ()
        if getattr(item, "type", None) == "text"
    )
