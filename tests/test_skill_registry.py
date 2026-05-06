import json
from pathlib import Path

from langchain.tools import tool

from focus_agent.capabilities.tool_manifest import StaticToolProvider
from focus_agent.capabilities.tool_registry import build_tool_registry
from focus_agent.config import (
    Settings,
    SkillViewToolConfig,
    SkillsListToolConfig,
    ToolCatalogConfig,
)
from focus_agent.config_parts.catalogs import ToolProviderConfig
from focus_agent.core.types import PromptMode
from focus_agent.skills.registry import (
    SkillRegistry,
    bundled_skills_dir,
    render_skill_view_json,
    render_skills_list_json,
)


def _write_skill(
    root,
    *,
    name: str,
    description: str,
    triggers: str = "",
    when_to_use: str = "",
    recommended_tools: str = "",
    prompt_mode: str = "",
    body: str = "Follow the steps carefully.",
):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if triggers:
        lines.append(f"triggers: {triggers}")
    if when_to_use:
        lines.append(f"when_to_use: {when_to_use}")
    if recommended_tools:
        lines.append(f"recommended_tools: {recommended_tools}")
    if prompt_mode:
        lines.append(f"prompt_mode: {prompt_mode}")
    lines.extend(
        [
            "---",
            "",
            f"# {name}",
            "",
            body,
        ]
    )
    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")


def _make_string_tool(name: str, result: str, *, metadata: dict[str, object] | None = None):
    def _tool_impl() -> str:
        return result

    _tool_impl.__name__ = name
    _tool_impl.__doc__ = f"Return {result}."
    tool_obj = tool(_tool_impl)
    tool_obj.metadata = dict(metadata or {})
    return tool_obj


def test_skill_registry_discovers_skills_and_renders_json(tmp_path):
    _write_skill(
        tmp_path,
        name="plan",
        description="Planning mode",
        triggers="plan:",
        when_to_use="The user wants a plan first",
        recommended_tools="list_files,read_file",
        prompt_mode="explore",
    )

    registry = SkillRegistry([tmp_path])

    assert [skill.skill_id for skill in registry.all_skills()] == ["plan"]
    listed = json.loads(render_skills_list_json(registry))
    viewed = json.loads(render_skill_view_json(registry, skill_id="plan"))

    assert listed["success"] is True
    assert listed["skills"][0]["name"] == "plan"
    assert listed["skills"][0]["when_to_use"] == ["The user wants a plan first"]
    assert listed["skills"][0]["recommended_tools"] == ["list_files", "read_file"]
    assert viewed["success"] is True
    assert viewed["prompt_mode"] == "explore"
    assert viewed["when_to_use"] == ["The user wants a plan first"]
    assert viewed["recommended_tools"] == ["list_files", "read_file"]
    assert "Follow the steps carefully." in viewed["content"]


def test_skill_registry_supports_stacked_prefix_activation(tmp_path):
    _write_skill(
        tmp_path,
        name="plan",
        description="Planning mode",
        triggers="plan:",
        prompt_mode="explore",
    )
    _write_skill(
        tmp_path,
        name="review",
        description="Review mode",
        triggers="review:",
        prompt_mode="synthesize",
    )

    registry = SkillRegistry([tmp_path])
    selection = registry.select_for_message("plan: review: inspect this patch")

    assert selection.skill_ids == ("plan", "review")
    assert selection.stripped_message == "inspect this patch"
    assert selection.prompt_mode == PromptMode.SYNTHESIZE


def test_tool_registry_exposes_skill_tools(tmp_path):
    _write_skill(
        tmp_path,
        name="plan",
        description="Planning mode",
        triggers="plan:",
        when_to_use="The user wants a plan first",
        recommended_tools="list_files,read_file",
        prompt_mode="explore",
    )
    registry = SkillRegistry([tmp_path])
    tool_registry = build_tool_registry(settings=Settings(), skill_registry=registry)

    skills_list_tool = tool_registry.by_name["skills_list"]
    skill_view_tool = tool_registry.by_name["skill_view"]

    listed = json.loads(skills_list_tool.invoke({}))
    viewed = json.loads(skill_view_tool.invoke({"name": "plan"}))

    assert listed["skills"][0]["name"] == "plan"
    assert listed["skills"][0]["when_to_use"] == ["The user wants a plan first"]
    assert listed["skills"][0]["recommended_tools"] == ["list_files", "read_file"]
    assert viewed["name"] == "plan"
    assert viewed["when_to_use"] == ["The user wants a plan first"]
    assert viewed["recommended_tools"] == ["list_files", "read_file"]


def test_tool_registry_passes_artifact_metadata_repository_to_default_tools(tmp_path, monkeypatch):
    registry = SkillRegistry([tmp_path])
    captured: dict[str, object] = {}

    def fake_get_default_tools(
        settings,
        *,
        store=None,
        checkpointer=None,
        artifact_metadata_repository=None,
    ):
        captured["settings"] = settings
        captured["store"] = store
        captured["checkpointer"] = checkpointer
        captured["artifact_metadata_repository"] = artifact_metadata_repository
        return []

    monkeypatch.setattr(
        "focus_agent.capabilities.tool_registry.get_default_tools",
        fake_get_default_tools,
    )
    sentinel_repo = object()

    build_tool_registry(
        settings=Settings(),
        skill_registry=registry,
        store="store-sentinel",
        checkpointer="checkpointer-sentinel",
        artifact_metadata_repository=sentinel_repo,
    )

    assert captured["store"] == "store-sentinel"
    assert captured["checkpointer"] == "checkpointer-sentinel"
    assert captured["artifact_metadata_repository"] is sentinel_repo


def test_tool_registry_respects_skill_tool_configuration(tmp_path):
    _write_skill(
        tmp_path,
        name="plan",
        description="Planning mode",
        triggers="plan:",
        when_to_use="The user wants a plan first",
        prompt_mode="explore",
    )
    registry = SkillRegistry([tmp_path])
    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                skills_list=SkillsListToolConfig(enabled=False),
                skill_view=SkillViewToolConfig(enabled=True),
            )
        ),
        skill_registry=registry,
    )

    assert "skills_list" not in tool_registry.by_name
    assert "skill_view" in tool_registry.by_name


def test_skill_tools_use_configured_label_and_description(tmp_path):
    _write_skill(
        tmp_path,
        name="plan",
        description="Planning mode",
        triggers="plan:",
        when_to_use="The user wants a plan first",
        prompt_mode="explore",
    )
    registry = SkillRegistry([tmp_path])
    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                skills_list=SkillsListToolConfig(
                    label="Skill Catalog",
                    description="Browse all registered skills.",
                ),
                skill_view=SkillViewToolConfig(
                    label="Skill Inspector",
                    description="Open one skill definition.",
                ),
            )
        ),
        skill_registry=registry,
    )

    assert tool_registry.by_name["skills_list"].description == "Browse all registered skills."
    assert tool_registry.by_name["skills_list"].metadata["display_name"] == "Skill Catalog"
    assert tool_registry.by_name["skill_view"].description == "Open one skill definition."
    assert tool_registry.by_name["skill_view"].metadata["display_name"] == "Skill Inspector"


def test_tool_registry_uses_tool_catalog_section_order(tmp_path):
    _write_skill(
        tmp_path,
        name="plan",
        description="Planning mode",
        triggers="plan:",
        when_to_use="The user wants a plan first",
        prompt_mode="explore",
    )
    registry = SkillRegistry([tmp_path])
    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                section_order=("skills_list", "list_files", "skill_view", "web_search"),
            )
        ),
        skill_registry=registry,
    )

    ordered_names = tuple(tool.name for tool in tool_registry.tools[:4])
    assert ordered_names == ("skills_list", "list_files", "skill_view", "web_search")


def test_tool_registry_applies_manifest_metadata_overlay_to_runtime(tmp_path):
    registry = SkillRegistry([tmp_path])
    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                generic_metadata_overlays={
                    "search_code": {
                        "allowed_roles": ("critic",),
                        "intent_policies": ("workspace_lookup",),
                        "risk_level": "medium",
                    }
                }
            )
        ),
        skill_registry=registry,
    )

    runtime = tool_registry.runtime_by_name["search_code"]

    assert runtime.allowed_roles == ("critic",)
    assert runtime.intent_policies == ("workspace_lookup",)
    assert runtime.risk_level == "medium"


def test_tool_registry_accepts_explicit_provider_factories(tmp_path):
    registry = SkillRegistry([tmp_path])

    def build_local_provider(context):
        assert context.settings.workspace_root == "."
        return StaticToolProvider(
            provider_id="local_tools",
            tools=(_make_string_tool("local_lookup", "local-result"),),
        )

    tool_registry = build_tool_registry(
        settings=Settings(),
        skill_registry=registry,
        explicit_provider_factories={"local_tools": build_local_provider},
    )

    assert tool_registry.by_name["local_lookup"].invoke({}) == "local-result"
    assert tool_registry.runtime_by_name["local_lookup"].provider_id == "local_tools"


def test_tool_registry_skips_disabled_explicit_provider_factory(tmp_path):
    registry = SkillRegistry([tmp_path])
    factory_called = False

    def build_disabled_provider(context):  # noqa: ARG001
        nonlocal factory_called
        factory_called = True
        return StaticToolProvider(
            provider_id="local_tools",
            tools=(_make_string_tool("disabled_lookup", "disabled-result"),),
        )

    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                providers=(ToolProviderConfig(id="local_tools", enabled=False),)
            )
        ),
        skill_registry=registry,
        explicit_provider_factories={"local_tools": build_disabled_provider},
    )

    assert factory_called is False
    assert "disabled_lookup" not in tool_registry.by_name


def test_tool_registry_skips_disabled_builtin_provider(tmp_path, monkeypatch):
    registry = SkillRegistry([tmp_path])
    get_default_tools_called = False

    def fake_get_default_tools(settings, **kwargs):  # noqa: ARG001
        nonlocal get_default_tools_called
        get_default_tools_called = True
        return []

    monkeypatch.setattr("focus_agent.capabilities.tool_registry.get_default_tools", fake_get_default_tools)

    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                providers=(ToolProviderConfig(id="builtin", enabled=False),)
            )
        ),
        skill_registry=registry,
    )

    assert get_default_tools_called is False
    assert "skills_list" in tool_registry.by_name
    manifests = tool_registry.manifest_by_name.values()
    assert all(manifest.provider_id != "builtin" for manifest in manifests)


def test_tool_registry_uses_provider_order_for_manifest_merge(tmp_path):
    registry = SkillRegistry([tmp_path])
    lower_provider = StaticToolProvider(
        provider_id="lower_tools",
        tools=(_make_string_tool("shared_lookup", "lower"),),
    )
    higher_provider = StaticToolProvider(
        provider_id="higher_tools",
        tools=(_make_string_tool("shared_lookup", "higher"),),
    )

    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                providers=(
                    ToolProviderConfig(id="lower_tools", order=300),
                    ToolProviderConfig(id="higher_tools", order=200),
                )
            )
        ),
        skill_registry=registry,
        explicit_providers=(lower_provider, higher_provider),
    )

    assert tool_registry.by_name["shared_lookup"].invoke({}) == "lower"
    assert tool_registry.manifest_by_name["shared_lookup"].provider_id == "lower_tools"


def test_tool_registry_applies_tool_metadata_overlay_after_provider_overlay(tmp_path):
    registry = SkillRegistry([tmp_path])
    provider = StaticToolProvider(
        provider_id="local_tools",
        tools=(
            _make_string_tool(
                "overlay_lookup",
                "overlay",
                metadata={"parallel_safe": True, "risk_level": "low"},
            ),
        ),
    )

    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                providers=(
                    ToolProviderConfig(
                        id="local_tools",
                        metadata={"risk_level": "high", "toolset": "provider"},
                    ),
                ),
                generic_metadata_overlays={
                    "overlay_lookup": {"risk_level": "medium", "toolset": "tool"}
                },
            )
        ),
        skill_registry=registry,
        explicit_providers=(provider,),
    )

    runtime = tool_registry.runtime_by_name["overlay_lookup"]

    assert runtime.parallel_safe is True
    assert runtime.risk_level == "medium"
    assert runtime.toolset == "tool"


def test_bundled_registry_contains_copied_practical_skills():
    registry = SkillRegistry([bundled_skills_dir()])
    names = {item["name"] for item in registry.list_skills()}

    assert "systematic-debugging" in names
    assert "writing-plans" in names
    assert "codebase-inspection" in names
    assert "code-documentation" in names
    assert "research" in names
    assert "security-review" in names


def test_bundled_skills_use_project_ready_metadata_and_content():
    registry = SkillRegistry([bundled_skills_dir()])
    legacy_markers = (
        "search_files",
        "delegate_task",
        "/mnt/user-data/uploads",
        "~/.hermes",
        "Hermes Agent Integration",
        "For Hermes:",
    )

    for skill in registry.all_skills():
        assert skill.triggers, skill.skill_id
        assert skill.when_to_use, skill.skill_id
        assert skill.prompt_mode is not None, skill.skill_id
        for marker in legacy_markers:
            assert marker not in skill.body, (skill.skill_id, marker)


def test_optional_project_local_skills_use_project_ready_metadata():
    local_root = Path(".focus_agent/skills")
    if not local_root.exists():
        return

    registry = SkillRegistry([local_root])
    for skill in registry.all_skills():
        assert skill.triggers, skill.skill_id
        assert skill.when_to_use, skill.skill_id
        assert skill.prompt_mode is not None, skill.skill_id


def test_execution_skills_publish_recommended_focus_agent_native_tools():
    registry = SkillRegistry([bundled_skills_dir()])
    required_tools = {
        "tdd": ("list_files", "search_code", "read_file"),
        "review": ("git_status", "git_diff", "read_file"),
        "autopilot": ("list_files", "search_code", "git_diff"),
        "ralph": ("git_status", "search_code", "git_log"),
        "ultrawork": ("list_files", "search_code", "git_diff"),
    }

    for skill_id, markers in required_tools.items():
        skill = registry.resolve(skill_id)
        assert skill is not None
        for marker in markers:
            assert marker in skill.recommended_tools, (skill_id, marker, skill.recommended_tools)
