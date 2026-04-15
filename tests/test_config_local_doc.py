from __future__ import annotations

from pathlib import Path

from focus_agent.config import Settings, load_local_env_document


def test_load_local_env_document_reads_key_value_lines(tmp_path, monkeypatch):
    config_doc = tmp_path / "local-model-config.md"
    config_doc.write_text(
        "\n".join(
            [
                "# Local Model Config",
                "",
                "MODEL=openai:deepseek-reasoner",
                "OPENAI_BASE_URL=https://api.deepseek.com",
                "OPENAI_API_KEY=local-secret",
                'TEMPERATURE="0.2"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TEMPERATURE", raising=False)

    env: dict[str, str] = {}
    loaded = load_local_env_document(config_doc, environ=env)

    assert loaded["MODEL"] == "openai:deepseek-reasoner"
    assert loaded["OPENAI_BASE_URL"] == "https://api.deepseek.com"
    assert loaded["OPENAI_API_KEY"] == "local-secret"
    assert loaded["TEMPERATURE"] == "0.2"
    assert env["MODEL"] == "openai:deepseek-reasoner"
    assert env["TEMPERATURE"] == "0.2"


def test_settings_from_env_uses_local_config_doc_but_env_still_wins(tmp_path, monkeypatch):
    config_doc = tmp_path / "local-model-config.md"
    config_doc.write_text(
        "\n".join(
            [
                "MODEL=openai:deepseek-reasoner",
                "TEMPERATURE=0.4",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FOCUS_AGENT_LOCAL_CONFIG_DOC", str(config_doc))
    monkeypatch.setenv("MODEL", "openai:override-model")

    settings = Settings.from_env()

    assert settings.model == "openai:override-model"
    assert settings.temperature == 0.4


def test_load_local_env_document_ignores_missing_file(tmp_path):
    missing = Path(tmp_path / "missing.md")

    assert load_local_env_document(missing) == {}


def test_settings_from_env_reads_branch_max_depth(monkeypatch):
    monkeypatch.setenv("BRANCH_MAX_DEPTH", "5")

    settings = Settings.from_env()

    assert settings.branch_max_depth == 5


def test_settings_from_env_reads_skill_directories(monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_SKILLS_DIRS", "skills,/tmp/agent-skills")

    settings = Settings.from_env()

    assert settings.skill_directories == ("skills", "/tmp/agent-skills")


def test_settings_from_env_reads_model_choices(monkeypatch):
    monkeypatch.setenv(
        "FOCUS_AGENT_MODEL_CHOICES",
        "openai:deepseek-reasoner,moonshot:kimi-k2.5",
    )

    settings = Settings.from_env()

    assert settings.model_choices == ("openai:deepseek-reasoner", "moonshot:kimi-k2.5")


def test_settings_from_env_reads_workspace_root(monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/focus-agent-workspace")

    settings = Settings.from_env()

    assert settings.workspace_root == "/tmp/focus-agent-workspace"
