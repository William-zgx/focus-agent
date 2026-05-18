import json
from pathlib import Path

from langchain.tools import tool

from focus_agent.api.contract_models.agent import AgentSkillSelectRequest
from focus_agent.api.routers.agent_governance import _skill_selection_response
from focus_agent.capabilities.tool_manifest import StaticToolProvider
from focus_agent.capabilities.tool_registry import build_tool_registry
from focus_agent.config import (
    Settings,
    SkillInstallToolConfig,
    SkillsListToolConfig,
    SkillSourcesToolConfig,
    SkillsRefreshIndexToolConfig,
    SkillsSearchToolConfig,
    SkillViewToolConfig,
    ToolCatalogConfig,
)
from focus_agent.config_parts.catalogs import ToolProviderConfig
from focus_agent.core.types import PromptMode
from focus_agent.skills.models import SkillSourceDefinition
from focus_agent.skills.registry import (
    SkillRegistry,
    bundled_skills_dir,
    render_skill_install_json,
    render_skill_sources_json,
    render_skill_view_json,
    render_skills_list_json,
    render_skills_search_json,
)


def _write_skill(
    root,
    *,
    name: str,
    description: str,
    triggers: str = "",
    when_to_use: str = "",
    recommended_tools: str = "",
    capability_requirements: str = "",
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
    if capability_requirements:
        lines.append(f"capability_requirements: {capability_requirements}")
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


def test_skill_registry_searches_chinese_task_phrases_without_generic_skill_bias(tmp_path):
    _write_skill(
        tmp_path,
        name="release-readiness",
        description="Audit the repository against release and security checklists before a milestone.",
        when_to_use="A release is being prepared, A maintainer wants a readiness review",
    )
    _write_skill(
        tmp_path,
        name="build-fix",
        description="Triage and fix repository build, type-check, lint, or test failures.",
        when_to_use="Build or test failures need a focused repair workflow",
    )
    _write_skill(
        tmp_path,
        name="skill-manager",
        description="Manage AI agent skills and reusable skill sources.",
        when_to_use="The user asks to install or publish skills",
    )
    registry = SkillRegistry([tmp_path])

    release_results = registry.search_skills("有没有适合做发布前检查的 skill", limit=3)
    build_results = registry.search_skills("我刚接手项目，有没有能做构建失败修复的 skill", limit=3)

    assert release_results[0].skill_id == "release-readiness"
    assert "skill-manager" not in [item.skill_id for item in release_results[:1]]
    assert build_results[0].skill_id == "build-fix"


def test_skill_registry_searches_sources_and_installs_trusted_local_skill(tmp_path):
    installed_root = tmp_path / "installed"
    source_root = tmp_path / "source"
    install_root = tmp_path / "project-skills"
    _write_skill(
        source_root,
        name="agent-toolsmith",
        description="Design reusable agent tools and skills",
        triggers="toolsmith:",
        when_to_use="The task asks an agent to add common tools or discover skills",
        recommended_tools="skills_search,skill_view",
        capability_requirements="skill-discovery",
        body="# Toolsmith\nSearch sources and install relevant trusted skills.",
    )
    registry = SkillRegistry(
        [installed_root],
        source_definitions=(
            SkillSourceDefinition(
                source_id="community",
                source_type="local",
                label="Community Skills",
                enabled=True,
                trusted=True,
                location=str(source_root),
            ),
        ),
        install_dir=install_root,
    )

    results = registry.search_skills("add common tools", scope="all")
    assert results[0].skill_id == "agent-toolsmith"
    assert results[0].installed is False
    assert results[0].source_id == "community"

    installed = registry.install_skill("agent-toolsmith", source_id="community")
    assert installed.success is True
    assert installed.installed is True
    assert (install_root / "agent-toolsmith" / "SKILL.md").exists()
    assert registry.resolve("agent-toolsmith") is not None

    listed_sources = json.loads(render_skill_sources_json(registry))
    assert any(source["source_id"] == "community" for source in listed_sources["sources"])
    searched = json.loads(
        render_skills_search_json(
            registry,
            query="discover skills",
            scope="installed",
        )
    )
    assert searched["results"][0]["installed"] is True
    installed_json = json.loads(
        render_skill_install_json(
            registry,
            skill_id="agent-toolsmith",
            source_id="community",
        )
    )
    assert installed_json["success"] is True


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
    assert selection.selection_source == "prefix"
    assert selection.matched_triggers == ("plan:", "review:")


def test_skill_registry_semantic_selection_is_deterministic_fallback(tmp_path):
    _write_skill(
        tmp_path,
        name="docs",
        description="Documentation writing support",
        when_to_use="The user wants README or API docs",
        recommended_tools="read_file,write_text_artifact",
        prompt_mode="synthesize",
        body="# Documentation workflow\nDraft clear README and API reference updates.",
    )
    _write_skill(
        tmp_path,
        name="review",
        description="Code review support",
        when_to_use="The user asks for a review",
        recommended_tools="git_diff,read_file",
        prompt_mode="explore",
        body="# Review workflow\nInspect changes for regressions.",
    )

    registry = SkillRegistry([tmp_path], semantic_match_threshold=0.2)
    selection = registry.select_for_message("Please write README and API docs")

    assert selection.skill_ids == ("docs",)
    assert selection.selection_source == "semantic"
    assert selection.prompt_mode == PromptMode.SYNTHESIZE
    assert selection.semantic_candidates[0].skill_id == "docs"
    assert selection.semantic_candidates[0].auto_activate is True
    assert selection.confidence == selection.semantic_candidates[0].score


def test_skill_registry_default_threshold_activates_real_build_failure_request(tmp_path):
    _write_skill(
        tmp_path,
        name="build-fix",
        description=(
            "Triage and fix repository build, type-check, lint, or test failures "
            "using the project's real commands and verification path."
        ),
        triggers="build-fix:, fix-build:, check-fix:",
        when_to_use=(
            "make check is failing, Frontend or SDK type-checks are broken, "
            "Lint or pytest failures need a focused repair workflow"
        ),
        recommended_tools="git_status, git_diff, search_code, read_file, write_text_artifact",
        prompt_mode="execute",
        body="# Build Fix\nUse the repository's real validation commands.",
    )

    registry = SkillRegistry([tmp_path])
    selection = registry.select_for_message(
        "我这边 make check、lint、pytest 都失败了，帮我定位根因并修复。"
    )

    assert selection.skill_ids == ("build-fix",)
    assert selection.selection_source == "semantic"
    assert selection.prompt_mode == PromptMode.EXECUTE
    assert selection.semantic_candidates[0].skill_id == "build-fix"
    assert selection.semantic_candidates[0].auto_activate is True


def test_skill_registry_low_confidence_semantic_candidate_does_not_activate(tmp_path):
    _write_skill(
        tmp_path,
        name="docs",
        description="Documentation writing support",
        when_to_use="The user wants README or API docs",
        recommended_tools="read_file,write_text_artifact",
        body="# Documentation workflow",
    )

    registry = SkillRegistry([tmp_path], semantic_match_threshold=0.95)
    selection = registry.select_for_message("Please write README docs")

    assert selection.skill_ids == ()
    assert selection.selection_source == "none"
    assert selection.semantic_candidates[0].skill_id == "docs"
    assert selection.semantic_candidates[0].auto_activate is False
    assert "below threshold" in selection.rationale


def test_skill_registry_explicit_and_prefix_keep_priority_over_semantic(tmp_path):
    _write_skill(
        tmp_path,
        name="plan",
        description="Planning mode",
        triggers="plan:",
        when_to_use="The user wants a plan first",
        prompt_mode="explore",
    )
    _write_skill(
        tmp_path,
        name="docs",
        description="Documentation writing support",
        when_to_use="The user wants README or API docs",
        recommended_tools="read_file,write_text_artifact",
        prompt_mode="synthesize",
        body="# Documentation workflow",
    )

    registry = SkillRegistry([tmp_path], semantic_match_threshold=0.2)
    selection = registry.select_for_message(
        "plan: Please write README and API docs",
        explicit_hints=("docs",),
    )

    assert selection.skill_ids == ("docs", "plan")
    assert selection.selection_source == "mixed"
    assert selection.prompt_mode == PromptMode.EXPLORE
    assert selection.matched_triggers == ("plan:",)
    assert all(not candidate.auto_activate for candidate in selection.semantic_candidates)


def test_agent_skill_select_api_response_shape_uses_registry(tmp_path):
    _write_skill(
        tmp_path,
        name="docs",
        description="Documentation writing support",
        when_to_use="The user wants README or API docs",
        recommended_tools="read_file,write_text_artifact",
        prompt_mode="synthesize",
        body="# Documentation workflow",
    )
    runtime = type(
        "Runtime",
        (),
        {
            "settings": Settings(
                skill_semantic_match_enabled=True,
                skill_semantic_match_threshold=0.2,
            ),
            "skill_registry": SkillRegistry([tmp_path], semantic_match_threshold=0.2),
        },
    )()

    response = _skill_selection_response(
        payload=AgentSkillSelectRequest(message="Please write README and API docs"),
        runtime=runtime,
    )

    assert response.skill_ids == ["docs"]
    assert response.selection_source == "semantic"
    assert response.prompt_mode == "synthesize"
    assert response.semantic_candidates[0].skill_id == "docs"
    assert response.semantic_threshold == 0.2


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


def test_skill_registry_searches_sources_and_installs_local_skill_bundle(tmp_path):
    installed_root = tmp_path / "installed"
    source_root = tmp_path / "source"
    _write_skill(
        source_root,
        name="docs",
        description="Deploy docs helper",
        when_to_use="The user needs deploy docs support",
        recommended_tools="read_file,write_text_artifact",
        body="# Docs\nUse the bundled template.",
    )
    template_path = source_root / "docs" / "template.md"
    template_path.write_text("template", encoding="utf-8")
    registry = SkillRegistry(
        [installed_root],
        source_definitions=(
            SkillSourceDefinition(
                source_id="vendor",
                source_type="local",
                label="Vendor skills",
                enabled=True,
                trusted=True,
                location=str(source_root),
            ),
        ),
        install_dir=installed_root,
    )

    sources = json.loads(render_skill_sources_json(registry))
    searched = json.loads(
        render_skills_search_json(
            registry,
            query="deploy docs",
            scope="all",
            sources=("vendor",),
        )
    )
    installed = json.loads(render_skill_install_json(registry, skill_id="docs", source_id="vendor"))

    assert sources["sources"][1]["source_id"] == "vendor"
    assert searched["results"][0]["skill_id"] == "docs"
    assert searched["results"][0]["installed"] is False
    assert installed["success"] is True
    assert registry.resolve("docs") is not None
    assert (installed_root / "docs" / "template.md").read_text(encoding="utf-8") == "template"


def test_tool_registry_exposes_skill_discovery_tools(tmp_path):
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

    sources = json.loads(tool_registry.by_name["skill_sources"].invoke({}))
    searched = json.loads(
        tool_registry.by_name["skills_search"].invoke({"query": "planning", "limit": 3})
    )
    installed = json.loads(tool_registry.by_name["skill_install"].invoke({"skill_id": "plan"}))
    refreshed = json.loads(tool_registry.by_name["skills_refresh_index"].invoke({}))

    assert sources["success"] is True
    assert searched["results"][0]["skill_id"] == "plan"
    assert installed["success"] is True
    assert installed["metadata"]["already_installed"] is True
    assert refreshed["success"] is True
    assert tool_registry.runtime_by_name["skills_search"].allowed_roles == (
        "orchestrator",
        "planner",
        "skill_scout",
    )
    assert tool_registry.runtime_by_name["skill_sources"].allowed_roles == (
        "orchestrator",
        "planner",
        "skill_scout",
    )
    assert tool_registry.runtime_by_name["skills_refresh_index"].allowed_roles == (
        "planner",
        "skill_scout",
    )
    assert tool_registry.runtime_by_name["skill_install"].allowed_roles == ("skill_scout",)
    assert tool_registry.runtime_by_name["skill_install"].requires_workspace_write is True


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
                skill_sources=SkillSourcesToolConfig(enabled=False),
                skills_search=SkillsSearchToolConfig(enabled=False),
                skill_install=SkillInstallToolConfig(enabled=False),
                skills_refresh_index=SkillsRefreshIndexToolConfig(enabled=False),
                skill_view=SkillViewToolConfig(enabled=True),
            )
        ),
        skill_registry=registry,
    )

    assert "skills_list" not in tool_registry.by_name
    assert "skill_sources" not in tool_registry.by_name
    assert "skills_search" not in tool_registry.by_name
    assert "skill_install" not in tool_registry.by_name
    assert "skills_refresh_index" not in tool_registry.by_name
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
                skill_sources=SkillSourcesToolConfig(
                    label="Skill Source Catalog",
                    description="Open skill source definitions.",
                ),
            )
        ),
        skill_registry=registry,
    )

    assert tool_registry.by_name["skills_list"].description == "Browse all registered skills."
    assert tool_registry.by_name["skills_list"].metadata["display_name"] == "Skill Catalog"
    assert tool_registry.by_name["skill_view"].description == "Open one skill definition."
    assert tool_registry.by_name["skill_view"].metadata["display_name"] == "Skill Inspector"
    assert tool_registry.by_name["skill_sources"].description == "Open skill source definitions."
    assert tool_registry.by_name["skill_sources"].metadata["display_name"] == "Skill Source Catalog"


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


def test_tool_registry_rejects_enabled_unknown_provider_config(tmp_path):
    registry = SkillRegistry([tmp_path])

    try:
        build_tool_registry(
            settings=Settings(
                tool_catalog=ToolCatalogConfig(
                    providers=(ToolProviderConfig(id="unknown_tools", enabled=True),)
                )
            ),
            skill_registry=registry,
        )
    except ValueError as exc:
        assert "unknown_tools" in str(exc)
        assert "provider factory" in str(exc)
    else:
        raise AssertionError("expected enabled unknown provider validation failure")


def test_tool_registry_ignores_disabled_unknown_provider_config(tmp_path):
    registry = SkillRegistry([tmp_path])

    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                providers=(ToolProviderConfig(id="unknown_tools", enabled=False),)
            )
        ),
        skill_registry=registry,
    )

    assert "skills_list" in tool_registry.by_name
    assert "skill_view" in tool_registry.by_name


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

    monkeypatch.setattr(
        "focus_agent.capabilities.tool_registry.get_default_tools", fake_get_default_tools
    )

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


def test_tool_registry_rejects_duplicate_provider_tool_without_override(tmp_path):
    registry = SkillRegistry([tmp_path])
    first_provider = StaticToolProvider(
        provider_id="first_tools",
        tools=(_make_string_tool("shared_lookup", "first"),),
    )
    second_provider = StaticToolProvider(
        provider_id="second_tools",
        tools=(_make_string_tool("shared_lookup", "second"),),
    )

    try:
        build_tool_registry(
            settings=Settings(),
            skill_registry=registry,
            explicit_providers=(first_provider, second_provider),
        )
    except ValueError as exc:
        message = str(exc)
        assert "second_tools" in message
        assert "shared_lookup" in message
        assert "first_tools" in message
        assert "overrides" in message
    else:
        raise AssertionError("expected duplicate provider tool validation failure")


def test_tool_registry_allows_explicit_provider_tool_override(tmp_path):
    registry = SkillRegistry([tmp_path])
    first_provider = StaticToolProvider(
        provider_id="first_tools",
        tools=(_make_string_tool("shared_lookup", "first"),),
    )
    second_provider = StaticToolProvider(
        provider_id="second_tools",
        tools=(_make_string_tool("shared_lookup", "second"),),
    )

    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                providers=(ToolProviderConfig(id="second_tools", overrides=("shared_lookup",)),)
            )
        ),
        skill_registry=registry,
        explicit_providers=(first_provider, second_provider),
    )

    assert tool_registry.by_name["shared_lookup"].invoke({}) == "second"
    assert tool_registry.manifest_by_name["shared_lookup"].provider_id == "second_tools"


def test_tool_registry_skips_disabled_provider_before_duplicate_check(tmp_path):
    registry = SkillRegistry([tmp_path])
    enabled_provider = StaticToolProvider(
        provider_id="enabled_tools",
        tools=(_make_string_tool("shared_lookup", "enabled"),),
    )
    disabled_provider = StaticToolProvider(
        provider_id="disabled_tools",
        tools=(_make_string_tool("shared_lookup", "disabled"),),
    )

    tool_registry = build_tool_registry(
        settings=Settings(
            tool_catalog=ToolCatalogConfig(
                providers=(ToolProviderConfig(id="disabled_tools", enabled=False),)
            )
        ),
        skill_registry=registry,
        explicit_providers=(enabled_provider, disabled_provider),
    )

    assert tool_registry.by_name["shared_lookup"].invoke({}) == "enabled"
    assert tool_registry.manifest_by_name["shared_lookup"].provider_id == "enabled_tools"


def test_tool_registry_uses_provider_order_for_explicit_manifest_override(tmp_path):
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
                    ToolProviderConfig(
                        id="lower_tools",
                        order=300,
                        overrides=("shared_lookup",),
                    ),
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
