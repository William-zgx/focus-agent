from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from focus_agent.config import ConfiguredModel, ModelCatalogConfig, ProviderConfig, Settings
from focus_agent.config_parts.agent import load_agent_config
from focus_agent.services.admin_config_fields import _POLICY_FIELD_SPECS
from focus_agent.services.agent_team import AgentTeamService
from focus_agent.services.agent_team_readiness import build_agent_team_readiness


def _settings(**overrides: object) -> Settings:
    catalog = ModelCatalogConfig(
        default_model="openai:gpt-4.1-mini",
        providers=(ProviderConfig(id="openai", api_key_env="OPENAI_API_KEY"),),
        models=(ConfiguredModel(id="openai:gpt-4.1-mini"),),
    )
    return Settings(model_catalog=catalog, **overrides)


def _blocker_codes(payload: dict[str, object]) -> set[str]:
    return {
        str(item["code"])
        for item in payload["blockers"]  # type: ignore[index]
    }


def _git(cwd, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _worktree_settings(workspace_root: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "agent_team_v2_enabled": True,
        "multi_agent_v2_enabled": True,
        "multi_agent_resource_lock_enabled": True,
        "agent_team_rollout_phase": "canary",
        "agent_team_execution_mode": "worktree_sandbox",
        "agent_delegation_execution_mode": "background",
        "agent_team_real_provider_enabled": True,
        "agent_team_durable_required": True,
        "agent_team_fencing_enabled": True,
        "agent_team_cross_session_locks_enabled": True,
        "agent_team_kill_switch_enabled": False,
        "background_job_backend": "postgres",
        "background_job_execution": "durable",
        "database_uri": "postgresql://focus-agent.test/readiness",
        "workspace_root": workspace_root,
        "resolved_env": {
            "OPENAI_API_KEY": "test-key",
            "FOCUS_AGENT_SANDBOX_BACKEND": "docker",
            "FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK": "0",
        },
    }
    values.update(overrides)
    return _settings(**values)


class _HealthyDurableWorker:
    def snapshot(self) -> dict[str, int]:
        return {
            "durable_worker_started": 1,
            "durable_worker_thread_alive": 1,
            "durable_worker_heartbeat_fresh": 1,
        }


def test_agent_team_v2_settings_are_default_closed_and_keep_delegation_unchanged() -> None:
    settings = Settings()
    values = load_agent_config({}, settings)

    assert settings.agent_delegation_execution_mode == "observe"
    assert values["agent_team_v2_enabled"] is False
    assert values["agent_team_rollout_phase"] == "off"
    assert values["agent_team_execution_mode"] == "disabled"
    assert values["agent_team_real_provider_enabled"] is False
    assert values["agent_team_durable_required"] is False
    assert values["agent_team_fencing_enabled"] is False
    assert values["agent_team_approval_resume_enabled"] is False
    assert values["agent_team_cross_session_locks_enabled"] is False
    assert values["agent_team_kill_switch_enabled"] is True
    assert values["agent_team_legacy_write_enabled"] is False
    assert values["agent_team_global_tab_enabled"] is False
    assert values["agent_team_adoption_enabled"] is False


def test_agent_team_v2_config_reads_rollout_controls_and_rejects_unknown_execution_mode() -> None:
    values = load_agent_config(
        {
            "AGENT_TEAM_V2_ENABLED": "true",
            "AGENT_TEAM_ROLLOUT_PHASE": "canary",
            "AGENT_TEAM_EXECUTION_MODE": "worktree-sandbox",
            "AGENT_TEAM_REAL_PROVIDER_ENABLED": "true",
            "AGENT_TEAM_DURABLE_REQUIRED": "true",
            "AGENT_TEAM_FENCING_ENABLED": "true",
            "AGENT_TEAM_APPROVAL_RESUME_ENABLED": "true",
            "AGENT_TEAM_CROSS_SESSION_LOCKS_ENABLED": "true",
            "AGENT_TEAM_KILL_SWITCH_ENABLED": "false",
            "AGENT_TEAM_LEGACY_WRITE_ENABLED": "true",
            "AGENT_TEAM_GLOBAL_TAB_ENABLED": "true",
            "AGENT_TEAM_ADOPTION_ENABLED": "true",
        },
        Settings(),
    )

    assert values["agent_team_v2_enabled"] is True
    assert values["agent_team_rollout_phase"] == "canary"
    assert values["agent_team_execution_mode"] == "worktree_sandbox"
    assert values["agent_team_real_provider_enabled"] is True
    assert values["agent_team_durable_required"] is True
    assert values["agent_team_fencing_enabled"] is True
    assert values["agent_team_approval_resume_enabled"] is True
    assert values["agent_team_cross_session_locks_enabled"] is True
    assert values["agent_team_kill_switch_enabled"] is False
    assert values["agent_team_legacy_write_enabled"] is True
    assert values["agent_team_global_tab_enabled"] is True
    assert values["agent_team_adoption_enabled"] is True

    with pytest.raises(ValueError, match="AGENT_TEAM_EXECUTION_MODE"):
        load_agent_config({"AGENT_TEAM_EXECUTION_MODE": "unsafe"}, Settings())


def test_agent_team_v2_controls_are_exposed_as_admin_policy_fields() -> None:
    specs = {item.key: item for item in _POLICY_FIELD_SPECS}

    assert specs["agent_team_execution_mode"].options == (
        "disabled",
        "inline",
        "background",
        "worktree_sandbox",
    )
    assert specs["agent_team_durable_required"].env_key == "AGENT_TEAM_DURABLE_REQUIRED"
    assert specs["agent_team_fencing_enabled"].env_key == "AGENT_TEAM_FENCING_ENABLED"
    assert (
        specs["agent_team_cross_session_locks_enabled"].env_key
        == "AGENT_TEAM_CROSS_SESSION_LOCKS_ENABLED"
    )
    assert specs["agent_team_kill_switch_enabled"].env_key == "AGENT_TEAM_KILL_SWITCH_ENABLED"
    assert specs["agent_team_adoption_enabled"].env_key == "AGENT_TEAM_ADOPTION_ENABLED"


def test_readiness_reports_disabled_phase_without_blocking_normal_chat() -> None:
    payload = build_agent_team_readiness(_settings())

    assert payload["phase"] == "disabled"
    assert payload["blockers"] == []
    assert payload["execution"] == {
        "configured_mode": "disabled",
        "delegation_mode": "observe",
        "real_execution_requested": False,
        "kill_switch_active": True,
        "durable_required": False,
    }
    assert payload["evidence"]["settings"]["agent_team_v2_enabled"] is False  # type: ignore[index]


def test_readiness_blocks_active_rollout_while_kill_switch_is_armed() -> None:
    payload = build_agent_team_readiness(
        _settings(
            agent_team_v2_enabled=True,
            multi_agent_v2_enabled=True,
            agent_team_rollout_phase="canary",
        )
    )

    assert payload["phase"] == "blocked"
    assert _blocker_codes(payload) == {"kill_switch_active"}
    assert payload["actions"][-1]["code"] == "release_kill_switch"  # type: ignore[index]


def test_readiness_requires_real_execution_dependencies_without_leaking_secret_values() -> None:
    secret = "postgresql://user:super-secret@example.test/focus"
    api_key = "test-provider-secret"
    payload = build_agent_team_readiness(
        _settings(
            agent_team_v2_enabled=True,
            multi_agent_v2_enabled=True,
            agent_team_rollout_phase="canary",
            agent_team_execution_mode="worktree_sandbox",
            agent_delegation_execution_mode="observe",
            database_uri=secret,
            resolved_env={
                "OPENAI_API_KEY": api_key,
                "FOCUS_AGENT_SANDBOX_BACKEND": "auto",
                "FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK": "1",
            },
        )
    )

    assert payload["phase"] == "blocked"
    assert {
        "kill_switch_active",
        "real_delegation_mode_required",
        "real_provider_not_enabled",
        "durable_execution_not_required",
        "postgres_durable_jobs_required",
        "docker_fail_closed_required",
        "fencing_not_enabled",
        "cross_session_locks_not_enabled",
        "resource_locks_not_enabled",
    }.issubset(_blocker_codes(payload))
    assert "super-secret" not in repr(payload)
    assert api_key not in repr(payload)
    assert payload["evidence"]["provider"]["credential_reference_present"] is True  # type: ignore[index]


def test_readiness_reports_ready_only_with_real_dependencies_and_postgres_runtime() -> None:
    class PostgresAgentTeamRepository:
        pass

    class PostgresResourceLockManager:
        pass

    class PostgresApprovalQueue:
        pass

    runtime = SimpleNamespace(
        agent_team_service=SimpleNamespace(repository=PostgresAgentTeamRepository()),
        durable_background_worker=_HealthyDurableWorker(),
        coordination_backend=SimpleNamespace(
            resource_locks=PostgresResourceLockManager(),
            approval_queue=PostgresApprovalQueue(),
        ),
    )
    payload = build_agent_team_readiness(
        _settings(
            agent_team_v2_enabled=True,
            multi_agent_v2_enabled=True,
            multi_agent_resource_lock_enabled=True,
            agent_team_rollout_phase="canary",
            agent_team_execution_mode="background",
            agent_delegation_execution_mode="background",
            agent_team_real_provider_enabled=True,
            agent_team_durable_required=True,
            agent_team_fencing_enabled=True,
            agent_team_cross_session_locks_enabled=True,
            agent_team_kill_switch_enabled=False,
            background_job_backend="postgres",
            background_job_execution="durable",
            database_uri="postgresql://user:password@example.test/focus",
            resolved_env={
                "OPENAI_API_KEY": "not-reported",
                "FOCUS_AGENT_SANDBOX_BACKEND": "docker",
                "FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK": "0",
            },
        ),
        runtime=runtime,
    )

    assert payload["phase"] == "ready"
    assert payload["blockers"] == []
    assert payload["evidence"]["durable"] == {  # type: ignore[index]
        "postgres_database_configured": True,
        "job_backend_postgres": True,
        "execution_durable": True,
        "runtime_checked": True,
        "postgres_repository": True,
        "durable_worker_started": True,
        "durable_worker_thread_alive": True,
        "durable_worker_heartbeat_fresh": True,
        "durable_worker_healthy": True,
    }
    assert payload["evidence"]["docker"] == {  # type: ignore[index]
        "backend_configured": True,
        "docker_backend": True,
        "local_fallback_disabled": True,
    }


def test_readiness_blocks_unsupported_approval_resume_and_legacy_writes() -> None:
    payload = build_agent_team_readiness(
        _settings(
            agent_team_v2_enabled=True,
            multi_agent_v2_enabled=True,
            agent_team_rollout_phase="shadow",
            agent_team_kill_switch_enabled=False,
            agent_team_approval_resume_enabled=True,
            agent_team_legacy_write_enabled=True,
        )
    )

    assert payload["phase"] == "blocked"
    assert _blocker_codes(payload) == {
        "approval_resume_not_available",
        "legacy_writes_enabled",
    }
    assert any(item["code"] == "use_explicit_retry" for item in payload["actions"])  # type: ignore[index]


@pytest.mark.parametrize("workspace_root", ["", "."])
def test_worktree_sandbox_readiness_rejects_unconfigured_workspace(workspace_root: str) -> None:
    payload = build_agent_team_readiness(_worktree_settings(workspace_root))

    assert payload["phase"] == "blocked"
    assert "workspace_root_not_configured" in _blocker_codes(payload)
    workspace = payload["evidence"]["workspace"]  # type: ignore[index]
    assert workspace["ready"] is False
    assert any(item["code"] == "configure_workspace" for item in payload["actions"])  # type: ignore[index]


def test_worktree_sandbox_readiness_rejects_missing_workspace(tmp_path) -> None:
    payload = build_agent_team_readiness(_worktree_settings(str(tmp_path / "missing-workspace")))

    assert payload["phase"] == "blocked"
    assert "workspace_root_missing" in _blocker_codes(payload)


def test_worktree_sandbox_readiness_requires_writable_git_workspace(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_git_workspace = tmp_path / "not-a-git-repository"
    non_git_workspace.mkdir()
    non_git_payload = build_agent_team_readiness(_worktree_settings(str(non_git_workspace)))

    assert "workspace_root_not_git_repository" in _blocker_codes(non_git_payload)

    workspace = tmp_path / "read-only-repository"
    workspace.mkdir()
    monkeypatch.setattr(
        "focus_agent.services.agent_team_readiness._is_writable_directory",
        lambda _path: False,
    )
    not_writable_payload = build_agent_team_readiness(_worktree_settings(str(workspace)))

    assert "workspace_root_not_writable" in _blocker_codes(not_writable_payload)


def test_agent_team_service_defaults_workspace_service_to_settings_workspace_root(tmp_path) -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(workspace_root=str(tmp_path)),
    )

    assert service.workspace_service.repo_root == tmp_path.resolve()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required for workspace readiness")
def test_worktree_sandbox_readiness_accepts_configured_writable_git_workspace(tmp_path) -> None:
    workspace = tmp_path / "controlled-checkout"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "focus-agent@example.test")
    _git(workspace, "config", "user.name", "Focus Agent Test")
    (workspace / "README.md").write_text("workspace\n", encoding="utf-8")
    _git(workspace, "add", "README.md")
    _git(workspace, "commit", "-m", "init")

    payload = build_agent_team_readiness(_worktree_settings(str(workspace)))

    assert payload["phase"] == "ready"
    assert payload["blockers"] == []
    assert payload["evidence"]["workspace"] == {  # type: ignore[index]
        "configured_path": str(workspace),
        "resolved_path": str(workspace.resolve()),
        "exists": True,
        "directory": True,
        "writable": True,
        "git_repository": True,
        "git_executable_available": True,
        "ready": True,
    }
