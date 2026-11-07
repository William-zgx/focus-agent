from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest
from langchain_core.tools import ToolException

from focus_agent.capabilities.mcp_tools import build_mcp_tool_provider
from focus_agent.capabilities.tool_registry import build_tool_registry
from focus_agent.config import (
    MCPServerConfig,
    ModelCatalogValidationError,
    Settings,
    ToolCatalogConfig,
    load_tool_catalog_document,
)
from focus_agent.skills import SkillRegistry

_DEMO_SERVER = Path(__file__).parent / "fixtures" / "mcp_demo_server.py"


@pytest.fixture
def mcp_sdk() -> None:
    pytest.importorskip("mcp")


def _demo_server(**overrides: object) -> MCPServerConfig:
    values: dict[str, object] = {
        "name": "demo",
        "transport": "stdio",
        "command": sys.executable,
        "args": (str(_DEMO_SERVER),),
        "timeout_seconds": 15.0,
    }
    values.update(overrides)
    return MCPServerConfig(**values)  # type: ignore[arg-type]


def _build_registry(servers: tuple[MCPServerConfig, ...]):
    return build_tool_registry(
        settings=Settings(tool_catalog=ToolCatalogConfig(mcp_servers=servers)),
        skill_registry=SkillRegistry([], enabled=False),
    )


def test_mcp_catalog_parses_servers_and_defaults(tmp_path: Path) -> None:
    catalog_path = tmp_path / "tools.toml"
    catalog_path.write_text(
        """
[[mcp_servers]]
name = "demo"
transport = "stdio"
command = "python"
args = ["server.py", "--stdio"]
env = {MODE = "test"}
env_from = {API_KEY = "DEMO_API_KEY"}
allowed_tools = ["add"]

[[mcp_servers]]
name = "remote"
transport = "streamable_http"
url = "https://mcp.example.test/mcp"
headers_from_env = {Authorization = "REMOTE_MCP_TOKEN"}
enabled = false
requires_approval = false
timeout_seconds = 12.5
""",
        encoding="utf-8",
    )

    catalog = load_tool_catalog_document(catalog_path)

    assert len(catalog.mcp_servers) == 2
    demo, remote = catalog.mcp_servers
    assert demo.command == "python"
    assert demo.args == ("server.py", "--stdio")
    assert demo.env == {"MODE": "test"}
    assert demo.env_from == {"API_KEY": "DEMO_API_KEY"}
    assert demo.allowed_tools == ("add",)
    assert demo.enabled is True
    assert demo.requires_approval is True
    assert demo.timeout_seconds == 60.0
    assert remote.url == "https://mcp.example.test/mcp"
    assert remote.headers_from_env == {"Authorization": "REMOTE_MCP_TOKEN"}
    assert remote.enabled is False
    assert remote.requires_approval is False
    assert remote.timeout_seconds == 12.5


@pytest.mark.parametrize(
    ("server_toml", "message"),
    [
        (
            'name = "Bad-Name"\ntransport = "stdio"\ncommand = "python"',
            r"mcp_servers\[0\]\.name must match",
        ),
        ('name = "demo"\ntransport = "sse"', "transport must be one of"),
        ('name = "demo"\ntransport = "stdio"', "command is required"),
        ('name = "demo"\ntransport = "streamable_http"', "url is required"),
        (
            'name = "demo"\ntransport = "stdio"\ncommand = "python"\nallowed_tools = 1',
            "allowed_tools must be an array of strings",
        ),
        (
            'name = "demo"\ntransport = "stdio"\ncommand = "python"\nallowed_tools = ["add", 1]',
            "allowed_tools must be an array of strings",
        ),
    ],
)
def test_mcp_catalog_rejects_invalid_servers(
    tmp_path: Path,
    server_toml: str,
    message: str,
) -> None:
    catalog_path = tmp_path / "tools.toml"
    catalog_path.write_text(f"[[mcp_servers]]\n{server_toml}\n", encoding="utf-8")

    with pytest.raises(ModelCatalogValidationError, match=message):
        load_tool_catalog_document(catalog_path)


def test_mcp_stdio_discovery_invocation_and_metadata(mcp_sdk: None) -> None:
    registry = _build_registry((_demo_server(),))

    add = registry.by_name["mcp__demo__add"]
    assert add.args_schema["properties"]["a"]["type"] == "integer"
    assert add.args_schema["properties"]["b"]["type"] == "integer"
    assert add.args_schema["required"] == ["a", "b"]
    runtime = registry.runtime_by_name["mcp__demo__add"]
    assert runtime.side_effect is False
    assert runtime.parallel_safe is True
    assert runtime.cacheable is False
    assert runtime.requires_approval is True
    assert runtime.risk_level == "high"
    assert runtime.provider_id == "mcp"
    assert registry.runtime_by_name["mcp__demo__fail"].side_effect is True
    assert add.invoke({"a": 1, "b": 2}) == "3"
    with pytest.raises(ToolException, match="returned an error"):
        registry.by_name["mcp__demo__fail"].invoke({})


def test_mcp_discovery_and_call_inside_running_loop(mcp_sdk: None) -> None:
    async def scenario() -> tuple[list[str], str]:
        provider = build_mcp_tool_provider((_demo_server(),))
        tools = {manifest.name: manifest.tool for manifest in provider.tool_manifests()}
        return sorted(tools), tools["mcp__demo__add"].invoke({"a": 1, "b": 2})

    tool_names, result = asyncio.run(scenario())

    assert tool_names == ["mcp__demo__add", "mcp__demo__fail"]
    assert result == "3"


def test_mcp_allowed_tools_filter(mcp_sdk: None) -> None:
    registry = _build_registry((_demo_server(allowed_tools=("add",)),))

    assert "mcp__demo__add" in registry.by_name
    assert "mcp__demo__fail" not in registry.by_name


def test_mcp_broken_server_is_skipped(
    mcp_sdk: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = MCPServerConfig(
        name="broken",
        transport="stdio",
        command="/definitely/missing/mcp-server",
        timeout_seconds=2.0,
    )
    with caplog.at_level(logging.WARNING, logger="focus_agent.capabilities.mcp_tools"):
        registry = _build_registry((broken, _demo_server()))

    assert "mcp__demo__add" in registry.by_name
    assert not any(name.startswith("mcp__broken__") for name in registry.by_name)
    assert "MCP server 'broken' discovery failed" in caplog.text
    assert broken.command not in caplog.text


def test_no_mcp_servers_leaves_registry_output_unchanged(monkeypatch) -> None:
    def unexpected_async_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("MCP discovery must not run without configured servers")

    monkeypatch.setattr("focus_agent.capabilities.mcp_tools.anyio.run", unexpected_async_run)
    registry = _build_registry(())

    assert registry.tools
    assert not any(name.startswith("mcp__") for name in registry.by_name)
    assert {manifest.provider_id for manifest in registry.manifests} <= {"builtin", "skill"}
