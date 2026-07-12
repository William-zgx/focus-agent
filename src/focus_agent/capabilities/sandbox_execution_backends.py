from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sandbox_execution import SandboxExecutionRequest, SandboxExecutionResult


def _execution_module() -> Any:
    from . import sandbox_execution

    return sandbox_execution


def _backend_unavailable_error() -> type[RuntimeError]:
    return _execution_module().SandboxBackendUnavailableError


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
        except _backend_unavailable_error() as exc:
            if not self.allow_fallback or self.fallback_backend is None:
                raise
            result = self.fallback_backend.run(request)
            return _with_fallback_reason(result, str(exc))


class LocalSubprocessSandboxBackend:
    backend_name = "local_subprocess"

    def run(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        execution = _execution_module()
        run_id = uuid.uuid4().hex
        started = time.monotonic()
        cwd = (request.workspace_root / request.cwd).resolve()
        try:
            cwd.relative_to(request.workspace_root)
        except ValueError as exc:
            raise ValueError("cwd must stay inside the workspace.") from exc
        env = execution.workspace_command_env()
        env.update(execution._sandbox_env(request.env))
        timed_out = False
        process = subprocess.Popen(
            request.command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name == "posix",
        )
        try:
            stdout, stderr = process.communicate(timeout=request.timeout_seconds)
            exit_code: int | None = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            stdout, stderr = process.communicate()
            exit_code = None
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        return execution._result_from_parts(
            request=request,
            run_id=run_id,
            backend=self.backend_name,
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            output_dir=None,
            policy={
                "backend": self.backend_name,
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
    execution = _execution_module()
    backend = os.environ.get("FOCUS_AGENT_SANDBOX_BACKEND", "auto").strip().lower()
    image = os.environ.get("FOCUS_AGENT_SANDBOX_IMAGE", execution._DEFAULT_DOCKER_IMAGE).strip()
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
            primary_backend=execution.DockerSandboxBackend(image=image),
            fallback_backend=None,
            allow_fallback=False,
        )
    return SandboxExecutionService(
        primary_backend=execution.DockerSandboxBackend(image=image),
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
    return _execution_module().SandboxExecutionResult(**payload)
