from __future__ import annotations

import inspect
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import focus_agent.capabilities.sandbox_execution as sandbox_execution
import focus_agent.capabilities.sandbox_execution_backends as sandbox_execution_backends


def _request(workspace_root: Path) -> sandbox_execution.SandboxExecutionRequest:
    return sandbox_execution.SandboxExecutionRequest(
        workspace_root=workspace_root,
        command=["python", "--version"],
        timeout_seconds=5,
        max_output_chars=1000,
        allow_network=False,
        env={"SAFE_VAR": "value"},
        tool_name="test",
    )


def test_sandbox_execution_reexports_backend_policy_public_api() -> None:
    assert (
        sandbox_execution.SandboxExecutionService
        is sandbox_execution_backends.SandboxExecutionService
    )
    assert (
        sandbox_execution.LocalSubprocessSandboxBackend
        is sandbox_execution_backends.LocalSubprocessSandboxBackend
    )
    assert (
        sandbox_execution.default_sandbox_execution_service
        is sandbox_execution_backends.default_sandbox_execution_service
    )
    assert (
        sandbox_execution._with_fallback_reason is sandbox_execution_backends._with_fallback_reason
    )


def test_local_backend_uses_execution_module_patch_seams(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    class _FakeProcess:
        pid = 12345
        returncode = 0

        def communicate(self, *, timeout: int) -> tuple[str, str]:
            observed["timeout"] = timeout
            return "ok\n", ""

    def fake_popen(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        stdout: int,
        stderr: int,
        text: bool,
        encoding: str,
        errors: str,
        start_new_session: bool,
    ) -> _FakeProcess:
        observed.update(
            command=command,
            cwd=cwd,
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=text,
            encoding=encoding,
            errors=errors,
            start_new_session=start_new_session,
        )
        return _FakeProcess()

    monkeypatch.setattr(
        sandbox_execution,
        "workspace_command_env",
        lambda: {"BASE_VAR": "base"},
    )
    monkeypatch.setattr(
        sandbox_execution,
        "_sandbox_env",
        lambda env: {"SAFE_VAR": env["SAFE_VAR"]},
    )
    monkeypatch.setattr(sandbox_execution_backends.subprocess, "Popen", fake_popen)

    result = sandbox_execution.LocalSubprocessSandboxBackend().run(_request(tmp_path))

    assert result.status == "completed"
    assert result.stdout == "ok\n"
    assert observed["cwd"] == tmp_path
    assert observed["env"] == {"BASE_VAR": "base", "SAFE_VAR": "value"}
    assert observed["stdout"] is subprocess.PIPE
    assert observed["stderr"] is subprocess.PIPE
    assert observed["start_new_session"] is (os.name == "posix")
    assert observed["timeout"] == 5


@pytest.mark.skipif(os.name != "posix", reason="process groups require POSIX")
def test_local_backend_timeout_terminates_descendant_processes(tmp_path: Path) -> None:
    pid_path = tmp_path / "descendant.pid"
    child_code = (
        "from pathlib import Path; "
        "import os, sys, time; "
        "Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); "
        "time.sleep(60)"
    )
    request = sandbox_execution.SandboxExecutionRequest(
        workspace_root=tmp_path,
        command=[
            sys.executable,
            "-c",
            (
                "import subprocess, sys, time; "
                f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}, {str(pid_path)!r}]); "
                "print(child.pid, flush=True); "
                "print('child started', file=sys.stderr, flush=True); "
                "time.sleep(60)"
            ),
        ],
        timeout_seconds=1,
        max_output_chars=1000,
        allow_network=False,
        tool_name="test",
    )
    descendant_pid: int | None = None
    try:
        result = sandbox_execution.LocalSubprocessSandboxBackend().run(request)
        assert result.timed_out is True
        assert result.exit_code is None
        descendant_pid = int(result.stdout.strip())
        assert result.stderr == "child started\n"
        assert pid_path.read_text(encoding="utf-8") == str(descendant_pid)

        for _ in range(100):
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            pytest.fail(f"descendant process {descendant_pid} survived the timeout")
    finally:
        if descendant_pid is None and pid_path.exists():
            descendant_pid = int(pid_path.read_text(encoding="utf-8"))
        if descendant_pid is not None:
            try:
                os.kill(descendant_pid, 9)
            except ProcessLookupError:
                pass


def test_default_service_uses_reexported_docker_backend_patch_seam(monkeypatch) -> None:
    created: list[str] = []

    class _DockerBackend:
        def __init__(self, *, image: str) -> None:
            created.append(image)

    monkeypatch.setenv("FOCUS_AGENT_SANDBOX_BACKEND", "docker")
    monkeypatch.setenv("FOCUS_AGENT_SANDBOX_IMAGE", "trusted-image:1")
    monkeypatch.setattr(sandbox_execution, "DockerSandboxBackend", _DockerBackend)

    service = sandbox_execution.default_sandbox_execution_service()

    assert created == ["trusted-image:1"]
    assert isinstance(service.primary_backend, _DockerBackend)
    assert service.fallback_backend is None
    assert service.allow_fallback is False


def test_service_remains_fail_closed_when_fallback_is_disabled(tmp_path: Path) -> None:
    class _UnavailableBackend:
        def run(
            self,
            request: sandbox_execution.SandboxExecutionRequest,
        ) -> sandbox_execution.SandboxExecutionResult:
            del request
            raise sandbox_execution.SandboxBackendUnavailableError("docker unavailable")

    class _UnexpectedFallback:
        def run(
            self,
            request: sandbox_execution.SandboxExecutionRequest,
        ) -> sandbox_execution.SandboxExecutionResult:
            del request
            raise AssertionError("fallback must remain disabled")

    service = sandbox_execution.SandboxExecutionService(
        primary_backend=_UnavailableBackend(),
        fallback_backend=_UnexpectedFallback(),
        allow_fallback=False,
    )

    with pytest.raises(
        sandbox_execution.SandboxBackendUnavailableError, match="docker unavailable"
    ):
        service.run(_request(tmp_path))


def test_sandbox_execution_module_stays_within_orchestration_budget() -> None:
    module_path = Path(inspect.getfile(sandbox_execution))

    assert len(module_path.read_text(encoding="utf-8").splitlines()) <= 680
