import json
from pathlib import Path

import pytest
from langchain.tools import tool

from focus_agent.api.contract_models.agent import AgentSkillSelectRequest
from focus_agent.api.routers.agent_governance import _skill_selection_response
from focus_agent.capabilities import skill_entrypoint_runner
from focus_agent.capabilities.sandbox_execution import SandboxExecutionResult
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

MIGRATED_BUILTIN_SKILL_PREFIX_MESSAGES = {
    "python-debugpy": "debug-python: inspect failing pytest locals",
    "node-inspect-debugger": "node-inspect: attach to a TypeScript test",
    "rest-graphql-debug": "graphql-debug: diagnose HTTP 200 errors",
    "one-three-one-rule": "one-three-one: compare three architecture options",
    "spike": "spike: validate whether this prototype can work",
}

MIGRATED_BUILTIN_SKILL_QUERIES = {
    "python-debugpy": "debug Python pdb debugpy failing test",
    "node-inspect-debugger": "node inspect breakpoint TypeScript heap snapshot",
    "rest-graphql-debug": "GraphQL API auth error request response debug",
    "one-three-one-rule": "technical decision options recommendation tradeoff",
    "spike": "feasibility prototype experiment validate approach",
}

MIGRATED_PROJECT_LOCAL_SKILLS = {
    "docker-management",
    "pinggy-tunnel",
    "fastmcp",
    "mcporter",
    "arxiv",
    "domain-intel",
    "youtube-content",
    "ocr-and-documents",
    "watchers",
    "code-wiki",
    "stocks",
    "excel-author",
    "pptx-author",
    "3-statement-model",
    "dcf-model",
    "comps-analysis",
    "lbo-model",
    "merger-model",
}

LEGACY_HERMES_MARKERS = (
    "search_files",
    "delegate_task",
    "skill_manage",
    "terminal()",
    "web_extract",
    "/mnt/user-data/uploads",
    "~/.hermes",
    ".hermes/plans",
    "Hermes Agent Integration",
    "For Hermes:",
)


def _write_skill(
    root,
    *,
    name: str,
    description: str,
    triggers: str = "",
    aliases: str = "",
    localized_triggers: str = "",
    domains: str = "",
    intents: str = "",
    when_to_use: str = "",
    primary_tools: str = "",
    recommended_tools: str = "",
    capability_requirements: str = "",
    prompt_mode: str = "",
    entrypoints: str = "",
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
    if aliases:
        lines.append(f"aliases: {aliases}")
    if localized_triggers:
        lines.append(f"localized_triggers: {localized_triggers}")
    if domains:
        lines.append(f"domains: {domains}")
    if intents:
        lines.append(f"intents: {intents}")
    if when_to_use:
        lines.append(f"when_to_use: {when_to_use}")
    if primary_tools:
        lines.append(f"primary_tools: {primary_tools}")
    if recommended_tools:
        lines.append(f"recommended_tools: {recommended_tools}")
    if capability_requirements:
        lines.append(f"capability_requirements: {capability_requirements}")
    if prompt_mode:
        lines.append(f"prompt_mode: {prompt_mode}")
    if entrypoints:
        lines.extend(entrypoints.splitlines())
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
    return skill_dir / "SKILL.md"


def _make_string_tool(name: str, result: str, *, metadata: dict[str, object] | None = None):
    def _tool_impl() -> str:
        return result

    _tool_impl.__name__ = name
    _tool_impl.__doc__ = f"Return {result}."
    tool_obj = tool(_tool_impl)
    tool_obj.metadata = dict(metadata or {})
    return tool_obj


def test_skill_registry_parses_declared_entrypoints(tmp_path):
    skill_root = tmp_path / "skills"
    _write_skill(
        skill_root,
        name="china-stock-analysis",
        description="Analyze A-share financial statements.",
        primary_tools="[run_skill_entrypoint]",
        recommended_tools="[run_skill_entrypoint, read_file]",
        prompt_mode="execute",
        entrypoints="\n".join(
            [
                "entrypoints:",
                "  analyze_a_stock:",
                '    command: ["python3", "scripts/run_analysis.py"]',
                '    dependencies: ["akshare", "pandas", "numpy"]',
                "    network: true",
                "    timeout_seconds: 300",
                "    memory_mb: 4096",
                "    output_dir_arg: --output-dir",
            ]
        ),
    )

    registry = SkillRegistry([skill_root])
    skill = registry.resolve("china-stock-analysis")

    assert skill is not None
    assert len(skill.entrypoints) == 1
    entrypoint = skill.entrypoints[0]
    assert entrypoint.name == "analyze_a_stock"
    assert entrypoint.command == ("python3", "scripts/run_analysis.py")
    assert entrypoint.dependencies == ("akshare", "pandas", "numpy")
    assert entrypoint.network is True
    assert entrypoint.timeout_seconds == 300
    assert entrypoint.memory_mb == 4096
    assert entrypoint.output_dir_arg == "--output-dir"

    viewed = json.loads(render_skill_view_json(registry, skill_id="china-stock-analysis"))
    assert viewed["entrypoints"][0]["name"] == "analyze_a_stock"
    assert viewed["entrypoints"][0]["memory_mb"] == 4096


def test_run_skill_entrypoint_runs_declared_script_in_sanitized_sandbox(
    tmp_path, monkeypatch
):
    skill_root = tmp_path / "skills"
    skill_file = _write_skill(
        skill_root,
        name="demo-skill",
        description="Run a declared demo script.",
        primary_tools="[run_skill_entrypoint]",
        recommended_tools="[run_skill_entrypoint]",
        prompt_mode="execute",
        entrypoints="\n".join(
            [
                "entrypoints:",
                "  hello:",
                '    command: ["python3", "scripts/hello.py"]',
                "    timeout_seconds: 30",
                "    output_dir_arg: --output-dir",
            ]
        ),
    )
    scripts_dir = skill_file.parent / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "hello.py").write_text(
        "\n".join(
            [
                "import argparse, json, os",
                "from pathlib import Path",
                "parser = argparse.ArgumentParser()",
                "parser.add_argument('--name')",
                "parser.add_argument('--output-dir')",
                "args = parser.parse_args()",
                "out = Path(args.output_dir)",
                "out.mkdir(parents=True, exist_ok=True)",
                "(out / 'result.txt').write_text('ok', encoding='utf-8')",
                "try:",
                "    os.symlink('/etc/passwd', out / 'leak.txt')",
                "except OSError:",
                "    pass",
                "print(json.dumps({",
                "    'name': args.name,",
                "    'output_dir': args.output_dir,",
                "    'secret': os.environ.get('SECRET_TOKEN', 'missing'),",
                "}, ensure_ascii=False))",
            ]
        ),
        encoding="utf-8",
    )
    fake_python = (
        tmp_path
        / ".focus_agent"
        / "sandboxes"
        / "demo-skill"
        / "venv"
        / "bin"
        / "python"
    )
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    monkeypatch.setenv("SECRET_TOKEN", "sk-test-secret")
    monkeypatch.setenv("FOCUS_AGENT_SANDBOX_BACKEND", "local")
    registry = SkillRegistry([skill_root])
    tools = build_tool_registry(
        settings=Settings(workspace_root=str(tmp_path)),
        skill_registry=registry,
    )

    payload = json.loads(
        tools.by_name["run_skill_entrypoint"].invoke(
            {
                "skill_id": "demo-skill",
                "entrypoint": "hello",
                "arguments": {"name": "Ada"},
            }
        )
    )

    assert payload["status"] == "completed"
    assert payload["exit_code"] == 0
    assert payload["skill_id"] == "demo-skill"
    assert payload["entrypoint"] == "hello"
    assert payload["sandbox_backend"] == "local_venv"
    assert payload["fallback_used"] is True
    assert payload["degraded_reason"] == "local_host_execution"
    assert "Ada" in payload["stdout"]
    assert "sk-test-secret" not in payload["stdout"]
    stdout_payload = json.loads(payload["stdout"])
    assert ".focus_agent/sandboxes/demo-skill/runs/" in stdout_payload["output_dir"]
    assert (
        tmp_path
        / ".focus_agent"
        / "sandboxes"
        / "demo-skill"
        / "venv"
        / ".focus-agent-venv.json"
    ).exists()
    output_paths = {item["path"] for item in payload["outputs"]}
    assert any(path.endswith("/result.txt") for path in output_paths)
    assert not any(path.endswith("/leak.txt") for path in output_paths)
    assert payload["outputs_truncated"] is False

    escape_dir = tmp_path / "outside-sandbox"
    overridden_payload = json.loads(
        tools.by_name["run_skill_entrypoint"].invoke(
            {
                "skill_id": "demo-skill",
                "entrypoint": "hello",
                "arguments": {"name": "Ada", "output_dir": str(escape_dir)},
            }
        )
    )

    overridden_stdout = json.loads(overridden_payload["stdout"])
    assert overridden_payload["status"] == "completed"
    assert overridden_stdout["output_dir"] != str(escape_dir)
    assert ".focus_agent/sandboxes/demo-skill/runs/" in overridden_stdout["output_dir"]

    with pytest.raises(ValueError, match="Unsafe skill entrypoint argument name"):
        tools.by_name["run_skill_entrypoint"].invoke(
            {
                "skill_id": "demo-skill",
                "entrypoint": "hello",
                "arguments": {"bad name": "Ada"},
            }
        )

    with pytest.raises(ValueError, match="declared entrypoint"):
        tools.by_name["run_skill_entrypoint"].invoke(
            {
                "skill_id": "demo-skill",
                "entrypoint": "missing",
                "arguments": {},
            }
        )


def test_run_skill_entrypoint_uses_unified_sandbox_service(tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    skill_file = _write_skill(
        skill_root,
        name="demo-skill",
        description="Run a declared demo script.",
        primary_tools="[run_skill_entrypoint]",
        recommended_tools="[run_skill_entrypoint]",
        prompt_mode="execute",
        entrypoints="\n".join(
            [
                "entrypoints:",
                "  hello:",
                '    command: ["python3", "scripts/hello.py"]',
                "    timeout_seconds: 30",
                "    memory_mb: 512",
                "    output_dir_arg: --output-dir",
            ]
        ),
    )
    scripts_dir = skill_file.parent / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    captured_requests = []

    class _SandboxService:
        def run(self, request):
            captured_requests.append(request)
            return SandboxExecutionResult(
                status="completed",
                command=request.command,
                cwd=request.cwd,
                exit_code=0,
                timed_out=False,
                timeout_seconds=request.timeout_seconds,
                stdout='{"result":"ok"}\n',
                stderr="",
                stdout_truncated=False,
                stderr_truncated=False,
                outputs=[
                    {
                        "path": ".focus_agent/sandboxes/runs/run-skill-1/output/summary.json",
                        "size_bytes": 2,
                    }
                ],
                outputs_truncated=False,
                duration_ms=1.0,
                sandbox_backend="docker",
                run_id="run-skill-1",
                policy={
                    "network": "none",
                    "workspace": "thread_persistent_copy",
                    "sandbox_id": "thread-thread-1",
                },
                skill_id=request.skill_id,
                entrypoint=request.entrypoint,
                memory_mb=request.memory_mb,
                sandbox_id="thread-thread-1",
                fallback_used=False,
                workspace_mode="thread_persistent_copy",
                network_policy="none",
                resource_limits={"memory_mb": request.memory_mb, "pids_limit": 512},
            )

    monkeypatch.setattr(
        skill_entrypoint_runner,
        "default_sandbox_execution_service",
        lambda **_kwargs: _SandboxService(),
    )
    monkeypatch.setattr(
        "focus_agent.capabilities.tool_registry._get_current_thread_id",
        lambda: "thread-1",
    )
    monkeypatch.setattr(
        "focus_agent.capabilities.tool_registry._get_current_branch_id",
        lambda: None,
    )
    registry = SkillRegistry([skill_root])
    tools = build_tool_registry(
        settings=Settings(workspace_root=str(tmp_path)),
        skill_registry=registry,
    )

    payload = json.loads(
        tools.by_name["run_skill_entrypoint"].invoke(
            {
                "skill_id": "demo-skill",
                "entrypoint": "hello",
                "arguments": {"name": "Ada"},
            }
        )
    )

    assert captured_requests
    request = captured_requests[0]
    assert request.command == ["python3", "scripts/hello.py", "--name", "Ada"]
    assert request.cwd == "skills/demo-skill"
    assert request.output_dir_arg == "--output-dir"
    assert request.skill_id == "demo-skill"
    assert request.entrypoint == "hello"
    assert request.allow_network is False
    assert request.memory_mb == 512
    assert request.thread_id == "thread-1"
    assert request.branch_id is None
    assert request.workspace_mode == "thread_persistent_copy"
    assert payload["sandbox_backend"] == "docker"
    assert payload["sandbox_id"] == "thread-thread-1"
    assert payload["workspace_mode"] == "thread_persistent_copy"
    assert payload["fallback_used"] is False
    assert payload["network_policy"] == "none"
    assert payload["resource_limits"] == {"memory_mb": 512, "pids_limit": 512}
    assert payload["skill_id"] == "demo-skill"
    assert payload["entrypoint"] == "hello"
    assert payload["run_id"] == "run-skill-1"
    assert payload["policy"]["workspace"] == "thread_persistent_copy"
    assert payload["policy"]["sandbox_id"] == "thread-thread-1"


def test_run_skill_entrypoint_rejects_unsafe_dependency_declarations(tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    skill_file = _write_skill(
        skill_root,
        name="demo-skill",
        description="Run a declared demo script.",
        primary_tools="[run_skill_entrypoint]",
        recommended_tools="[run_skill_entrypoint]",
        prompt_mode="execute",
        entrypoints="\n".join(
            [
                "entrypoints:",
                "  hello:",
                '    command: ["python3", "scripts/hello.py"]',
                '    dependencies: ["-r", "../requirements.txt"]',
                "    timeout_seconds: 30",
            ]
        ),
    )
    scripts_dir = skill_file.parent / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    registry = SkillRegistry([skill_root])
    monkeypatch.setattr(
        skill_entrypoint_runner,
        "default_sandbox_execution_service",
        lambda **_kwargs: pytest.fail("unsafe dependencies must not reach sandbox service"),
    )
    tools = build_tool_registry(
        settings=Settings(workspace_root=str(tmp_path)),
        skill_registry=registry,
    )

    payload = json.loads(
        tools.by_name["run_skill_entrypoint"].invoke(
            {
                "skill_id": "demo-skill",
                "entrypoint": "hello",
                "arguments": {},
            }
        )
    )

    assert payload["status"] == "dependency_error"
    assert "Unsafe skill dependency declaration" in payload["stderr"]
    assert not (tmp_path / ".focus_agent" / "sandboxes" / "demo-skill" / "venv").exists()


def test_skill_registry_discovers_skills_and_renders_json(tmp_path):
    _write_skill(
        tmp_path,
        name="plan",
        description="Planning mode",
        triggers="plan:",
        aliases="方案, planning",
        localized_triggers="计划:, 计划：",
        domains="planning, 项目管理",
        intents="implementation planning, 方案设计",
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
    assert listed["skills"][0]["aliases"] == ["方案", "planning"]
    assert listed["skills"][0]["localized_triggers"] == ["计划:", "计划："]
    assert listed["skills"][0]["domains"] == ["planning", "项目管理"]
    assert listed["skills"][0]["intents"] == ["implementation planning", "方案设计"]
    assert listed["skills"][0]["when_to_use"] == ["The user wants a plan first"]
    assert listed["skills"][0]["recommended_tools"] == ["list_files", "read_file"]
    assert viewed["success"] is True
    assert viewed["prompt_mode"] == "explore"
    assert viewed["aliases"] == ["方案", "planning"]
    assert viewed["localized_triggers"] == ["计划:", "计划："]
    assert viewed["domains"] == ["planning", "项目管理"]
    assert viewed["intents"] == ["implementation planning", "方案设计"]
    assert viewed["when_to_use"] == ["The user wants a plan first"]
    assert viewed["recommended_tools"] == ["list_files", "read_file"]
    assert "Follow the steps carefully." in viewed["content"]


def test_skill_registry_global_disable_and_reload_from_settings(tmp_path):
    skill_root = tmp_path / "skills"
    _write_skill(skill_root, name="plan", description="Planning mode", triggers="plan:")
    next_root = tmp_path / "next-skills"
    _write_skill(next_root, name="review", description="Review mode", triggers="review:")
    settings = Settings(
        skills_enabled=False,
        skill_directories=(str(skill_root),),
        skill_install_directory=str(skill_root),
    )

    registry = SkillRegistry.from_settings(settings)

    assert registry.enabled is False
    assert "plan" in {skill.skill_id for skill in registry.all_skills()}
    listed_by_name = {skill["name"]: skill for skill in registry.list_skills()}
    assert listed_by_name["plan"]["enabled"] is False
    assert registry.search_skills("planning") == ()
    assert registry.install_skill("plan").success is False
    assert registry.render_available_skills_block() == ""

    settings.skills_enabled = True
    settings.skill_directories = (str(next_root),)
    settings.skill_install_directory = str(next_root)
    settings.skill_disabled_ids = ("review",)
    result = registry.reload_from_settings(settings)

    assert result["previous_count"] >= 1
    assert result["count"] >= 1
    assert registry.enabled is True
    assert "review" in {skill.skill_id for skill in registry.all_skills()}
    listed_by_name = {skill["name"]: skill for skill in registry.list_skills()}
    assert listed_by_name["review"]["enabled"] is False
    assert "review" not in {result.skill_id for result in registry.search_skills("review")}

    settings.skill_disabled_ids = ()
    registry.reload_from_settings(settings)
    listed_by_name = {skill["name"]: skill for skill in registry.list_skills()}
    assert listed_by_name["review"]["enabled"] is True
    assert "review" in {result.skill_id for result in registry.search_skills("review")}


def test_migrated_hermes_builtin_skills_list_view_search_and_prefix_activate():
    registry = SkillRegistry([bundled_skills_dir()])
    listed = json.loads(render_skills_list_json(registry))
    listed_by_name = {skill["name"]: skill for skill in listed["skills"]}

    for skill_id, message in MIGRATED_BUILTIN_SKILL_PREFIX_MESSAGES.items():
        assert skill_id in listed_by_name
        listed_skill = listed_by_name[skill_id]
        assert listed_skill["source_id"] == "builtin"
        assert listed_skill["source_type"] == "builtin"
        assert listed_skill["triggers"]
        assert listed_skill["when_to_use"]
        assert listed_skill["recommended_tools"]
        assert listed_skill["capability_requirements"]
        assert listed_skill["prompt_mode"] is not None

        viewed = json.loads(render_skill_view_json(registry, skill_id=skill_id))
        assert viewed["success"] is True
        assert viewed["name"] == skill_id
        assert viewed["source_id"] == "builtin"
        for marker in LEGACY_HERMES_MARKERS:
            assert marker not in viewed["content"], (skill_id, marker)

        selected = registry.select_for_message(message)
        assert selected.selection_source == "prefix"
        assert selected.skill_ids == (skill_id,)

    for skill_id, query in MIGRATED_BUILTIN_SKILL_QUERIES.items():
        searched = json.loads(
            render_skills_search_json(registry, query=query, scope="installed", limit=20)
        )
        assert skill_id in {result["skill_id"] for result in searched["results"]}


def test_skill_registry_does_not_treat_hermes_nested_metadata_as_focus_metadata(tmp_path):
    skill_dir = tmp_path / "hermes-style"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: hermes-style",
                "description: Skill with Hermes-specific nested metadata.",
                "metadata:",
                "  hermes:",
                "    requires_toolsets: [terminal, browser]",
                "    related_skills: [plan]",
                "---",
                "",
                "# Hermes Style",
                "",
                "The migration must not rely on nested Hermes metadata.",
            ]
        ),
        encoding="utf-8",
    )
    registry = SkillRegistry([tmp_path])

    viewed = json.loads(render_skill_view_json(registry, skill_id="hermes-style"))

    assert viewed["success"] is True
    assert viewed["recommended_tools"] == []
    assert viewed["capability_requirements"] == []


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


def test_migrated_project_local_skills_resolve_as_project_local(tmp_path):
    for skill_id in MIGRATED_PROJECT_LOCAL_SKILLS:
        _write_skill(
            tmp_path,
            name=skill_id,
            description=f"Migrated project-local skill for {skill_id}.",
            triggers=f"{skill_id}:",
            when_to_use=f"Use when {skill_id} project-local workflow is needed",
            recommended_tools="read_file,write_text_artifact",
            capability_requirements="project-local dependency",
            prompt_mode="execute",
        )

    registry = SkillRegistry([tmp_path])

    for skill_id in MIGRATED_PROJECT_LOCAL_SKILLS:
        viewed = json.loads(render_skill_view_json(registry, skill_id=skill_id))
        assert viewed["success"] is True
        assert viewed["source_id"] == "project"
        assert viewed["source_type"] == "local"
        assert viewed["triggers"]
        assert viewed["when_to_use"]
        assert viewed["recommended_tools"]
        assert viewed["capability_requirements"]
        assert viewed["prompt_mode"] == "execute"


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


def test_skill_registry_selects_localized_prefix_triggers(tmp_path):
    _write_skill(
        tmp_path,
        name="stocks",
        description="Read-only market data lookup through Yahoo Finance",
        aliases="股票, 股价, 行情, A股",
        localized_triggers="股票:, 股票：, 行情:",
        when_to_use="Use when users ask for stock quotes and ticker history",
        prompt_mode="execute",
    )

    registry = SkillRegistry([tmp_path])
    selection = registry.select_for_message("股票：看一下南网能源本周活动情况")

    assert selection.skill_ids == ("stocks",)
    assert selection.stripped_message == "看一下南网能源本周活动情况"
    assert selection.selection_source == "prefix"
    assert selection.matched_triggers == ("股票：",)
    assert selection.prompt_mode == PromptMode.EXECUTE


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


def test_skill_registry_semantic_selection_uses_cjk_aliases(tmp_path):
    _write_skill(
        tmp_path,
        name="stocks",
        description="Fetch read-only stock quotes, ticker search, and OHLCV history",
        aliases="股票, 股价, 行情, A股, 证券, ticker, quote",
        domains="finance, market-data, 股票",
        intents="quote lookup, historical OHLCV, 行情查询, 股价查询",
        when_to_use="Use when the user asks for current stock prices or ticker lookup",
        recommended_tools="run_workspace_command,web_search",
        prompt_mode="execute",
    )

    registry = SkillRegistry([tmp_path], semantic_match_threshold=0.2)
    selection = registry.select_for_message(
        "使用股票相关的Skill看一下本周南网能源的活动情况。"
    )

    assert selection.skill_ids == ("stocks",)
    assert selection.selection_source == "semantic"
    assert selection.prompt_mode == PromptMode.EXECUTE
    assert selection.semantic_candidates[0].skill_id == "stocks"
    assert "股票" in selection.semantic_candidates[0].matched_terms


def test_skills_search_matches_cjk_aliases(tmp_path):
    _write_skill(
        tmp_path,
        name="stocks",
        description="Fetch read-only stock quotes through Yahoo Finance",
        aliases="股票, 股价, 行情, A股",
        domains="finance, market-data",
        intents="行情查询, 股价查询",
        when_to_use="Use when the user asks for current stock prices",
        recommended_tools="run_workspace_command,web_search",
    )

    registry = SkillRegistry([tmp_path], semantic_match_threshold=0.2)
    payload = json.loads(
        render_skills_search_json(registry, query="股票相关能力", scope="installed")
    )

    assert payload["results"][0]["skill_id"] == "stocks"
    assert payload["results"][0]["aliases"] == ["股票", "股价", "行情", "A股"]
    assert payload["results"][0]["domains"] == ["finance", "market-data"]
    assert payload["results"][0]["intents"] == ["行情查询", "股价查询"]


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


def test_skill_registry_rejects_untrusted_local_skill_source(tmp_path):
    installed_root = tmp_path / "installed"
    source_root = tmp_path / "source"
    _write_skill(
        source_root,
        name="risky-skill",
        description="Untrusted local source skill.",
        body="# Risky\nDo not install without review.",
    )
    registry = SkillRegistry(
        [installed_root],
        source_definitions=(
            SkillSourceDefinition(
                source_id="community",
                source_type="local",
                label="Community skills",
                enabled=True,
                trusted=False,
                location=str(source_root),
            ),
        ),
        install_dir=installed_root,
    )

    installed = json.loads(
        render_skill_install_json(registry, skill_id="risky-skill", source_id="community")
    )

    assert installed["success"] is False
    assert installed["requires_review"] is True
    assert installed["metadata"]["trusted"] is False
    assert registry.resolve("risky-skill") is None


def test_skill_registry_rejects_unsafe_external_skill_ids_and_hidden_sources(tmp_path):
    installed_root = tmp_path / "installed"
    source_root = tmp_path / "source"
    unsafe_dir = source_root / "unsafe"
    unsafe_dir.mkdir(parents=True)
    (unsafe_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: ../escape",
                "description: Path traversal skill should be ignored.",
                "---",
                "",
                "# Unsafe",
            ]
        ),
        encoding="utf-8",
    )
    hidden_dir = source_root / ".hidden" / "hidden-skill"
    hidden_dir.mkdir(parents=True)
    (hidden_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: hidden-skill",
                "description: Hidden source skill should be ignored.",
                "---",
                "",
                "# Hidden",
            ]
        ),
        encoding="utf-8",
    )
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

    searched = json.loads(
        render_skills_search_json(registry, query="skill", scope="all", sources=("vendor",))
    )
    unsafe_install = json.loads(
        render_skill_install_json(registry, skill_id="../escape", source_id="vendor")
    )
    slash_install = json.loads(
        render_skill_install_json(registry, skill_id="nested/skill", source_id="vendor")
    )

    assert searched["results"] == []
    assert unsafe_install["success"] is False
    assert slash_install["success"] is False
    assert "path separators" in unsafe_install["error"]
    assert "path separators" in slash_install["error"]


def test_skill_registry_requires_trusted_local_sources_for_install(tmp_path):
    installed_root = tmp_path / "installed"
    source_root = tmp_path / "source"
    _write_skill(
        source_root,
        name="remote-skill",
        description="Remote source skill.",
    )

    for source_type in ("git", "http", "ai-skills"):
        registry = SkillRegistry(
            [installed_root],
            source_definitions=(
                SkillSourceDefinition(
                    source_id=source_type,
                    source_type=source_type,
                    label=source_type,
                    enabled=True,
                    trusted=True,
                    location=str(source_root),
                ),
            ),
            install_dir=installed_root,
        )

        installed = json.loads(
            render_skill_install_json(
                registry,
                skill_id="remote-skill",
                source_id=source_type,
            )
        )

        assert installed["success"] is False
        assert installed["requires_review"] is True
        assert installed["metadata"]["source_type"] == source_type


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

    for skill in registry.all_skills():
        assert skill.triggers, skill.skill_id
        assert skill.when_to_use, skill.skill_id
        assert skill.prompt_mode is not None, skill.skill_id
        for marker in LEGACY_HERMES_MARKERS:
            assert marker not in skill.body, (skill.skill_id, marker)


def test_optional_project_local_skills_use_project_ready_metadata():
    local_root = Path(".focus_agent/skills")
    if not local_root.exists():
        return

    registry = SkillRegistry([local_root])
    found_migrated = {skill.skill_id for skill in registry.all_skills()} & MIGRATED_PROJECT_LOCAL_SKILLS
    for skill in registry.all_skills():
        assert skill.triggers, skill.skill_id
        assert skill.when_to_use, skill.skill_id
        assert skill.prompt_mode is not None, skill.skill_id
        if skill.skill_id in MIGRATED_PROJECT_LOCAL_SKILLS:
            assert skill.source_id == "project"
            assert skill.source_type == "local"
            assert skill.recommended_tools, skill.skill_id
            assert skill.capability_requirements, skill.skill_id
            for marker in LEGACY_HERMES_MARKERS:
                assert marker not in skill.body, (skill.skill_id, marker)
    if found_migrated:
        assert found_migrated == MIGRATED_PROJECT_LOCAL_SKILLS


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
