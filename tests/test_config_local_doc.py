from __future__ import annotations

from pathlib import Path

from focus_agent.config import (
    Settings,
    load_local_env_file,
    load_model_catalog_document,
    load_tool_catalog_document,
)


def test_load_local_env_file_reads_key_value_lines(tmp_path, monkeypatch):
    config_file = tmp_path / "local.env"
    config_file.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://api.deepseek.com",
                "OPENAI_API_KEY=local-secret",
                'TEMPERATURE="0.2"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TEMPERATURE", raising=False)

    env: dict[str, str] = {}
    loaded = load_local_env_file(config_file, environ=env)

    assert loaded["OPENAI_BASE_URL"] == "https://api.deepseek.com"
    assert loaded["OPENAI_API_KEY"] == "local-secret"
    assert loaded["TEMPERATURE"] == "0.2"
    assert env["TEMPERATURE"] == "0.2"


def test_load_model_catalog_document_reads_structured_model_data(tmp_path):
    config_doc = tmp_path / "models.toml"
    config_doc.write_text(
        "\n".join(
            [
                'default_model = "deepseek:deepseek-reasoner"',
                'helper_model = "openai:gpt-4.1-mini"',
                'model_choices = ["deepseek:deepseek-reasoner", "ollama:gemma4-hauhau:q8"]',
                "",
                "[[providers]]",
                'id = "deepseek"',
                'label = "DeepSeek"',
                'backend_provider = "openai"',
                'base_url_env = "DEEPSEEK_BASE_URL"',
                'api_key_env = "DEEPSEEK_API_KEY"',
                'aliases = ["ds"]',
                "",
                "[[models]]",
                'id = "deepseek:deepseek-reasoner"',
                'label = "DeepSeek Reasoner"',
                "supports_thinking = true",
                "default_thinking_enabled = true",
                'thinking_disable_switch_model = "deepseek-chat"',
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_model_catalog_document(config_doc)

    assert loaded.default_model == "deepseek:deepseek-reasoner"
    assert loaded.helper_model == "openai:gpt-4.1-mini"
    assert loaded.model_choices == ("deepseek:deepseek-reasoner", "ollama:gemma4-hauhau:q8")
    assert loaded.providers[0].id == "deepseek"
    assert loaded.providers[0].aliases == ("ds",)
    assert loaded.models[0].thinking_disable_switch_model == "deepseek-chat"


def test_load_tool_catalog_document_reads_web_search_config(tmp_path):
    config_doc = tmp_path / "tools.toml"
    config_doc.write_text(
        "\n".join(
            [
                "[list_files]",
                "enabled = false",
                'label = "Workspace Files"',
                'description = "List repository files for the current workspace."',
                "default_max_results = 12",
                "max_results_cap = 34",
                "",
                "[skills_list]",
                "enabled = false",
                "",
                "[skill_view]",
                "enabled = false",
                "",
                "[web_search]",
                "enabled = true",
                'provider = "tavily"',
                'fallback_provider = "duckduckgo"',
                'api_key_env = "SEARCH_API_KEY"',
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_tool_catalog_document(config_doc)

    assert loaded.list_files.enabled is False
    assert loaded.list_files.label == "Workspace Files"
    assert loaded.list_files.description == "List repository files for the current workspace."
    assert loaded.list_files.default_max_results == 12
    assert loaded.list_files.max_results_cap == 34
    assert loaded.skills_list.enabled is False
    assert loaded.skill_view.enabled is False
    assert loaded.web_search.enabled is True
    assert loaded.web_search.provider == "tavily"
    assert loaded.web_search.fallback_provider == "duckduckgo"
    assert loaded.web_search.api_key_env == "SEARCH_API_KEY"
    assert loaded.section_names[:4] == ("list_files", "skills_list", "skill_view", "web_search")
    assert loaded.by_name["web_search"].provider == "tavily"
    assert loaded.by_name["list_files"].default_max_results == 12


def test_settings_from_env_reads_models_from_catalog_doc(tmp_path, monkeypatch):
    config_doc = tmp_path / "models.toml"
    tools_doc = tmp_path / "tools.toml"
    config_doc.write_text(
        "\n".join(
            [
                'default_model = "openai:deepseek-reasoner"',
                'helper_model = "moonshot:kimi-k2.5"',
                'model_choices = ["openai:deepseek-reasoner", "moonshot:kimi-k2.5"]',
            ]
        ),
        encoding="utf-8",
    )
    tools_doc.write_text(
        "\n".join(
            [
                "[web_search]",
                "enabled = true",
                'provider = "duckduckgo"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FOCUS_AGENT_MODEL_CATALOG_DOC", str(config_doc))
    monkeypatch.setenv("FOCUS_AGENT_TOOL_CATALOG_DOC", str(tools_doc))
    monkeypatch.setenv("TEMPERATURE", "0.4")

    settings = Settings.from_env()

    assert settings.model == "openai:deepseek-reasoner"
    assert settings.helper_model == "moonshot:kimi-k2.5"
    assert settings.model_choices == ("openai:deepseek-reasoner", "moonshot:kimi-k2.5")
    assert settings.web_search.provider == "duckduckgo"
    assert settings.temperature == 0.4


def test_settings_from_env_prefers_explicit_model_env_over_catalog_default(tmp_path, monkeypatch):
    config_doc = tmp_path / "models.toml"
    config_doc.write_text(
        "\n".join(
            [
                'default_model = "ollama:qwen2.5:7b"',
                'helper_model = "moonshot:kimi-k2.5"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FOCUS_AGENT_MODEL_CATALOG_DOC", str(config_doc))
    monkeypatch.setenv("MODEL", "openai:gpt-4.1-mini")
    monkeypatch.setenv("HELPER_MODEL", "anthropic:claude-3-5-sonnet-latest")

    settings = Settings.from_env()

    assert settings.model == "openai:gpt-4.1-mini"
    assert settings.helper_model == "anthropic:claude-3-5-sonnet-latest"


def test_settings_from_env_reads_local_env_file_override(tmp_path, monkeypatch):
    local_env = tmp_path / "focus-agent.local.env"
    local_env.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=override-secret",
                "TEMPERATURE=0.6",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FOCUS_AGENT_LOCAL_ENV_FILE", str(local_env))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TEMPERATURE", raising=False)

    settings = Settings.from_env()

    assert settings.resolved_env["OPENAI_API_KEY"] == "override-secret"
    assert settings.temperature == 0.6


def test_settings_default_artifact_dir_stays_under_focus_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    settings = Settings.from_env()

    assert settings.artifact_dir == ".focus_agent/artifacts"
    assert (tmp_path / ".focus_agent" / "artifacts").is_dir()


def test_load_local_env_file_ignores_missing_file(tmp_path):
    missing = Path(tmp_path / "missing.env")

    assert load_local_env_file(missing) == {}


def test_settings_from_env_reads_branch_max_depth(monkeypatch):
    monkeypatch.setenv("BRANCH_MAX_DEPTH", "5")

    settings = Settings.from_env()

    assert settings.branch_max_depth == 5


def test_settings_from_env_reads_skill_directories(monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_SKILLS_DIRS", "skills,/tmp/agent-skills")

    settings = Settings.from_env()

    assert settings.skill_directories == ("skills", "/tmp/agent-skills")


def test_settings_from_env_reads_workspace_root(monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/focus-agent-workspace")

    settings = Settings.from_env()

    assert settings.workspace_root == "/tmp/focus-agent-workspace"


def test_settings_from_env_enables_trajectory_when_database_uri_exists(monkeypatch):
    monkeypatch.setenv("DATABASE_URI", "postgresql://user:pass@localhost/focus_agent")

    settings = Settings.from_env()

    assert settings.trajectory_enabled is True


def test_settings_from_env_allows_disabling_trajectory_with_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URI", "postgresql://user:pass@localhost/focus_agent")
    monkeypatch.setenv("TRAJECTORY_ENABLED", "false")
    monkeypatch.setenv("TRAJECTORY_OBSERVATION_MAX_CHARS", "123")
    monkeypatch.setenv("TRAJECTORY_ANSWER_MAX_CHARS", "456")
    monkeypatch.setenv("TRAJECTORY_HASH_USER_ID", "false")

    settings = Settings.from_env()

    assert settings.trajectory_enabled is False
    assert settings.trajectory_observation_max_chars == 123
    assert settings.trajectory_answer_max_chars == 456
    assert settings.trajectory_hash_user_id is False
