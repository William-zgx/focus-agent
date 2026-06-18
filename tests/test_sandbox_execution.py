import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from focus_agent.capabilities import sandbox_execution
from focus_agent.capabilities.sandbox_execution import (
    DockerSandboxBackend,
    LocalSubprocessSandboxBackend,
    SandboxBackendUnavailable,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxExecutionService,
    SandboxProvider,
    default_sandbox_execution_service,
)


def _volume_host_path(command: list[str], container_path: str) -> Path:
    for index, token in enumerate(command):
        if token != "-v" or index + 1 >= len(command):
            continue
        raw = command[index + 1]
        host, _, rest = raw.partition(":")
        mounted_path, _, _mode = rest.partition(":")
        if mounted_path == container_path:
            return Path(host)
    raise AssertionError(f"missing docker volume for {container_path}: {command}")


def test_sandbox_provider_reuses_thread_session(tmp_path):
    provider = SandboxProvider(workspace_root=tmp_path)

    sandbox_id = provider.acquire(thread_id="thread/one", branch_id=None)
    same_sandbox_id = provider.acquire(thread_id="thread/one", branch_id=None)
    branch_sandbox_id = provider.acquire(thread_id="thread/one", branch_id="branch/a")

    assert sandbox_id == same_sandbox_id
    assert sandbox_id != branch_sandbox_id
    assert "/" not in sandbox_id
    assert "/" not in branch_sandbox_id
    assert provider.get(sandbox_id).sandbox_id == sandbox_id
    assert provider.get(sandbox_id).thread_id == "thread/one"
    assert provider.get(sandbox_id).branch_id is None
    assert provider.get(branch_sandbox_id).branch_id == "branch/a"

    provider.release(sandbox_id)

    assert provider.get(sandbox_id) is None
    assert provider.get(branch_sandbox_id) is not None


def test_docker_backend_reuses_thread_workspace_and_sandbox_id(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tracked.txt").write_text("original\n", encoding="utf-8")
    run_ids = iter(["run-docker-1", "run-docker-2"])
    observed_workspaces: list[Path] = []

    def fake_docker_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        del timeout
        sandbox_workspace = _volume_host_path(command, "/workspace")
        sandbox_output = _volume_host_path(command, "/sandbox_output")
        observed_workspaces.append(sandbox_workspace)
        if not (sandbox_workspace / "first-run-marker.txt").exists():
            (sandbox_workspace / "first-run-marker.txt").write_text("created\n", encoding="utf-8")
            stdout = "created\n"
        else:
            stdout = "persisted\n"
        (sandbox_output / "result.json").write_text(
            json.dumps(
                {
                    "exit_code": 0,
                    "stdout": stdout,
                    "stderr": "",
                    "timed_out": False,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    backend = DockerSandboxBackend(
        image="focus-agent-test:latest",
        docker_runner=fake_docker_run,
        run_id_factory=lambda: next(run_ids),
    )
    request = SandboxExecutionRequest(
        workspace_root=workspace,
        command=["python", "--version"],
        cwd=".",
        timeout_seconds=30,
        max_output_chars=1000,
        allow_network=False,
        memory_mb=512,
        tool_name="run_workspace_command",
        thread_id="thread-1",
    )

    first = backend.run(request)
    second = backend.run(request)

    assert observed_workspaces[0] == observed_workspaces[1]
    assert "/threads/" in observed_workspaces[0].as_posix()
    assert first.sandbox_id == second.sandbox_id
    assert first.workspace_mode == "thread_persistent_copy"
    assert first.fallback_used is False
    assert first.network_policy == "none"
    assert first.resource_limits == {"memory_mb": 512, "pids_limit": 512}
    assert first.stdout == "created\n"
    assert second.stdout == "persisted\n"
    assert (workspace / "first-run-marker.txt").exists() is False
    first_payload = first.to_payload()
    assert first_payload["sandbox_backend"] == "docker"
    assert first_payload["run_id"] == "run-docker-1"
    assert first_payload["sandbox_id"] == first.sandbox_id
    assert first_payload["workspace_mode"] == "thread_persistent_copy"
    assert first_payload["fallback_used"] is False
    assert first_payload["network_policy"] == "none"
    assert first_payload["resource_limits"] == {"memory_mb": 512, "pids_limit": 512}
    assert first_payload["policy"]["workspace"] == "thread_persistent_copy"
    assert first_payload["policy"]["sandbox_id"] == first.sandbox_id
    assert first_payload["policy"]["network"] == "none"


def _docker_exec_env_value(command: list[str], key: str) -> str:
    prefix = f"{key}="
    for index, token in enumerate(command):
        if token != "-e" or index + 1 >= len(command):
            continue
        value = command[index + 1]
        if value.startswith(prefix):
            return value[len(prefix) :]
    raise AssertionError(f"missing docker exec env {key}: {command}")


def test_docker_backend_reuses_thread_container_when_enabled(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tracked.txt").write_text("original\n", encoding="utf-8")
    run_ids = iter(["run-reuse-1", "run-reuse-2"])
    commands: list[list[str]] = []
    container_running = False
    sandbox_mount: Path | None = None

    def fake_docker_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        nonlocal container_running, sandbox_mount
        del timeout
        commands.append(command)
        if command[1] == "inspect":
            stdout = "true\n" if container_running else "false\n"
            return subprocess.CompletedProcess(command, 1 if not container_running else 0, stdout, "")
        if command[1] == "run":
            sandbox_mount = _volume_host_path(command, "/sandbox")
            container_running = True
            return subprocess.CompletedProcess(command, 0, "container-id\n", "")
        if command[1] == "exec":
            assert sandbox_mount is not None
            output_container_path = _docker_exec_env_value(command, "SANDBOX_OUTPUT")
            assert output_container_path.startswith("/sandbox/")
            output_path = sandbox_mount / output_container_path.removeprefix("/sandbox/")
            output_path.mkdir(parents=True, exist_ok=True)
            output_path.joinpath("result.json").write_text(
                json.dumps(
                    {
                        "exit_code": 0,
                        "stdout": f"ran {len([cmd for cmd in commands if cmd[1] == 'exec'])}\n",
                        "stderr": "",
                        "timed_out": False,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected docker command: {command}")

    backend = DockerSandboxBackend(
        image="focus-agent-test:latest",
        docker_runner=fake_docker_run,
        run_id_factory=lambda: next(run_ids),
        reuse_containers=True,
    )
    request = SandboxExecutionRequest(
        workspace_root=workspace,
        command=["python", "--version"],
        cwd=".",
        timeout_seconds=30,
        max_output_chars=1000,
        allow_network=False,
        memory_mb=512,
        tool_name="run_workspace_command",
        thread_id="thread-reuse",
    )

    first = backend.run(request)
    second = backend.run(request)

    run_commands = [command for command in commands if command[1] == "run"]
    exec_commands = [command for command in commands if command[1] == "exec"]
    assert len(run_commands) == 1
    assert len(exec_commands) == 2
    assert "--rm" not in run_commands[0]
    assert first.stdout == "ran 1\n"
    assert second.stdout == "ran 2\n"
    assert first.sandbox_id == second.sandbox_id
    assert first.policy["container_reuse"] is True
    assert second.policy["container_reuse"] is True


def test_docker_backend_rebuilds_reusable_container_when_exec_finds_stopped_container(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    commands: list[list[str]] = []
    run_ids = iter(["run-rebuild-1"])
    started_count = 0
    exec_count = 0
    removed = False
    sandbox_mount: Path | None = None

    def fake_docker_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        nonlocal started_count, exec_count, removed, sandbox_mount
        del timeout
        commands.append(command)
        if command[1] == "inspect":
            if removed:
                return subprocess.CompletedProcess(command, 1, "", "No such container")
            return subprocess.CompletedProcess(command, 0, "true\n", "")
        if command[1] == "rm":
            removed = True
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1] == "run":
            sandbox_mount = _volume_host_path(command, "/sandbox")
            started_count += 1
            removed = False
            return subprocess.CompletedProcess(command, 0, "container-id\n", "")
        if command[1] == "exec":
            exec_count += 1
            if exec_count == 1:
                return subprocess.CompletedProcess(
                    command,
                    125,
                    "",
                    "Error response from daemon: Container is not running",
                )
            assert sandbox_mount is not None
            output_path = (
                sandbox_mount
                / _docker_exec_env_value(command, "SANDBOX_OUTPUT").removeprefix("/sandbox/")
            )
            output_path.mkdir(parents=True, exist_ok=True)
            output_path.joinpath("result.json").write_text(
                json.dumps(
                    {
                        "exit_code": 0,
                        "stdout": "rebuilt\n",
                        "stderr": "",
                        "timed_out": False,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected docker command: {command}")

    backend = DockerSandboxBackend(
        image="focus-agent-test:latest",
        docker_runner=fake_docker_run,
        run_id_factory=lambda: next(run_ids),
        reuse_containers=True,
    )
    result = backend.run(
        SandboxExecutionRequest(
            workspace_root=workspace,
            command=["python", "--version"],
            thread_id="thread-rebuild",
            timeout_seconds=30,
        )
    )

    assert result.stdout == "rebuilt\n"
    assert exec_count == 2
    assert started_count == 1
    assert any(command[1] == "rm" for command in commands)


def test_docker_backend_refreshes_thread_workspace_from_host_between_runs(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tracked.txt").write_text("original\n", encoding="utf-8")
    run_ids = iter(["run-refresh-1", "run-refresh-2"])
    observed_contents: list[str] = []

    def fake_docker_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        del timeout
        sandbox_workspace = _volume_host_path(command, "/workspace")
        sandbox_output = _volume_host_path(command, "/sandbox_output")
        observed_contents.append((sandbox_workspace / "tracked.txt").read_text(encoding="utf-8"))
        (sandbox_output / "result.json").write_text(
            json.dumps(
                {
                    "exit_code": 0,
                    "stdout": "ok\n",
                    "stderr": "",
                    "timed_out": False,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    backend = DockerSandboxBackend(
        image="focus-agent-test:latest",
        docker_runner=fake_docker_run,
        run_id_factory=lambda: next(run_ids),
    )
    request = SandboxExecutionRequest(
        workspace_root=workspace,
        command=["python", "--version"],
        cwd=".",
        timeout_seconds=30,
        max_output_chars=1000,
        allow_network=False,
        tool_name="run_workspace_command",
        thread_id="thread-refresh",
    )

    backend.run(request)
    (workspace / "tracked.txt").write_text("updated\n", encoding="utf-8")
    backend.run(request)

    assert observed_contents == ["original\n", "updated\n"]


def test_docker_backend_runs_in_isolated_workspace_with_network_disabled(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "tracked.txt").write_text("original\n", encoding="utf-8")
    observed_commands: list[list[str]] = []

    def fake_docker_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        del timeout
        observed_commands.append(command)
        sandbox_workspace = _volume_host_path(command, "/workspace")
        sandbox_output = _volume_host_path(command, "/sandbox_output")
        (sandbox_workspace / "tracked.txt").write_text("mutated\n", encoding="utf-8")
        (sandbox_output / "result.json").write_text(
            json.dumps(
                {
                    "exit_code": 0,
                    "stdout": "ok\n",
                    "stderr": "",
                    "timed_out": False,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    backend = DockerSandboxBackend(
        image="focus-agent-test:latest",
        docker_runner=fake_docker_run,
        run_id_factory=lambda: "run-docker-1",
    )

    result = backend.run(
        SandboxExecutionRequest(
            workspace_root=workspace,
            command=["python", "-m", "pytest", "--version"],
            cwd=".",
            timeout_seconds=30,
            max_output_chars=1000,
            allow_network=False,
            memory_mb=512,
            env={
                "OPENAI_API_KEY": "sk-test-secret",
                "CUSTOM_TOKEN": "token-secret",
                "PIP_INDEX_URL": "https://private.example/simple",
                "PYTHONPATH": "/private/pythonpath",
                "SAFE_VAR": "visible",
            },
            tool_name="run_workspace_command",
        )
    )

    docker_command = observed_commands[0]
    assert result.sandbox_backend == "docker"
    assert result.run_id == "run-docker-1"
    assert result.policy["network"] == "none"
    assert "--network" in docker_command
    assert "none" in docker_command
    assert "--read-only" in docker_command
    assert "--user" in docker_command
    assert "SAFE_VAR=visible" in docker_command
    assert not any("sk-test-secret" in token for token in docker_command)
    assert not any("token-secret" in token for token in docker_command)
    assert not any("PIP_INDEX_URL" in token for token in docker_command)
    assert not any("PYTHONPATH" in token for token in docker_command)
    assert not any("docker.sock" in token for token in docker_command)
    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "original\n"


def test_sandbox_service_falls_back_to_local_backend_with_visible_reason(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class _UnavailableBackend:
        backend_name = "docker"

        def run(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
            del request
            raise SandboxBackendUnavailable("docker is not available")

    service = SandboxExecutionService(
        primary_backend=_UnavailableBackend(),
        fallback_backend=LocalSubprocessSandboxBackend(),
        allow_fallback=True,
    )

    result = service.run(
        SandboxExecutionRequest(
            workspace_root=workspace,
            command=[
                "python",
                "-c",
                (
                    "import os; "
                    "print(os.environ.get('SAFE_VAR', 'missing')); "
                    "print(os.environ.get('OPENAI_API_KEY', 'missing'))"
                ),
            ],
            cwd=".",
            timeout_seconds=30,
            max_output_chars=1000,
            allow_network=False,
            env={"SAFE_VAR": "fallback", "OPENAI_API_KEY": "sk-test-secret"},
            tool_name="test",
        )
    )

    assert result.sandbox_backend == "local_subprocess"
    assert result.fallback_reason == "docker is not available"
    assert result.stdout.splitlines() == ["fallback", "missing"]
    payload = result.to_payload()
    assert payload["fallback_used"] is True
    assert payload["fallback_reason"] == "docker is not available"
    assert payload["degraded_reason"] == "local_host_execution"
    assert payload["workspace_mode"] == "host"
    assert payload["network_policy"] == "host"
    assert payload["policy"]["fallback"] is True
    assert payload["policy"]["fallback_reason"] == "docker is not available"
    assert payload["policy"]["degraded_reason"] == "local_host_execution"


def test_docker_backend_cleans_old_run_directories(tmp_path):
    workspace = tmp_path / "workspace"
    runs_root = (
        workspace
        / ".focus_agent"
        / "sandboxes"
        / "threads"
        / "thread-cleanup-thread"
        / "runs"
    )
    old_run = runs_root / "old-run"
    old_run.mkdir(parents=True)
    (old_run / "old.txt").write_text("old", encoding="utf-8")
    old_mtime = time.time() - 3600
    os.utime(old_run, (old_mtime, old_mtime))

    def fake_docker_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        del timeout
        sandbox_output = _volume_host_path(command, "/sandbox_output")
        (sandbox_output / "result.json").write_text(
            json.dumps(
                {
                    "exit_code": 0,
                    "stdout": "",
                    "stderr": "",
                    "timed_out": False,
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    backend = DockerSandboxBackend(
        docker_runner=fake_docker_run,
        run_id_factory=lambda: "new-run",
        run_ttl_seconds=1,
    )

    backend.run(
        SandboxExecutionRequest(
            workspace_root=workspace,
            command=["python", "--version"],
            timeout_seconds=5,
            max_output_chars=1000,
            allow_network=False,
            tool_name="run_workspace_command",
            thread_id="cleanup-thread",
        )
    )

    assert not old_run.exists()
    assert (runs_root / "new-run").exists()
    assert (runs_root.parent / "workspace").exists()


def test_sandbox_request_rejects_absolute_cwd(tmp_path):
    with pytest.raises(ValueError, match="cwd must be relative"):
        SandboxExecutionRequest(
            workspace_root=tmp_path,
            command=["python", "--version"],
            cwd="/tmp",
            timeout_seconds=1,
            max_output_chars=1000,
            allow_network=False,
            tool_name="test",
        )


def test_default_sandbox_service_uses_standard_execution_image(monkeypatch):
    monkeypatch.delenv("FOCUS_AGENT_SANDBOX_BACKEND", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_SANDBOX_IMAGE", raising=False)

    service = default_sandbox_execution_service()

    assert service.primary_backend.image == "focus-agent-sandbox:latest"


def test_docker_backend_missing_image_error_includes_preflight_command(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sandbox_execution,
        "_docker_image_available",
        lambda *, docker_binary, image: False,
    )
    backend = DockerSandboxBackend(image="missing-sandbox:latest")

    with pytest.raises(SandboxBackendUnavailable) as exc_info:
        backend.run(
            SandboxExecutionRequest(
                workspace_root=tmp_path,
                command=["python", "--version"],
                timeout_seconds=1,
                max_output_chars=1000,
                allow_network=False,
                tool_name="test",
                thread_id="thread-1",
            )
        )

    message = str(exc_info.value)
    assert "missing-sandbox:latest" in message
    assert "scripts/ensure_sandbox_image.py" in message
    assert "--image missing-sandbox:latest" in message
