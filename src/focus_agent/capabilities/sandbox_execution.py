from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

from . import sandbox_execution_backends as _backends
from . import sandbox_runner as _runner
from . import sandbox_snapshot as _snapshot
from .default_tool_modules import workspace_command as _workspace_command

workspace_command_env = _workspace_command.workspace_command_env

_DEFAULT_DOCKER_IMAGE = "focus-agent-sandbox:latest"
_FALLBACK_POLICY_ALLOW_DEV_LOCAL = "allow_dev_local"

_DEFAULT_MEMORY_MB = _runner._DEFAULT_MEMORY_MB
_DEFAULT_PIDS_LIMIT = _runner._DEFAULT_PIDS_LIMIT
_DEFAULT_RUN_TTL_SECONDS = _runner._DEFAULT_RUN_TTL_SECONDS
_MAX_OUTPUT_BYTES = _runner._MAX_OUTPUT_BYTES
_MAX_OUTPUT_FILES = _runner._MAX_OUTPUT_FILES
_REQUEST_FILENAME = _runner._REQUEST_FILENAME
_RESULT_FILENAME = _runner._RESULT_FILENAME
_RUNNER_FILENAME = _runner._RUNNER_FILENAME
_SENSITIVE_ENV_NAME_MARKERS = _runner._SENSITIVE_ENV_NAME_MARKERS
_cleanup_old_run_dirs = _runner._cleanup_old_run_dirs
_coerce_output = _runner._coerce_output
_docker_image_available = _runner._docker_image_available
_docker_image_unavailable_message = _runner._docker_image_unavailable_message
_force_remove_container = _runner._force_remove_container
_looks_like_container_missing_or_stopped = _runner._looks_like_container_missing_or_stopped
_looks_like_docker_unavailable = _runner._looks_like_docker_unavailable
_result_from_parts = _runner._result_from_parts
_run_docker_command = _runner._run_docker_command
_run_outputs = _runner._run_outputs
_sandbox_env = _runner._sandbox_env
_trim_output = _runner._trim_output
_write_runner = _runner._write_runner

_COPY_SKIP_NAMES = _snapshot._COPY_SKIP_NAMES
_SANDBOX_ID_UNSAFE_RE = _snapshot._SANDBOX_ID_UNSAFE_RE
_WORKSPACE_MANIFEST_FILENAME = _snapshot._WORKSPACE_MANIFEST_FILENAME
_WORKSPACE_MODE_COPY_DISCARD = _snapshot._WORKSPACE_MODE_COPY_DISCARD
_WORKSPACE_MODE_HOST = _snapshot._WORKSPACE_MODE_HOST
_WORKSPACE_MODE_THREAD_PERSISTENT_COPY = _snapshot._WORKSPACE_MODE_THREAD_PERSISTENT_COPY
_add_snapshot_manifest_entry = _snapshot._add_snapshot_manifest_entry
_copytree_ignore = _snapshot._copytree_ignore
_delete_removed_snapshot_paths = _snapshot._delete_removed_snapshot_paths
_is_safe_manifest_path = _snapshot._is_safe_manifest_path
_optional_string = _snapshot._optional_string
_prune_snapshot_entry_to_manifest = _snapshot._prune_snapshot_entry_to_manifest
_prune_workspace_to_manifest = _snapshot._prune_workspace_to_manifest
_read_workspace_snapshot_manifest = _snapshot._read_workspace_snapshot_manifest
_remove_snapshot_path = _snapshot._remove_snapshot_path
_sandbox_id_for_parts = _snapshot._sandbox_id_for_parts
_sandbox_id_for_request = _snapshot._sandbox_id_for_request
_sandbox_paths = _snapshot._sandbox_paths
_sanitize_sandbox_identifier = _snapshot._sanitize_sandbox_identifier
_sync_workspace_snapshot = _snapshot._sync_workspace_snapshot
_workspace_snapshot_manifest = _snapshot._workspace_snapshot_manifest
_write_request = _snapshot._write_request
_write_workspace_snapshot_manifest = _snapshot._write_workspace_snapshot_manifest


_sandbox_run_locks_guard = threading.Lock()
_sandbox_run_locks: dict[str, tuple[threading.Lock, int]] = {}


@contextmanager
def _serialized_sandbox_run(sandbox_id: str) -> Iterator[None]:
    with _sandbox_run_locks_guard:
        sandbox_lock, users = _sandbox_run_locks.get(sandbox_id, (threading.Lock(), 0))
        _sandbox_run_locks[sandbox_id] = (sandbox_lock, users + 1)
    try:
        with sandbox_lock:
            yield
    finally:
        with _sandbox_run_locks_guard:
            sandbox_lock, users = _sandbox_run_locks[sandbox_id]
            if users == 1:
                del _sandbox_run_locks[sandbox_id]
            else:
                _sandbox_run_locks[sandbox_id] = (sandbox_lock, users - 1)


class SandboxBackendUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SandboxExecutionRequest:
    workspace_root: Path
    command: list[str]
    cwd: str = "."
    timeout_seconds: int = 60
    max_output_chars: int = 20_000
    allow_network: bool = False
    memory_mb: int | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    tool_name: str = ""
    skill_id: str | None = None
    entrypoint: str | None = None
    dependencies: tuple[str, ...] = ()
    output_dir_arg: str | None = None
    thread_id: str | None = None
    branch_id: str | None = None
    sandbox_id: str | None = None
    workspace_mode: str = _WORKSPACE_MODE_THREAD_PERSISTENT_COPY
    fallback_policy: str = _FALLBACK_POLICY_ALLOW_DEV_LOCAL
    policy: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("command must not be empty.")
        cwd = str(self.cwd or ".")
        if Path(cwd).is_absolute() or any(part == ".." for part in PurePosixPath(cwd).parts):
            raise ValueError("cwd must be relative and stay inside the workspace.")
        object.__setattr__(self, "workspace_root", self.workspace_root.expanduser().resolve())
        object.__setattr__(self, "cwd", "." if cwd == "" else cwd)
        object.__setattr__(self, "timeout_seconds", max(1, int(self.timeout_seconds or 1)))
        object.__setattr__(self, "max_output_chars", max(100, int(self.max_output_chars or 100)))
        if self.memory_mb is not None:
            object.__setattr__(self, "memory_mb", max(256, int(self.memory_mb)))
        object.__setattr__(self, "command", [str(item) for item in self.command])
        object.__setattr__(self, "dependencies", tuple(str(item) for item in self.dependencies))
        object.__setattr__(self, "thread_id", _optional_string(self.thread_id))
        object.__setattr__(self, "branch_id", _optional_string(self.branch_id))
        object.__setattr__(self, "sandbox_id", _optional_string(self.sandbox_id))
        workspace_mode = str(self.workspace_mode or _WORKSPACE_MODE_THREAD_PERSISTENT_COPY)
        if workspace_mode not in {
            _WORKSPACE_MODE_COPY_DISCARD,
            _WORKSPACE_MODE_THREAD_PERSISTENT_COPY,
            _WORKSPACE_MODE_HOST,
        }:
            raise ValueError(f"unsupported workspace_mode: {workspace_mode}")
        object.__setattr__(self, "workspace_mode", workspace_mode)
        object.__setattr__(
            self,
            "fallback_policy",
            str(self.fallback_policy or _FALLBACK_POLICY_ALLOW_DEV_LOCAL),
        )
        object.__setattr__(self, "policy", dict(self.policy or {}))


@dataclass(frozen=True, slots=True)
class SandboxExecutionResult:
    status: str
    command: list[str]
    cwd: str
    exit_code: int | None
    timed_out: bool
    timeout_seconds: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    outputs: list[dict[str, Any]]
    outputs_truncated: bool
    duration_ms: float
    sandbox_backend: str
    run_id: str
    policy: dict[str, Any]
    fallback_reason: str | None = None
    skill_id: str | None = None
    entrypoint: str | None = None
    memory_mb: int | None = None
    sandbox_id: str | None = None
    fallback_used: bool = False
    workspace_mode: str = _WORKSPACE_MODE_COPY_DISCARD
    network_policy: str | None = None
    resource_limits: dict[str, Any] = field(default_factory=dict)
    degraded_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "timeout_seconds": self.timeout_seconds,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "outputs": self.outputs,
            "outputs_truncated": self.outputs_truncated,
            "duration_ms": self.duration_ms,
            "sandbox_backend": self.sandbox_backend,
            "run_id": self.run_id,
            "policy": self.policy,
            "sandbox_id": self.sandbox_id,
            "fallback_used": self.fallback_used,
            "workspace_mode": self.workspace_mode,
            "network_policy": self.network_policy,
            "resource_limits": self.resource_limits,
        }
        if self.fallback_reason:
            payload["fallback_reason"] = self.fallback_reason
        if self.degraded_reason:
            payload["degraded_reason"] = self.degraded_reason
        if self.skill_id:
            payload["skill_id"] = self.skill_id
        if self.entrypoint:
            payload["entrypoint"] = self.entrypoint
        if self.memory_mb is not None:
            payload["memory_mb"] = self.memory_mb
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False)


SandboxExecutionService = _backends.SandboxExecutionService


class SandboxSession:
    def __init__(
        self,
        *,
        workspace_root: Path,
        sandbox_id: str,
        thread_id: str | None = None,
        branch_id: str | None = None,
        service: SandboxExecutionService | None = None,
    ) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.sandbox_id = sandbox_id
        self.thread_id = thread_id
        self.branch_id = branch_id
        self.service = service or default_sandbox_execution_service()

    def execute(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        session_request = replace(
            request,
            workspace_root=self.workspace_root,
            sandbox_id=self.sandbox_id,
            thread_id=request.thread_id or self.thread_id,
            branch_id=request.branch_id or self.branch_id,
            workspace_mode=request.workspace_mode or _WORKSPACE_MODE_THREAD_PERSISTENT_COPY,
        )
        return self.service.run(session_request)


class SandboxProvider:
    def __init__(
        self,
        *,
        workspace_root: Path,
        service: SandboxExecutionService | None = None,
    ) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.service = service
        self._sessions: dict[str, SandboxSession] = {}

    def acquire(self, thread_id: str | None, branch_id: str | None = None) -> str:
        sandbox_id = _sandbox_id_for_parts(thread_id=thread_id, branch_id=branch_id)
        if sandbox_id not in self._sessions:
            self._sessions[sandbox_id] = SandboxSession(
                workspace_root=self.workspace_root,
                sandbox_id=sandbox_id,
                thread_id=thread_id,
                branch_id=branch_id,
                service=self.service,
            )
        return sandbox_id

    def get(self, sandbox_id: str) -> SandboxSession | None:
        return self._sessions.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        self._sessions.pop(sandbox_id, None)


class DockerSandboxBackend:
    backend_name = "docker"

    def __init__(
        self,
        *,
        image: str = _DEFAULT_DOCKER_IMAGE,
        docker_binary: str = "docker",
        docker_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        run_id_factory: Callable[[], str] | None = None,
        run_ttl_seconds: int = _DEFAULT_RUN_TTL_SECONDS,
        reuse_containers: bool | None = None,
    ) -> None:
        self.image = image
        self.docker_binary = docker_binary
        self._docker_runner = docker_runner or _run_docker_command
        self._check_image_available = docker_runner is None
        self._run_id_factory = run_id_factory or (lambda: uuid.uuid4().hex)
        self.run_ttl_seconds = max(0, int(run_ttl_seconds))
        if reuse_containers is None:
            reuse_containers = docker_runner is None and (
                os.environ.get("FOCUS_AGENT_SANDBOX_REUSE_CONTAINERS", "1") != "0"
            )
        self.reuse_containers = bool(reuse_containers)

    def run(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        if self._check_image_available and not _docker_image_available(
            docker_binary=self.docker_binary,
            image=self.image,
        ):
            raise SandboxBackendUnavailableError(_docker_image_unavailable_message(self.image))
        run_id = self._run_id_factory()
        sandbox_id = _sandbox_id_for_request(request, run_id=run_id)
        request = replace(request, sandbox_id=sandbox_id)
        if (
            self.reuse_containers
            or request.workspace_mode == _WORKSPACE_MODE_THREAD_PERSISTENT_COPY
        ):
            with _serialized_sandbox_run(sandbox_id):
                return self._run(request=request, run_id=run_id)
        return self._run(request=request, run_id=run_id)

    def _run(self, *, request: SandboxExecutionRequest, run_id: str) -> SandboxExecutionResult:
        (
            run_root,
            runs_root,
            sandbox_workspace,
            sandbox_output,
            sandbox_tmp,
            sandbox_cache,
        ) = _sandbox_paths(request=request, run_id=run_id)
        _cleanup_old_run_dirs(
            runs_root=runs_root,
            now=time.time(),
            ttl_seconds=self.run_ttl_seconds,
        )
        for path in (sandbox_workspace, sandbox_output, sandbox_tmp, sandbox_cache):
            path.mkdir(parents=True, exist_ok=True)
        _sync_workspace_snapshot(source_root=request.workspace_root, target_root=sandbox_workspace)
        runner_path = run_root / _RUNNER_FILENAME
        request_path = run_root / _REQUEST_FILENAME
        _write_runner(runner_path)
        _write_request(request_path, request)

        started = time.monotonic()
        container_name = f"focus-agent-sandbox-{request.sandbox_id[:48]}-{run_id[:12]}"
        try:
            if self.reuse_containers:
                container_name = self._thread_container_name(request)
                completed = self._run_in_reusable_container(
                    request=request,
                    run_id=run_id,
                    container_name=container_name,
                    run_root=run_root,
                    runner_path=runner_path,
                    request_path=request_path,
                    sandbox_workspace=sandbox_workspace,
                    sandbox_tmp=sandbox_tmp,
                    sandbox_cache=sandbox_cache,
                )
            else:
                docker_command = self._docker_command(
                    request=request,
                    run_id=run_id,
                    container_name=container_name,
                    runner_path=runner_path,
                    request_path=request_path,
                    sandbox_workspace=sandbox_workspace,
                    sandbox_output=sandbox_output,
                    sandbox_tmp=sandbox_tmp,
                    sandbox_cache=sandbox_cache,
                )
                completed = self._docker_runner(
                    docker_command,
                    timeout=request.timeout_seconds + 10,
                )
        except FileNotFoundError as exc:
            raise SandboxBackendUnavailableError("docker is not available") from exc
        except subprocess.TimeoutExpired as exc:
            _force_remove_container(self.docker_binary, container_name)
            duration_ms = round((time.monotonic() - started) * 1000, 3)
            return _result_from_parts(
                request=request,
                run_id=run_id,
                backend="docker",
                exit_code=None,
                timed_out=True,
                stdout=_coerce_output(exc.stdout),
                stderr=_coerce_output(exc.stderr),
                duration_ms=duration_ms,
                output_dir=sandbox_output,
                policy=self._policy(request),
            )
        if completed.returncode == 125 and _looks_like_docker_unavailable(
            completed.stderr or completed.stdout
        ):
            raise SandboxBackendUnavailableError((completed.stderr or completed.stdout).strip())

        duration_ms = round((time.monotonic() - started) * 1000, 3)
        result_file = sandbox_output / _RESULT_FILENAME
        if result_file.exists():
            try:
                payload = json.loads(result_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        else:
            payload = {}
        exit_code = payload.get("exit_code")
        if not isinstance(exit_code, int):
            exit_code = completed.returncode
        return _result_from_parts(
            request=request,
            run_id=run_id,
            backend="docker",
            exit_code=exit_code,
            timed_out=bool(payload.get("timed_out", False)),
            stdout=_coerce_output(payload.get("stdout", completed.stdout)),
            stderr=_coerce_output(payload.get("stderr", completed.stderr)),
            duration_ms=duration_ms,
            output_dir=sandbox_output,
            policy=self._policy(request),
        )

    def _docker_command(
        self,
        *,
        request: SandboxExecutionRequest,
        run_id: str,
        container_name: str,
        runner_path: Path,
        request_path: Path,
        sandbox_workspace: Path,
        sandbox_output: Path,
        sandbox_tmp: Path,
        sandbox_cache: Path,
    ) -> list[str]:
        memory_mb = int(request.memory_mb or _DEFAULT_MEMORY_MB)
        network = "bridge" if request.allow_network else "none"
        command = [
            self.docker_binary,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            network,
            "--memory",
            f"{memory_mb}m",
            "--pids-limit",
            str(_DEFAULT_PIDS_LIMIT),
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/sandbox_output",
            "-e",
            "XDG_CACHE_HOME=/sandbox_cache",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-v",
            f"{request.workspace_root}:/workspace_input:ro",
            "-v",
            f"{sandbox_workspace}:/workspace",
            "-v",
            f"{sandbox_output}:/sandbox_output",
            "-v",
            f"{sandbox_tmp}:/tmp",
            "-v",
            f"{sandbox_cache}:/sandbox_cache",
            "-v",
            f"{runner_path}:/sandbox_runner.py:ro",
            "-v",
            f"{request_path}:/sandbox_request.json:ro",
        ]
        for key, value in _sandbox_env(request.env).items():
            command.extend(["-e", f"{key}={value}"])
        command.extend([self.image, "python", "/sandbox_runner.py"])
        return command

    def _run_in_reusable_container(
        self,
        *,
        request: SandboxExecutionRequest,
        run_id: str,
        container_name: str,
        run_root: Path,
        runner_path: Path,
        request_path: Path,
        sandbox_workspace: Path,
        sandbox_tmp: Path,
        sandbox_cache: Path,
    ) -> subprocess.CompletedProcess[str]:
        sandbox_root = sandbox_workspace.parent
        self._ensure_thread_container(
            request=request,
            container_name=container_name,
            sandbox_root=sandbox_root,
            sandbox_workspace=sandbox_workspace,
            sandbox_tmp=sandbox_tmp,
            sandbox_cache=sandbox_cache,
        )
        run_container_root = f"/sandbox/runs/{run_id}"
        command = [
            self.docker_binary,
            "exec",
            "-e",
            "SANDBOX_INPUT=/workspace_input",
            "-e",
            "SANDBOX_WORKSPACE=/workspace",
            "-e",
            f"SANDBOX_OUTPUT={run_container_root}/output",
            "-e",
            "SANDBOX_CACHE=/sandbox/cache",
            "-e",
            f"SANDBOX_REQUEST={run_container_root}/{_REQUEST_FILENAME}",
            "-e",
            f"HOME={run_container_root}/output",
            "-e",
            "XDG_CACHE_HOME=/sandbox/cache",
            "-e",
            "PYTHONUNBUFFERED=1",
        ]
        for key, value in _sandbox_env(request.env).items():
            command.extend(["-e", f"{key}={value}"])
        command.extend(
            [
                container_name,
                "python",
                f"{run_container_root}/{_RUNNER_FILENAME}",
            ]
        )
        del run_root, runner_path, request_path
        completed = self._docker_runner(command, timeout=request.timeout_seconds + 10)
        if completed.returncode == 125 and _looks_like_container_missing_or_stopped(
            completed.stderr or completed.stdout
        ):
            self._docker_runner(
                [self.docker_binary, "rm", "-f", container_name],
                timeout=10,
            )
            self._ensure_thread_container(
                request=request,
                container_name=container_name,
                sandbox_root=sandbox_workspace.parent,
                sandbox_workspace=sandbox_workspace,
                sandbox_tmp=sandbox_tmp,
                sandbox_cache=sandbox_cache,
            )
            completed = self._docker_runner(command, timeout=request.timeout_seconds + 10)
        return completed

    def _ensure_thread_container(
        self,
        *,
        request: SandboxExecutionRequest,
        container_name: str,
        sandbox_root: Path,
        sandbox_workspace: Path,
        sandbox_tmp: Path,
        sandbox_cache: Path,
    ) -> None:
        inspect = self._docker_runner(
            [
                self.docker_binary,
                "inspect",
                "-f",
                "{{.State.Running}}",
                container_name,
            ],
            timeout=10,
        )
        if inspect.returncode == 0 and inspect.stdout.strip().lower() == "true":
            return
        if inspect.returncode == 0:
            _force_remove_container(self.docker_binary, container_name)
        start = self._docker_runner(
            self._thread_container_command(
                request=request,
                container_name=container_name,
                sandbox_root=sandbox_root,
                sandbox_workspace=sandbox_workspace,
                sandbox_tmp=sandbox_tmp,
                sandbox_cache=sandbox_cache,
            ),
            timeout=20,
        )
        if start.returncode != 0:
            output = (start.stderr or start.stdout or "").strip()
            if _looks_like_docker_unavailable(output) or start.returncode == 125:
                raise SandboxBackendUnavailableError(output or "docker container start failed")
            raise RuntimeError(output or "docker container start failed")

    def _thread_container_command(
        self,
        *,
        request: SandboxExecutionRequest,
        container_name: str,
        sandbox_root: Path,
        sandbox_workspace: Path,
        sandbox_tmp: Path,
        sandbox_cache: Path,
    ) -> list[str]:
        memory_mb = int(request.memory_mb or _DEFAULT_MEMORY_MB)
        network = "bridge" if request.allow_network else "none"
        command = [
            self.docker_binary,
            "run",
            "-d",
            "--name",
            container_name,
            "--network",
            network,
            "--memory",
            f"{memory_mb}m",
            "--pids-limit",
            str(_DEFAULT_PIDS_LIMIT),
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/sandbox/output",
            "-e",
            "XDG_CACHE_HOME=/sandbox/cache",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-v",
            f"{request.workspace_root}:/workspace_input:ro",
            "-v",
            f"{sandbox_workspace}:/workspace",
            "-v",
            f"{sandbox_root}:/sandbox",
            "-v",
            f"{sandbox_tmp}:/tmp",
            "-v",
            f"{sandbox_cache}:/sandbox/cache",
            self.image,
            "sleep",
            "infinity",
        ]
        return command

    def _thread_container_name(self, request: SandboxExecutionRequest) -> str:
        sandbox_id = request.sandbox_id or "anonymous"
        network = "net" if request.allow_network else "none"
        memory = int(request.memory_mb or _DEFAULT_MEMORY_MB)
        suffix = _sanitize_sandbox_identifier(sandbox_id, prefix="sandbox")[:42]
        return f"focus-agent-sandbox-{suffix}-{network}-{memory}"

    def _policy(self, request: SandboxExecutionRequest) -> dict[str, Any]:
        return {
            "backend": "docker",
            "network": "bridge" if request.allow_network else "none",
            "workspace": request.workspace_mode,
            "sandbox_id": request.sandbox_id,
            "memory_mb": int(request.memory_mb or _DEFAULT_MEMORY_MB),
            "pids_limit": _DEFAULT_PIDS_LIMIT,
            "read_only_root": True,
            "container_reuse": self.reuse_containers,
        }


LocalSubprocessSandboxBackend = _backends.LocalSubprocessSandboxBackend
default_sandbox_execution_service = _backends.default_sandbox_execution_service
_with_fallback_reason = _backends._with_fallback_reason


__all__ = [
    "DockerSandboxBackend",
    "LocalSubprocessSandboxBackend",
    "SandboxBackendUnavailableError",
    "SandboxExecutionRequest",
    "SandboxExecutionResult",
    "SandboxExecutionService",
    "SandboxProvider",
    "SandboxSession",
    "default_sandbox_execution_service",
]
