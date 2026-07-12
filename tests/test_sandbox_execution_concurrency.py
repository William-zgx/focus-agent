import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from focus_agent.capabilities import sandbox_execution
from focus_agent.capabilities.sandbox_execution import (
    DockerSandboxBackend,
    SandboxExecutionRequest,
)


def _volume_host_path(command: list[str], container_path: str) -> Path:
    for index, token in enumerate(command):
        if token != "-v" or index + 1 >= len(command):
            continue
        host_path, _, mount = command[index + 1].partition(":")
        mounted_path, _, _mode = mount.partition(":")
        if mounted_path == container_path:
            return Path(host_path)
    raise AssertionError(f"missing docker volume for {container_path}: {command}")


def _docker_exec_env_value(command: list[str], key: str) -> str:
    prefix = f"{key}="
    for index, token in enumerate(command):
        if token == "-e" and index + 1 < len(command):
            value = command[index + 1]
            if value.startswith(prefix):
                return value[len(prefix) :]
    raise AssertionError(f"missing docker exec env {key}: {command}")


def _request(workspace_root: Path, *, sandbox_id: str) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        workspace_root=workspace_root,
        command=["python", "--version"],
        timeout_seconds=30,
        max_output_chars=1000,
        sandbox_id=sandbox_id,
        thread_id="thread-lock",
        tool_name="run_workspace_command",
    )


def _wait_at_barrier(barrier: threading.Barrier) -> None:
    try:
        barrier.wait(timeout=1)
    except threading.BrokenBarrierError:
        pass


def test_docker_backend_serializes_concurrent_reusable_runs_for_same_sandbox(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_lock = threading.Lock()
    start_barrier = threading.Barrier(3)
    snapshot_barrier = threading.Barrier(2)
    exec_barrier = threading.Barrier(2)
    active_snapshots = 0
    max_active_snapshots = 0
    active_execs = 0
    max_active_execs = 0
    container_running = False
    container_starts = 0
    sandbox_root: Path | None = None

    def fake_sync_workspace_snapshot(*, source_root: Path, target_root: Path) -> None:
        nonlocal active_snapshots, max_active_snapshots
        del source_root, target_root
        with state_lock:
            active_snapshots += 1
            max_active_snapshots = max(max_active_snapshots, active_snapshots)
        try:
            _wait_at_barrier(snapshot_barrier)
        finally:
            with state_lock:
                active_snapshots -= 1

    def fake_docker_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        nonlocal active_execs, max_active_execs, container_running, container_starts, sandbox_root
        del timeout
        operation = command[1]
        if operation == "inspect":
            with state_lock:
                running = container_running
            return subprocess.CompletedProcess(
                command, 0 if running else 1, "true\n" if running else "", ""
            )
        if operation == "run":
            with state_lock:
                container_starts += 1
                container_running = True
                sandbox_root = _volume_host_path(command, "/sandbox")
            return subprocess.CompletedProcess(command, 0, "container-id\n", "")
        if operation == "exec":
            with state_lock:
                active_execs += 1
                max_active_execs = max(max_active_execs, active_execs)
                current_sandbox_root = sandbox_root
            try:
                _wait_at_barrier(exec_barrier)
                assert current_sandbox_root is not None
                output_path = current_sandbox_root / _docker_exec_env_value(
                    command, "SANDBOX_OUTPUT"
                ).removeprefix("/sandbox/")
                output_path.mkdir(parents=True, exist_ok=True)
                output_path.joinpath("result.json").write_text(
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
            finally:
                with state_lock:
                    active_execs -= 1
        raise AssertionError(f"unexpected docker command: {command}")

    monkeypatch.setattr(sandbox_execution, "_sync_workspace_snapshot", fake_sync_workspace_snapshot)
    backend = DockerSandboxBackend(
        image="focus-agent-test:latest",
        docker_runner=fake_docker_run,
        reuse_containers=True,
    )
    request = _request(workspace, sandbox_id="shared-sandbox")

    def run_request():
        start_barrier.wait()
        return backend.run(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_request)
        second = executor.submit(run_request)
        start_barrier.wait()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert [result.stdout for result in results] == ["ok\n", "ok\n"]
    assert max_active_snapshots == 1
    assert max_active_execs == 1
    assert container_starts == 1


def test_docker_backend_allows_different_sandboxes_to_snapshot_concurrently(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_lock = threading.Lock()
    start_barrier = threading.Barrier(3)
    snapshot_barrier = threading.Barrier(2)
    active_snapshots = 0
    max_active_snapshots = 0

    def fake_sync_workspace_snapshot(*, source_root: Path, target_root: Path) -> None:
        nonlocal active_snapshots, max_active_snapshots
        del source_root, target_root
        with state_lock:
            active_snapshots += 1
            max_active_snapshots = max(max_active_snapshots, active_snapshots)
        try:
            _wait_at_barrier(snapshot_barrier)
        finally:
            with state_lock:
                active_snapshots -= 1

    def fake_docker_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        del timeout
        sandbox_output = _volume_host_path(command, "/sandbox_output")
        sandbox_output.joinpath("result.json").write_text(
            json.dumps({"exit_code": 0, "stdout": "ok\n", "stderr": "", "timed_out": False}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(sandbox_execution, "_sync_workspace_snapshot", fake_sync_workspace_snapshot)
    backend = DockerSandboxBackend(
        image="focus-agent-test:latest",
        docker_runner=fake_docker_run,
        reuse_containers=False,
    )

    def run_request(sandbox_id: str):
        start_barrier.wait()
        return backend.run(_request(workspace, sandbox_id=sandbox_id))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_request, "sandbox-one")
        second = executor.submit(run_request, "sandbox-two")
        start_barrier.wait()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert [result.stdout for result in results] == ["ok\n", "ok\n"]
    assert max_active_snapshots == 2


def test_docker_backend_releases_reusable_sandbox_lock_after_runner_exception(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_lock = threading.Lock()
    container_running = False
    fail_first_exec = True
    sandbox_root: Path | None = None

    def fake_docker_run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        nonlocal container_running, fail_first_exec, sandbox_root
        del timeout
        operation = command[1]
        if operation == "inspect":
            with state_lock:
                running = container_running
            return subprocess.CompletedProcess(
                command, 0 if running else 1, "true\n" if running else "", ""
            )
        if operation == "run":
            with state_lock:
                container_running = True
                sandbox_root = _volume_host_path(command, "/sandbox")
            return subprocess.CompletedProcess(command, 0, "container-id\n", "")
        if operation == "exec":
            with state_lock:
                if fail_first_exec:
                    fail_first_exec = False
                    raise RuntimeError("docker exec failed")
                current_sandbox_root = sandbox_root
            assert current_sandbox_root is not None
            output_path = current_sandbox_root / _docker_exec_env_value(
                command, "SANDBOX_OUTPUT"
            ).removeprefix("/sandbox/")
            output_path.mkdir(parents=True, exist_ok=True)
            output_path.joinpath("result.json").write_text(
                json.dumps(
                    {"exit_code": 0, "stdout": "recovered\n", "stderr": "", "timed_out": False}
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"unexpected docker command: {command}")

    backend = DockerSandboxBackend(
        image="focus-agent-test:latest",
        docker_runner=fake_docker_run,
        reuse_containers=True,
    )
    request = _request(workspace, sandbox_id="exception-sandbox")

    with pytest.raises(RuntimeError, match="docker exec failed"):
        backend.run(request)

    assert backend.run(request).stdout == "recovered\n"
