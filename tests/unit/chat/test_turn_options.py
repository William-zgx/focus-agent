from .support import (
    AIMessage,
    ConfiguredModel,
    ModelCatalogConfig,
    Path,
    RecordingGraph,
    Settings,
    SimpleNamespace,
    SkillRegistry,
    SQLiteBranchRepository,
)


def test_send_message_activates_skills_from_prefix(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    skill_dir = tmp_path / "skills"
    plan_dir = skill_dir / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: plan",
                "description: Planning mode",
                "triggers: plan:",
                "prompt_mode: explore",
                "---",
                "",
                "# Plan",
                "",
                "Plan first.",
            ]
        ),
        encoding="utf-8",
    )

    graph = RecordingGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        skill_registry=SkillRegistry([skill_dir]),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="plan: map the rollout",
        model="moonshot:kimi-k2.6",
        thinking_mode="disabled",
    )

    assert graph.last_context.skill_hints == ("plan",)
    assert graph.last_payload["task_brief"] == "map the rollout"
    assert graph.last_payload["active_skill_ids"] == ["plan"]
    assert graph.last_payload["selected_model"] == "moonshot:kimi-k2.6"
    assert graph.last_payload["selected_thinking_mode"] == "disabled"
    assert payload["active_skill_ids"] == ["plan"]
    assert payload["selected_model"] == "moonshot:kimi-k2.6"
    assert payload["selected_thinking_mode"] == "disabled"


def test_send_message_exposes_active_skill_metadata_per_turn(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    skill_dir = tmp_path / "skills"
    plan_dir = skill_dir / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: plan",
                "description: Planning mode",
                "triggers: plan:",
                "recommended_tools: search_code, run_workspace_command",
                "prompt_mode: explore",
                "---",
                "",
                "# Plan",
                "",
                "Plan first.",
            ]
        ),
        encoding="utf-8",
    )

    class TurnMessageGraph:
        def __init__(self):
            self.values: dict[str, object] = {}
            self.last_payload = None

        def invoke(self, payload, *, config, context, version):
            del config, context, version
            self.last_payload = payload
            self.values = {
                "messages": [*list(payload["messages"]), AIMessage(content="planned")],
                "active_skill_ids": list(payload.get("active_skill_ids", [])),
                "selected_model": payload.get("selected_model", ""),
                "selected_thinking_mode": payload.get("selected_thinking_mode", ""),
            }
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

        def update_state(self, _config, values, as_node=None):
            del _config, as_node
            self.values = {**self.values, **dict(values)}

    graph = TurnMessageGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        skill_registry=SkillRegistry([skill_dir]),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="plan: map the rollout",
    )

    assert graph.last_payload["messages"][0].response_metadata["focus_agent"][
        "active_skill_ids"
    ] == ["plan"]
    assert payload["active_skill_ids"] == ["plan"]
    assert payload["active_skills"][0]["skill_id"] == "plan"
    assert payload["active_skills"][0]["description"] == "Planning mode"
    assert payload["active_skills"][0]["recommended_tools"] == [
        "search_code",
        "run_workspace_command",
    ]
    human_message = payload["messages"][0]
    assert human_message["type"] == "human"
    assert human_message["metadata"]["active_skill_ids"] == ["plan"]
    assert human_message["metadata"]["active_skills"][0]["skill_id"] == "plan"
    assert human_message["metadata"]["skill_selection"]["prompt_mode"] == "explore"


def test_send_message_preserves_thread_active_skill_without_new_trigger(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    skill_dir = tmp_path / "skills"
    stocks_dir = skill_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    (stocks_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: stocks",
                "description: Fetch read-only stock market data.",
                "aliases: [股票, 行情, A股]",
                "recommended_tools: [run_workspace_command, web_search]",
                "prompt_mode: execute",
                "---",
                "",
                "# Stocks",
                "",
                "Use this skill for stock market data.",
            ]
        ),
        encoding="utf-8",
    )

    class ActiveSkillGraph:
        def __init__(self):
            self.values: dict[str, object] = {
                "messages": [],
                "active_skill_ids": ["stocks"],
            }
            self.last_payload = None
            self.last_context = None

        def invoke(self, payload, *, config, context, version):
            del config, version
            self.last_payload = payload
            self.last_context = context
            self.values = {
                **self.values,
                "messages": [*list(payload["messages"]), AIMessage(content="done")],
                "active_skill_ids": list(payload.get("active_skill_ids", [])),
            }
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

        def update_state(self, _config, values, as_node=None):
            del _config, as_node
            self.values = {**self.values, **dict(values)}

    graph = ActiveSkillGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        skill_registry=SkillRegistry([skill_dir], semantic_match_enabled=False),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="华钰矿业近一周表现",
    )

    assert graph.last_payload["active_skill_ids"] == ["stocks"]
    assert graph.last_context.skill_hints == ("stocks",)
    assert payload["active_skill_ids"] == ["stocks"]
    assert payload["active_skills"][0]["skill_id"] == "stocks"
    human_message = payload["messages"][0]
    assert human_message["metadata"]["active_skill_ids"] == ["stocks"]
    assert human_message["metadata"]["skill_selection"]["selection_source"] == "none"


def test_send_message_explicit_skill_name_overrides_thread_active_skill(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    skill_dir = tmp_path / "skills"
    stocks_dir = skill_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    (stocks_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: stocks",
                "description: Fetch stock market data.",
                "aliases: [股票, A股]",
                "primary_tools: [run_workspace_command]",
                "prompt_mode: execute",
                "---",
                "# Stocks",
            ]
        ),
        encoding="utf-8",
    )
    china_dir = skill_dir / "china-stock-analysis"
    china_dir.mkdir(parents=True, exist_ok=True)
    (china_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: china-stock-analysis",
                "description: Analyze China A-share financial statements.",
                "aliases: [A股分析, 财报分析]",
                "primary_tools: [run_skill_entrypoint]",
                "prompt_mode: execute",
                "---",
                "# China Stock Analysis",
            ]
        ),
        encoding="utf-8",
    )

    class ActiveSkillGraph:
        def __init__(self):
            self.values: dict[str, object] = {
                "messages": [],
                "active_skill_ids": ["stocks"],
            }
            self.last_payload = None
            self.last_context = None

        def invoke(self, payload, *, config, context, version):
            del config, version
            self.last_payload = payload
            self.last_context = context
            self.values = {
                **self.values,
                "messages": [*list(payload["messages"]), AIMessage(content="done")],
                "active_skill_ids": list(payload.get("active_skill_ids", [])),
            }
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

        def update_state(self, _config, values, as_node=None):
            del _config, as_node
            self.values = {**self.values, **dict(values)}

    graph = ActiveSkillGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        skill_registry=SkillRegistry([skill_dir], semantic_match_enabled=False),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="调用china-stock-analysis技能（本地路径：.focus_agent/skills/china-stock-analysis/SKILL.md）分析中兴通讯",
    )

    assert graph.last_payload["active_skill_ids"] == ["china-stock-analysis"]
    assert graph.last_context.skill_hints == ("china-stock-analysis",)
    assert payload["active_skill_ids"] == ["china-stock-analysis"]
    human_message = payload["messages"][0]
    assert human_message["metadata"]["skill_selection"]["selection_source"] == "explicit"


def test_send_message_semantically_activates_build_fix_for_real_failure_request(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    skill_dir = tmp_path / "skills"
    build_fix_dir = skill_dir / "build-fix"
    build_fix_dir.mkdir(parents=True, exist_ok=True)
    (build_fix_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: build-fix",
                (
                    "description: Triage and fix repository build, type-check, lint, "
                    "or test failures using the project's real commands and verification path."
                ),
                "triggers: build-fix:, fix-build:, check-fix:",
                (
                    "when_to_use: make check is failing, Frontend or SDK type-checks are broken, "
                    "Lint or pytest failures need a focused repair workflow"
                ),
                "recommended_tools: git_status, git_diff, search_code, read_file, write_text_artifact",
                "prompt_mode: execute",
                "---",
                "",
                "# Build Fix",
                "",
                "Use the repository's real validation commands.",
            ]
        ),
        encoding="utf-8",
    )

    graph = RecordingGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        skill_registry=SkillRegistry([skill_dir]),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="我这边 make check、lint、pytest 都失败了，帮我定位根因并修复。",
        model="moonshot:kimi-k2.6",
        thinking_mode="disabled",
    )

    assert graph.last_context.skill_hints == ("build-fix",)
    assert graph.last_payload["active_skill_ids"] == ["build-fix"]
    assert graph.last_payload["prompt_mode"] == "execute"
    assert payload["active_skill_ids"] == ["build-fix"]


def test_send_message_ignores_thinking_mode_for_models_without_thinking_support(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    graph = RecordingGraph()
    runtime = SimpleNamespace(
        settings=Settings(
            model="ollama:gemma4-hauhau:q8",
            model_catalog=ModelCatalogConfig(
                models=(
                    ConfiguredModel(
                        id="ollama:gemma4-hauhau:q8",
                        label="gemma4-hauhau:q8",
                    ),
                ),
            ),
        ),
        graph=graph,
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="hello",
        model="ollama:gemma4-hauhau:q8",
        thinking_mode="enabled",
    )

    assert graph.last_payload["selected_model"] == "ollama:gemma4-hauhau:q8"
    assert graph.last_payload["selected_thinking_mode"] == ""
    assert payload["selected_model"] == "ollama:gemma4-hauhau:q8"
    assert payload["selected_thinking_mode"] == ""


def test_send_message_uses_runtime_model_catalog_for_custom_thinking_model(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    graph = RecordingGraph()
    runtime = SimpleNamespace(
        settings=Settings(
            model="openai:custom-reasoning-pro",
            model_catalog=ModelCatalogConfig(
                models=(
                    ConfiguredModel(
                        id="openai:custom-reasoning-pro",
                        label="Custom Reasoning Pro",
                        supports_thinking=True,
                        default_thinking_enabled=True,
                    ),
                ),
            ),
        ),
        graph=graph,
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="hello",
        model="openai:custom-reasoning-pro",
    )

    assert graph.last_payload["selected_model"] == "openai:custom-reasoning-pro"
    assert graph.last_payload["selected_thinking_mode"] == "enabled"
    assert payload["selected_model"] == "openai:custom-reasoning-pro"
    assert payload["selected_thinking_mode"] == "enabled"
