"""Read-only readiness assessment for the guarded Agent Team v2 rollout."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_REAL_EXECUTION_MODES = frozenset({"inline", "background", "worktree_sandbox", "real"})
_REAL_DELEGATION_MODES = frozenset({"inline", "background"})


class AgentTeamReadinessService:
    """Describe whether Agent Team v2 can safely enter its configured phase."""

    def __init__(
        self,
        settings: Any,
        *,
        runtime: Any | None = None,
        environment: Mapping[str, object] | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = runtime
        source_environment = (
            environment if environment is not None else getattr(settings, "resolved_env", {})
        )
        self._environment = _environment_controls(source_environment)
        self._environment_keys = _environment_keys(source_environment)

    def assess(self) -> dict[str, object]:
        settings = self._settings
        rollout_phase = _rollout_phase(getattr(settings, "agent_team_rollout_phase", "off"))
        execution_mode = _execution_mode(getattr(settings, "agent_team_execution_mode", "disabled"))
        delegation_mode = (
            str(getattr(settings, "agent_delegation_execution_mode", "observe") or "observe")
            .strip()
            .lower()
        )
        v2_enabled = bool(getattr(settings, "agent_team_v2_enabled", False))
        coordination_enabled = bool(getattr(settings, "multi_agent_v2_enabled", False))
        kill_switch_active = bool(getattr(settings, "agent_team_kill_switch_enabled", True))
        real_execution_requested = execution_mode in _REAL_EXECUTION_MODES
        provider = _provider_evidence(settings, self._environment_keys)
        durable = _durable_evidence(settings, self._runtime)
        docker = _docker_evidence(self._environment)
        coordination = _coordination_evidence(self._runtime)
        workspace = _workspace_evidence(settings) if execution_mode == "worktree_sandbox" else None
        blockers: list[dict[str, str]] = []
        actions: list[dict[str, str]] = []

        if not v2_enabled:
            actions.append(
                _action(
                    "enable_v2",
                    "Set AGENT_TEAM_V2_ENABLED=true only after reviewing this readiness result.",
                )
            )
        if not coordination_enabled:
            actions.append(
                _action(
                    "enable_coordination",
                    "Set MULTI_AGENT_V2_ENABLED=true before enabling v2 coordination features.",
                )
            )
        if rollout_phase == "off":
            actions.append(
                _action(
                    "select_rollout_phase",
                    "Choose shadow or canary before requesting Agent Team execution.",
                )
            )
        if execution_mode == "disabled":
            actions.append(
                _action(
                    "keep_execution_disabled",
                    "Execution remains disabled; normal chat and existing Agent Team behavior are unchanged.",
                )
            )

        active_rollout = v2_enabled and coordination_enabled and rollout_phase != "off"
        if active_rollout and kill_switch_active:
            blockers.append(
                _blocker(
                    "kill_switch_active",
                    "Agent Team v2 execution is stopped by AGENT_TEAM_KILL_SWITCH_ENABLED.",
                )
            )
            actions.append(
                _action(
                    "release_kill_switch",
                    "Set AGENT_TEAM_KILL_SWITCH_ENABLED=false only for an approved rollout.",
                )
            )

        if real_execution_requested:
            _add_real_execution_requirements(
                blockers=blockers,
                actions=actions,
                settings=settings,
                delegation_mode=delegation_mode,
                provider=provider,
                durable=durable,
                docker=docker,
                coordination=coordination,
            )
        if workspace is not None:
            _add_worktree_workspace_requirements(
                blockers=blockers,
                actions=actions,
                workspace=workspace,
            )

        if bool(getattr(settings, "agent_team_legacy_write_enabled", False)):
            blockers.append(
                _blocker(
                    "legacy_writes_enabled",
                    "Legacy Agent Team writes must stay disabled during the v2 rollout.",
                )
            )
        if bool(getattr(settings, "agent_team_approval_resume_enabled", False)):
            blockers.append(
                _blocker(
                    "approval_resume_not_available",
                    "Approval decisions do not automatically resume completed Agent Team runs.",
                )
            )
            actions.append(
                _action(
                    "use_explicit_retry",
                    "After an approval decision, start a new controlled task or run and retain both records.",
                )
            )

        phase = _phase(
            active_rollout=active_rollout,
            rollout_phase=rollout_phase,
            real_execution_requested=real_execution_requested,
            blockers=blockers,
        )
        return {
            "phase": phase,
            "actions": actions,
            "blockers": blockers,
            "execution": {
                "configured_mode": execution_mode,
                "delegation_mode": delegation_mode,
                "real_execution_requested": real_execution_requested,
                "kill_switch_active": kill_switch_active,
                "durable_required": bool(getattr(settings, "agent_team_durable_required", False)),
            },
            "evidence": {
                "settings": {
                    "agent_team_v2_enabled": v2_enabled,
                    "multi_agent_v2_enabled": coordination_enabled,
                    "rollout_phase": rollout_phase,
                    "fencing_enabled": bool(getattr(settings, "agent_team_fencing_enabled", False)),
                    "cross_session_locks_enabled": bool(
                        getattr(settings, "agent_team_cross_session_locks_enabled", False)
                    ),
                    "approval_resume_enabled": bool(
                        getattr(settings, "agent_team_approval_resume_enabled", False)
                    ),
                    "legacy_write_enabled": bool(
                        getattr(settings, "agent_team_legacy_write_enabled", False)
                    ),
                    "global_tab_enabled": bool(
                        getattr(settings, "agent_team_global_tab_enabled", False)
                    ),
                    "adoption_enabled": bool(
                        getattr(settings, "agent_team_adoption_enabled", False)
                    ),
                },
                "provider": provider,
                "durable": durable,
                "docker": docker,
                "coordination": coordination,
                "workspace": workspace,
            },
        }


def build_agent_team_readiness(
    settings: Any,
    *,
    runtime: Any | None = None,
    environment: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a secret-safe Agent Team v2 readiness payload."""
    return AgentTeamReadinessService(
        settings,
        runtime=runtime,
        environment=environment,
    ).assess()


def _add_real_execution_requirements(
    *,
    blockers: list[dict[str, str]],
    actions: list[dict[str, str]],
    settings: Any,
    delegation_mode: str,
    provider: dict[str, object],
    durable: dict[str, object],
    docker: dict[str, object],
    coordination: dict[str, object],
) -> None:
    if delegation_mode not in _REAL_DELEGATION_MODES:
        blockers.append(
            _blocker(
                "real_delegation_mode_required",
                "Real Agent Team execution requires AGENT_DELEGATION_EXECUTION_MODE=inline or background.",
            )
        )
    if not bool(getattr(settings, "agent_team_real_provider_enabled", False)):
        blockers.append(
            _blocker(
                "real_provider_not_enabled",
                "AGENT_TEAM_REAL_PROVIDER_ENABLED must be true for real execution.",
            )
        )
    if not provider["selected_model"] or not provider["provider_id"]:
        blockers.append(
            _blocker(
                "real_provider_not_configured",
                "The selected model must resolve to a configured provider.",
            )
        )
    elif not provider["credential_reference_present"]:
        blockers.append(
            _blocker(
                "real_provider_credential_reference_missing",
                "The selected provider has no configured credential reference.",
            )
        )
    if not bool(getattr(settings, "agent_team_durable_required", False)):
        blockers.append(
            _blocker(
                "durable_execution_not_required",
                "Real Agent Team execution requires AGENT_TEAM_DURABLE_REQUIRED=true.",
            )
        )
    if not bool(durable["postgres_database_configured"]):
        blockers.append(
            _blocker(
                "postgres_database_missing",
                "Real Agent Team execution requires a configured Postgres database.",
            )
        )
    if not bool(durable["job_backend_postgres"]) or not bool(durable["execution_durable"]):
        blockers.append(
            _blocker(
                "postgres_durable_jobs_required",
                "Real Agent Team execution requires BACKGROUND_JOB_BACKEND=postgres and BACKGROUND_JOB_EXECUTION=durable.",
            )
        )
    if durable["runtime_checked"] and not bool(durable["postgres_repository"]):
        blockers.append(
            _blocker(
                "postgres_agent_team_repository_required",
                "The running Agent Team service is not backed by a Postgres repository.",
            )
        )
    if durable["runtime_checked"]:
        if not bool(durable["durable_worker_started"]):
            blockers.append(
                _blocker(
                    "durable_worker_not_started",
                    "The durable background worker has not started in the running process.",
                )
            )
        elif not bool(durable["durable_worker_healthy"]):
            blockers.append(
                _blocker(
                    "durable_worker_not_healthy",
                    "The durable background worker is not alive with a fresh heartbeat.",
                )
            )
    if not bool(docker["docker_backend"]) or not bool(docker["local_fallback_disabled"]):
        blockers.append(
            _blocker(
                "docker_fail_closed_required",
                "Real Agent Team execution requires Docker sandboxing with local fallback disabled.",
            )
        )
    if not bool(getattr(settings, "agent_team_fencing_enabled", False)):
        blockers.append(
            _blocker(
                "fencing_not_enabled",
                "Real Agent Team execution requires AGENT_TEAM_FENCING_ENABLED=true.",
            )
        )
    if not bool(getattr(settings, "agent_team_cross_session_locks_enabled", False)):
        blockers.append(
            _blocker(
                "cross_session_locks_not_enabled",
                "Real Agent Team execution requires AGENT_TEAM_CROSS_SESSION_LOCKS_ENABLED=true.",
            )
        )
    if not bool(getattr(settings, "multi_agent_resource_lock_enabled", False)):
        blockers.append(
            _blocker(
                "resource_locks_not_enabled",
                "Real Agent Team execution requires MULTI_AGENT_RESOURCE_LOCK_ENABLED=true.",
            )
        )
    if coordination["runtime_checked"] and not bool(coordination["postgres_resource_locks"]):
        blockers.append(
            _blocker(
                "postgres_resource_locks_required",
                "The running coordination backend does not expose Postgres resource locks.",
            )
        )
    actions.extend(
        [
            _action(
                "capture_execution_evidence",
                "Record the task/run ids, workspace metadata, test output, and explicit adoption decision.",
            ),
            _action(
                "verify_docker_runtime",
                "Verify the configured Docker provider and trusted image out-of-band; readiness does not execute Docker.",
            ),
        ]
    )


def _add_worktree_workspace_requirements(
    *,
    blockers: list[dict[str, str]],
    actions: list[dict[str, str]],
    workspace: dict[str, object],
) -> None:
    blocker_code = workspace.get("blocker_code")
    if isinstance(blocker_code, str):
        blockers.append(_blocker(blocker_code, str(workspace["message"])))
        actions.append(_action("configure_workspace", str(workspace["action"])))


def _provider_evidence(settings: Any, environment_keys: frozenset[str]) -> dict[str, object]:
    selected_model = str(getattr(settings, "model", "") or "").strip()
    provider_id = selected_model.partition(":")[0]
    provider = next(
        (
            item
            for item in getattr(getattr(settings, "model_catalog", None), "providers", ()) or ()
            if str(getattr(item, "id", "") or "").strip() == provider_id
        ),
        None,
    )
    credential_env = str(getattr(provider, "api_key_env", "") or "").strip()
    return {
        "selected_model": selected_model or None,
        "provider_id": provider_id or None,
        "provider_configured": provider is not None,
        "credential_reference_present": bool(
            (credential_env and credential_env in environment_keys)
            or getattr(provider, "api_key_default", None)
        ),
    }


def _durable_evidence(settings: Any, runtime: Any | None) -> dict[str, object]:
    service = getattr(runtime, "agent_team_service", None) if runtime is not None else None
    repository = getattr(service, "repository", None)
    worker = getattr(runtime, "durable_background_worker", None) if runtime is not None else None
    worker_health = _durable_worker_health(worker)
    return {
        "postgres_database_configured": str(getattr(settings, "database_uri", "") or "")
        .strip()
        .lower()
        .startswith(("postgres://", "postgresql://")),
        "job_backend_postgres": str(getattr(settings, "background_job_backend", "") or "")
        .strip()
        .lower()
        == "postgres",
        "execution_durable": str(getattr(settings, "background_job_execution", "") or "")
        .strip()
        .lower()
        == "durable",
        "runtime_checked": runtime is not None,
        "postgres_repository": _is_postgres_component(repository),
        **worker_health,
    }


def _durable_worker_health(worker: object | None) -> dict[str, bool]:
    if worker is None:
        return {
            "durable_worker_started": False,
            "durable_worker_thread_alive": False,
            "durable_worker_heartbeat_fresh": False,
            "durable_worker_healthy": False,
        }
    snapshot = getattr(worker, "snapshot", None)
    if not callable(snapshot):
        return {
            "durable_worker_started": False,
            "durable_worker_thread_alive": False,
            "durable_worker_heartbeat_fresh": False,
            "durable_worker_healthy": False,
        }
    try:
        values = dict(snapshot())
    except Exception:  # noqa: BLE001 - readiness must fail closed on worker inspection errors.
        return {
            "durable_worker_started": False,
            "durable_worker_thread_alive": False,
            "durable_worker_heartbeat_fresh": False,
            "durable_worker_healthy": False,
        }
    started = bool(values.get("durable_worker_started"))
    thread_alive = bool(values.get("durable_worker_thread_alive"))
    heartbeat_fresh = bool(values.get("durable_worker_heartbeat_fresh"))
    return {
        "durable_worker_started": started,
        "durable_worker_thread_alive": thread_alive,
        "durable_worker_heartbeat_fresh": heartbeat_fresh,
        "durable_worker_healthy": started and thread_alive and heartbeat_fresh,
    }


def _docker_evidence(environment: Mapping[str, str]) -> dict[str, object]:
    backend = environment.get("FOCUS_AGENT_SANDBOX_BACKEND")
    fallback = environment.get("FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK")
    return {
        "backend_configured": backend is not None,
        "docker_backend": backend == "docker",
        "local_fallback_disabled": fallback == "0",
    }


def _coordination_evidence(runtime: Any | None) -> dict[str, object]:
    backend = getattr(runtime, "coordination_backend", None) if runtime is not None else None
    return {
        "runtime_checked": runtime is not None,
        "postgres_resource_locks": _is_postgres_component(getattr(backend, "resource_locks", None)),
        "postgres_approval_queue": _is_postgres_component(getattr(backend, "approval_queue", None)),
    }


def _workspace_evidence(settings: Any) -> dict[str, object]:
    configured_path = str(getattr(settings, "workspace_root", "") or "").strip()
    if not configured_path or configured_path == ".":
        return _workspace_failure(
            configured_path=configured_path or None,
            code="workspace_root_not_configured",
            message=(
                "Worktree sandbox execution requires WORKSPACE_ROOT to name a controlled git "
                "checkout; the default current directory is not accepted."
            ),
            action="Mount a controlled git checkout and set WORKSPACE_ROOT to its absolute path.",
        )

    path = Path(configured_path).expanduser()
    try:
        resolved_path = path.resolve(strict=True)
    except OSError:
        return _workspace_failure(
            configured_path=configured_path,
            code="workspace_root_missing",
            message="The configured WORKSPACE_ROOT does not exist.",
            action="Mount the configured git checkout at WORKSPACE_ROOT before enabling execution.",
        )
    if not resolved_path.is_dir():
        return _workspace_failure(
            configured_path=configured_path,
            resolved_path=resolved_path,
            code="workspace_root_not_directory",
            message="The configured WORKSPACE_ROOT is not a directory.",
            action="Set WORKSPACE_ROOT to the mounted git checkout directory.",
        )
    if not _is_writable_directory(resolved_path):
        return _workspace_failure(
            configured_path=configured_path,
            resolved_path=resolved_path,
            code="workspace_root_not_writable",
            message="The configured WORKSPACE_ROOT is not writable for git worktrees.",
            action="Grant the service write access to the controlled git checkout.",
        )

    git = shutil.which("git")
    if git is None:
        return _workspace_failure(
            configured_path=configured_path,
            resolved_path=resolved_path,
            code="git_executable_missing",
            message="Worktree sandbox execution requires the git executable.",
            action="Install git in the runtime image before enabling execution.",
        )
    try:
        worktree_result = subprocess.run(
            [git, "-C", str(resolved_path), "rev-parse", "--is-inside-work-tree"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return _workspace_failure(
            configured_path=configured_path,
            resolved_path=resolved_path,
            code="git_executable_unusable",
            message="Worktree sandbox execution could not invoke git.",
            action="Repair the git installation in the runtime image before enabling execution.",
        )
    if worktree_result.returncode != 0 or worktree_result.stdout.strip().lower() != "true":
        return _workspace_failure(
            configured_path=configured_path,
            resolved_path=resolved_path,
            code="workspace_root_not_git_repository",
            message="The configured WORKSPACE_ROOT is not a usable git worktree.",
            action="Mount a git checkout at WORKSPACE_ROOT before enabling execution.",
        )
    try:
        head_result = subprocess.run(
            [git, "-C", str(resolved_path), "rev-parse", "--verify", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return _workspace_failure(
            configured_path=configured_path,
            resolved_path=resolved_path,
            code="git_executable_unusable",
            message="Worktree sandbox execution could not invoke git.",
            action="Repair the git installation in the runtime image before enabling execution.",
        )
    if head_result.returncode != 0 or not head_result.stdout.strip():
        return _workspace_failure(
            configured_path=configured_path,
            resolved_path=resolved_path,
            code="workspace_root_missing_head",
            message="The configured WORKSPACE_ROOT must contain a committed git baseline.",
            action="Mount a git checkout with at least one reachable commit before enabling execution.",
        )
    return {
        "configured_path": configured_path,
        "resolved_path": str(resolved_path),
        "exists": True,
        "directory": True,
        "writable": True,
        "git_repository": True,
        "git_executable_available": True,
        "ready": True,
    }


def _workspace_failure(
    *,
    configured_path: str | None,
    code: str,
    message: str,
    action: str,
    resolved_path: Path | None = None,
) -> dict[str, object]:
    return {
        "configured_path": configured_path,
        "resolved_path": str(resolved_path) if resolved_path is not None else None,
        "exists": bool(resolved_path and resolved_path.exists()),
        "directory": bool(resolved_path and resolved_path.is_dir()),
        "writable": bool(resolved_path and _is_writable_directory(resolved_path)),
        "git_repository": False,
        "git_executable_available": shutil.which("git") is not None,
        "ready": False,
        "blocker_code": code,
        "message": message,
        "action": action,
    }


def _is_writable_directory(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)


def _environment_controls(environment: Mapping[str, object] | object) -> dict[str, str]:
    if isinstance(environment, Mapping):
        return {
            key: str(environment.get(key) or "").strip().lower()
            for key in (
                "FOCUS_AGENT_SANDBOX_BACKEND",
                "FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK",
            )
            if key in environment
        }
    return {}


def _environment_keys(environment: Mapping[str, object] | object) -> frozenset[str]:
    if isinstance(environment, Mapping):
        return frozenset(str(key) for key in environment)
    return frozenset()


def _is_postgres_component(component: object | None) -> bool:
    return component is not None and component.__class__.__name__.startswith("Postgres")


def _rollout_phase(value: object) -> str:
    normalized = str(value or "off").strip().lower().replace("-", "_")
    return normalized if normalized in {"off", "shadow", "canary", "enabled"} else "off"


def _execution_mode(value: object) -> str:
    normalized = str(value or "disabled").strip().lower().replace("-", "_")
    return (
        normalized
        if normalized in {"disabled", "inline", "background", "worktree_sandbox", "real"}
        else "disabled"
    )


def _phase(
    *,
    active_rollout: bool,
    rollout_phase: str,
    real_execution_requested: bool,
    blockers: list[dict[str, str]],
) -> str:
    if not active_rollout:
        return "disabled"
    if blockers:
        return "blocked"
    if real_execution_requested:
        return "ready"
    return rollout_phase


def _action(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


__all__ = ["AgentTeamReadinessService", "build_agent_team_readiness"]
