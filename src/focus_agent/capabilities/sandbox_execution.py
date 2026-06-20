from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

from .default_tool_modules.workspace_command import workspace_command_env

_DEFAULT_DOCKER_IMAGE = "focus-agent-sandbox:latest"
_DEFAULT_MEMORY_MB = 1024
_DEFAULT_PIDS_LIMIT = 512
_MAX_OUTPUT_FILES = 200
_MAX_OUTPUT_BYTES = 50 * 1024 * 1024
_RUNNER_FILENAME = "sandbox_runner.py"
_REQUEST_FILENAME = "sandbox_request.json"
_RESULT_FILENAME = "result.json"
_DEFAULT_RUN_TTL_SECONDS = 7 * 24 * 60 * 60
_WORKSPACE_MODE_COPY_DISCARD = "copy_discard"
_WORKSPACE_MODE_THREAD_PERSISTENT_COPY = "thread_persistent_copy"
_WORKSPACE_MODE_HOST = "host"
_FALLBACK_POLICY_ALLOW_DEV_LOCAL = "allow_dev_local"
_SANDBOX_ID_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_COPY_SKIP_NAMES = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
_SENSITIVE_ENV_NAME_MARKERS = (
    "API_KEY",
    "AUTH",
    "COOKIE",
    "CREDENTIAL",
    "JWT",
    "KEY",
    "PASSWORD",
    "PRIVATE",
    "SECRET",
    "SESSION",
    "TOKEN",
)


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


class SandboxExecutionService:
    def __init__(
        self,
        *,
        primary_backend: Any,
        fallback_backend: Any | None = None,
        allow_fallback: bool = True,
    ) -> None:
        self.primary_backend = primary_backend
        self.fallback_backend = fallback_backend
        self.allow_fallback = allow_fallback

    def run(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        try:
            return self.primary_backend.run(request)
        except SandboxBackendUnavailableError as exc:
            if not self.allow_fallback or self.fallback_backend is None:
                raise
            result = self.fallback_backend.run(request)
            return _with_fallback_reason(result, str(exc))


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
        _sync_workspace_snapshot(
            source_root=request.workspace_root,
            target_root=sandbox_workspace,
        )
        runner_path = run_root / _RUNNER_FILENAME
        request_path = run_root / _REQUEST_FILENAME
        _write_runner(runner_path)
        _write_request(request_path, request)

        started = time.monotonic()
        container_name = f"focus-agent-sandbox-{sandbox_id[:48]}-{run_id[:12]}"
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
        sandbox_id = request.sandbox_id or _sanitize_sandbox_identifier("anonymous", prefix="sandbox")
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


class LocalSubprocessSandboxBackend:
    backend_name = "local_subprocess"

    def run(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        run_id = uuid.uuid4().hex
        started = time.monotonic()
        cwd = (request.workspace_root / request.cwd).resolve()
        try:
            cwd.relative_to(request.workspace_root)
        except ValueError as exc:
            raise ValueError("cwd must stay inside the workspace.") from exc
        env = workspace_command_env()
        env.update(_sandbox_env(request.env))
        timed_out = False
        try:
            completed = subprocess.run(
                request.command,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=request.timeout_seconds,
                check=False,
            )
            exit_code: int | None = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = None
            stdout = _coerce_output(exc.stdout)
            stderr = _coerce_output(exc.stderr)
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        return _result_from_parts(
            request=request,
            run_id=run_id,
            backend="local_subprocess",
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            output_dir=None,
            policy={
                "backend": "local_subprocess",
                "network": "host",
                "workspace": "host",
                "fallback": True,
            },
        )


def default_sandbox_execution_service(
    *,
    fallback_backend: Any | None = None,
    allow_fallback: bool | None = None,
) -> SandboxExecutionService:
    backend = os.environ.get("FOCUS_AGENT_SANDBOX_BACKEND", "auto").strip().lower()
    image = os.environ.get("FOCUS_AGENT_SANDBOX_IMAGE", _DEFAULT_DOCKER_IMAGE).strip()
    resolved_allow_fallback = (
        os.environ.get("FOCUS_AGENT_SANDBOX_ALLOW_LOCAL_FALLBACK", "1") != "0"
        if allow_fallback is None
        else bool(allow_fallback)
    )
    resolved_fallback = fallback_backend or LocalSubprocessSandboxBackend()
    if backend == "local":
        return SandboxExecutionService(
            primary_backend=resolved_fallback,
            fallback_backend=None,
            allow_fallback=False,
        )
    if backend == "docker":
        return SandboxExecutionService(
            primary_backend=DockerSandboxBackend(image=image),
            fallback_backend=None,
            allow_fallback=False,
        )
    return SandboxExecutionService(
        primary_backend=DockerSandboxBackend(image=image),
        fallback_backend=resolved_fallback,
        allow_fallback=resolved_allow_fallback,
    )


def _with_fallback_reason(
    result: SandboxExecutionResult, fallback_reason: str
) -> SandboxExecutionResult:
    payload = result.to_payload()
    payload["fallback_reason"] = fallback_reason
    payload["fallback_used"] = True
    payload["degraded_reason"] = "local_host_execution"
    policy = dict(payload.get("policy") or {})
    policy["fallback_reason"] = fallback_reason
    policy["degraded_reason"] = "local_host_execution"
    payload["policy"] = policy
    return SandboxExecutionResult(**payload)


def _result_from_parts(
    *,
    request: SandboxExecutionRequest,
    run_id: str,
    backend: str,
    exit_code: int | None,
    timed_out: bool,
    stdout: str,
    stderr: str,
    duration_ms: float,
    output_dir: Path | None,
    policy: dict[str, Any],
) -> SandboxExecutionResult:
    stdout, stdout_truncated = _trim_output(stdout, request.max_output_chars)
    stderr, stderr_truncated = _trim_output(stderr, request.max_output_chars)
    outputs, outputs_truncated = (
        _run_outputs(output_dir=output_dir, workspace_root=request.workspace_root)
        if output_dir is not None
        else ([], False)
    )
    status = "timeout" if timed_out else ("completed" if exit_code == 0 else "failed")
    network_policy = str(policy.get("network") or ("host" if backend.startswith("local") else "none"))
    workspace_mode = str(policy.get("workspace") or request.workspace_mode)
    degraded_reason = "local_host_execution" if backend.startswith("local") else None
    if degraded_reason:
        policy = {**policy, "degraded_reason": degraded_reason}
    memory_mb = int(request.memory_mb or _DEFAULT_MEMORY_MB)
    resource_limits: dict[str, Any] = {}
    if backend == "docker":
        resource_limits = {"memory_mb": memory_mb, "pids_limit": _DEFAULT_PIDS_LIMIT}
    elif request.memory_mb is not None:
        resource_limits = {"memory_mb": request.memory_mb}
    return SandboxExecutionResult(
        status=status,
        command=list(request.command),
        cwd=request.cwd,
        exit_code=exit_code,
        timed_out=timed_out,
        timeout_seconds=request.timeout_seconds,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        outputs=outputs,
        outputs_truncated=outputs_truncated,
        duration_ms=duration_ms,
        sandbox_backend=backend,
        run_id=run_id,
        policy=policy,
        skill_id=request.skill_id,
        entrypoint=request.entrypoint,
        memory_mb=request.memory_mb,
        sandbox_id=request.sandbox_id or _sandbox_id_for_request(request, run_id=run_id),
        fallback_used=bool(policy.get("fallback")) or backend.startswith("local"),
        workspace_mode=workspace_mode,
        network_policy=network_policy,
        resource_limits=resource_limits,
        degraded_reason=degraded_reason,
    )


def _write_request(path: Path, request: SandboxExecutionRequest) -> None:
    payload = {
        "command": request.command,
        "cwd": request.cwd,
        "timeout_seconds": request.timeout_seconds,
        "dependencies": list(request.dependencies),
        "output_dir_arg": request.output_dir_arg,
        "workspace_mode": request.workspace_mode,
        "sandbox_id": request.sandbox_id,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _sync_workspace_snapshot(*, source_root: Path, target_root: Path) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    for child in source_root.iterdir():
        if child.name in _COPY_SKIP_NAMES or child.name == ".git":
            continue
        target = target_root / child.name
        if child.name == ".focus_agent":
            skills = child / "skills"
            if skills.is_dir():
                skills_target = target / "skills"
                if skills_target.exists() and not skills_target.is_dir():
                    skills_target.unlink()
                skills_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    skills,
                    skills_target,
                    symlinks=False,
                    ignore=_copytree_ignore,
                    dirs_exist_ok=True,
                )
            continue
        if child.is_dir():
            if target.exists() and not target.is_dir():
                target.unlink()
            shutil.copytree(
                child,
                target,
                symlinks=False,
                ignore=_copytree_ignore,
                dirs_exist_ok=True,
            )
        elif child.is_file():
            if target.exists() and target.is_dir():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _copytree_ignore(_dir: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _COPY_SKIP_NAMES or name == ".focus_agent"}


def _sandbox_paths(
    *,
    request: SandboxExecutionRequest,
    run_id: str,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    if request.workspace_mode == _WORKSPACE_MODE_COPY_DISCARD:
        runs_root = request.workspace_root / ".focus_agent" / "sandboxes" / "runs"
        run_root = runs_root / run_id
        return (
            run_root,
            runs_root,
            run_root / "workspace",
            run_root / "output",
            run_root / "tmp",
            run_root / "cache",
        )

    sandbox_id = request.sandbox_id or _sandbox_id_for_request(request, run_id=run_id)
    sandbox_root = request.workspace_root / ".focus_agent" / "sandboxes" / "threads" / sandbox_id
    runs_root = sandbox_root / "runs"
    run_root = runs_root / run_id
    return (
        run_root,
        runs_root,
        sandbox_root / "workspace",
        run_root / "output",
        run_root / "tmp",
        sandbox_root / "cache",
    )


def _sandbox_id_for_request(request: SandboxExecutionRequest, *, run_id: str) -> str:
    return _sandbox_id_for_parts(
        thread_id=request.thread_id,
        branch_id=request.branch_id,
        sandbox_id=request.sandbox_id,
        run_id=run_id,
    )


def _sandbox_id_for_parts(
    *,
    thread_id: str | None,
    branch_id: str | None,
    sandbox_id: str | None = None,
    run_id: str | None = None,
) -> str:
    if sandbox_id:
        return _sanitize_sandbox_identifier(sandbox_id, prefix="sandbox")
    if branch_id:
        return f"branch-{_sanitize_sandbox_identifier(branch_id, prefix='branch')}"
    if thread_id:
        return f"thread-{_sanitize_sandbox_identifier(thread_id, prefix='thread')}"
    if run_id:
        return f"run-{_sanitize_sandbox_identifier(run_id, prefix='run')}"
    return "anonymous"


def _sanitize_sandbox_identifier(value: str, *, prefix: str) -> str:
    sanitized = _SANDBOX_ID_UNSAFE_RE.sub("-", str(value)).strip(".-_")
    sanitized = sanitized[:96].strip(".-_")
    return sanitized or prefix


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _write_runner(path: Path) -> None:
    template = r'''
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

INPUT = Path(os.environ.get("SANDBOX_INPUT", "/workspace_input"))
WORKSPACE = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace"))
OUTPUT = Path(os.environ.get("SANDBOX_OUTPUT", "/sandbox_output"))
CACHE = Path(os.environ.get("SANDBOX_CACHE", "/sandbox_cache"))
REQUEST = Path(os.environ.get("SANDBOX_REQUEST", "/sandbox_request.json"))
RESULT = OUTPUT / "result.json"
SKIP_NAMES = __SKIP_NAMES__
SEED_MARKER = WORKSPACE / ".focus-agent-workspace-seeded"


def _ignore(_dir, names):
    return {{name for name in names if name in SKIP_NAMES or name == ".focus_agent"}}


def _copy_workspace():
    for child in INPUT.iterdir():
        target = WORKSPACE / child.name
        if child.name == ".focus_agent":
            skills = child / "skills"
            if skills.is_dir():
                (target).mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    skills,
                    target / "skills",
                    symlinks=False,
                    ignore=_ignore,
                    dirs_exist_ok=True,
                )
            continue
        if child.name in SKIP_NAMES:
            continue
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.copytree(child, target, symlinks=False, ignore=_ignore, dirs_exist_ok=True)
        elif child.is_file():
            shutil.copy2(child, target)


def _prepare_workspace(workspace_mode):
    if workspace_mode == "thread_persistent_copy" and SEED_MARKER.exists():
        return
    _copy_workspace()
    if workspace_mode == "thread_persistent_copy":
        SEED_MARKER.write_text("ok\n", encoding="utf-8")


def _ensure_venv(dependencies):
    if not dependencies:
        return None
    digest = hashlib.sha256("\n".join(dependencies).encode("utf-8")).hexdigest()
    venv_dir = CACHE / "venvs" / digest
    python = venv_dir / "bin" / "python"
    marker = venv_dir / ".focus-agent-deps-ok"
    if not marker.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        subprocess.run([str(python), "-m", "pip", "install", *dependencies], check=True)
        marker.write_text("ok\n", encoding="utf-8")
    return python


def main():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _prepare_workspace(request.get("workspace_mode") or "thread_persistent_copy")
    command = list(request["command"])
    output_dir_arg = request.get("output_dir_arg")
    if output_dir_arg:
        command.extend([str(output_dir_arg), str(OUTPUT)])
    venv_python = _ensure_venv(request.get("dependencies") or [])
    if venv_python is not None and Path(command[0]).name in {"python", "python3"}:
        command[0] = str(venv_python)
    cwd = WORKSPACE / request.get("cwd", ".")
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=int(request.get("timeout_seconds") or 60),
        check=False,
    )
    RESULT.write_text(
        json.dumps(
            {
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "timed_out": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as exc:
        RESULT.write_text(
            json.dumps(
                {
                    "exit_code": None,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                    "timed_out": True,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        RESULT.write_text(
            json.dumps(
                {
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": f"{type(exc).__name__}: {exc}",
                    "timed_out": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        raise
'''
    path.write_text(
        template.replace("__SKIP_NAMES__", repr(sorted(_COPY_SKIP_NAMES))).lstrip(),
        encoding="utf-8",
    )


def _sandbox_env(env: Mapping[str, str]) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for key, value in env.items():
        normalized = str(key).upper()
        if (
            normalized == "PYTHONPATH"
            or normalized.startswith("PIP_")
            or any(marker in normalized for marker in _SENSITIVE_ENV_NAME_MARKERS)
        ):
            continue
        allowed[str(key)] = str(value)
    return allowed


def _run_docker_command(
    command: list[str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _docker_image_available(*, docker_binary: str, image: str) -> bool:
    try:
        completed = subprocess.run(
            [docker_binary, "image", "inspect", image],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _docker_image_unavailable_message(image: str) -> str:
    return (
        f"docker image is not available: {image}. "
        f"Run `python scripts/ensure_sandbox_image.py --image {image}` "
        "to check Docker compatibility and build the sandbox image, or set "
        "FOCUS_AGENT_SANDBOX_IMAGE to an existing trusted image."
    )


def _force_remove_container(docker_binary: str, container_name: str) -> None:
    try:
        subprocess.run(
            [docker_binary, "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return None


def _cleanup_old_run_dirs(*, runs_root: Path, now: float, ttl_seconds: int) -> None:
    if ttl_seconds <= 0 or not runs_root.exists():
        return
    cutoff = now - ttl_seconds
    for path in runs_root.iterdir():
        try:
            stat_result = path.stat()
        except OSError:
            continue
        if not path.is_dir() or path.is_symlink() or stat_result.st_mtime >= cutoff:
            continue
        try:
            shutil.rmtree(path)
        except OSError:
            continue


def _looks_like_docker_unavailable(output: str) -> bool:
    lowered = output.lower()
    return (
        "cannot connect to the docker daemon" in lowered
        or "is the docker daemon running" in lowered
        or "command not found" in lowered
    )


def _looks_like_container_missing_or_stopped(output: str) -> bool:
    lowered = output.lower()
    return (
        "no such container" in lowered
        or "is not running" in lowered
        or "container is not running" in lowered
    )


def _trim_output(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def _coerce_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _run_outputs(
    *,
    output_dir: Path,
    workspace_root: Path,
) -> tuple[list[dict[str, Any]], bool]:
    outputs: list[dict[str, Any]] = []
    total_bytes = 0
    truncated = False
    for path in sorted(output_dir.rglob("*")):
        if len(outputs) >= _MAX_OUTPUT_FILES:
            truncated = True
            break
        try:
            stat_result = path.lstat()
        except OSError:
            continue
        if path.name == _RESULT_FILENAME or path.is_symlink() or not path.is_file():
            continue
        size_bytes = stat_result.st_size
        if total_bytes + size_bytes > _MAX_OUTPUT_BYTES:
            truncated = True
            break
        try:
            relative = path.relative_to(workspace_root).as_posix()
        except ValueError:
            relative = path.as_posix()
        total_bytes += size_bytes
        outputs.append({"path": relative, "size_bytes": size_bytes})
    return outputs, truncated


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
