from __future__ import annotations

from types import SimpleNamespace

from focus_agent.config import ToolCatalogConfig, load_tool_catalog_document
from focus_agent.harness.agents.factory import _build_new_components
from focus_agent.harness.governance.permissions import PermissionAction, PermissionRequest
from focus_agent.harness.schemas import HarnessConfig
from focus_agent.services.admin_config_rendering import _render_tool_catalog_toml


def test_permission_rules_load_and_last_match_wins(tmp_path) -> None:
    path = tmp_path / "tools.toml"
    path.write_text(
        """
[[permissions.rules]]
action = "deny"
tool = "bash"
command = "rm -rf *"
reason = "destructive commands need an administrator exception"

[[permissions.rules]]
action = "allow"
tool = "bash"
command = "rm -rf /tmp/*"

[[hooks.pre_tool_use]]
command = ["python", "pre_hook.py"]

[[hooks.post_tool_use]]
matcher = "web_*"
command = ["python", "post_hook.py", "--observe"]
timeout_seconds = 2.5
""",
        encoding="utf-8",
    )

    catalog = load_tool_catalog_document(path)

    assert catalog.permissions.rules[0].reason == (
        "destructive commands need an administrator exception"
    )
    assert catalog.hooks.pre_tool_use[0].matcher == "*"
    assert catalog.hooks.pre_tool_use[0].timeout_seconds == 10.0
    assert catalog.hooks.post_tool_use[0].command == (
        "python",
        "post_hook.py",
        "--observe",
    )
    assert "permissions" not in catalog.generic_metadata_overlays
    assert "hooks" not in catalog.generic_metadata_overlays

    components = _build_new_components(
        HarnessConfig(enable_extensions=False, enable_system_agents=False),
        tool_catalog=catalog,
    )
    manager = components["permission_manager"]

    def check(command: str) -> tuple[PermissionAction, str | None]:
        return manager.check_permission(
            PermissionRequest(id="request", tool_name="bash", command=command)
        )

    assert check("rm -rf /home/demo")[0] == PermissionAction.DENY
    assert check("rm -rf /tmp/demo")[0] == PermissionAction.ALLOW
    unmentioned, _ = manager.check_permission(PermissionRequest(id="request", tool_name="lookup"))
    assert unmentioned == PermissionAction.ALLOW
    assert components["extension_registry"].get("command_hooks") is not None


def test_empty_catalog_keeps_default_allow_all(tmp_path) -> None:
    path = tmp_path / "tools.toml"
    path.write_text("", encoding="utf-8")
    catalog = load_tool_catalog_document(path)

    manager = _build_new_components(
        HarnessConfig(enable_extensions=False, enable_system_agents=False),
        tool_catalog=catalog,
    )["permission_manager"]
    action, _ = manager.check_permission(PermissionRequest(id="request", tool_name="any_tool"))

    assert action == PermissionAction.ALLOW
    assert catalog.permissions.rules == ()
    assert catalog.hooks.pre_tool_use == ()
    assert catalog.hooks.post_tool_use == ()


def test_default_components_without_catalog_keep_default_allow_all() -> None:
    manager = _build_new_components(
        HarnessConfig(enable_extensions=False, enable_system_agents=False),
        tool_catalog=ToolCatalogConfig(),
    )["permission_manager"]

    action, _ = manager.check_permission(PermissionRequest(id="request", tool_name="lookup"))

    assert action == PermissionAction.ALLOW


def test_admin_tool_rendering_preserves_server_only_governance(tmp_path) -> None:
    source = tmp_path / "source.toml"
    source.write_text(
        """
[[permissions.rules]]
action = "ask"
tool = "lookup"
reason = "confirm lookup"

[[hooks.pre_tool_use]]
matcher = "lookup"
command = ["python", "hook.py"]
timeout_seconds = 3
""",
        encoding="utf-8",
    )
    catalog = load_tool_catalog_document(source)

    rendered = _render_tool_catalog_toml(
        catalog,
        SimpleNamespace(tools=None, providers=None),
    )

    assert "[[permissions.rules]]" in rendered
    assert 'reason = "confirm lookup"' in rendered
    assert "[[hooks.pre_tool_use]]" in rendered
    assert 'command = ["python", "hook.py"]' in rendered
    rendered_path = tmp_path / "rendered.toml"
    rendered_path.write_text(rendered, encoding="utf-8")
    reloaded = load_tool_catalog_document(rendered_path)
    assert reloaded.permissions == catalog.permissions
    assert reloaded.hooks == catalog.hooks
