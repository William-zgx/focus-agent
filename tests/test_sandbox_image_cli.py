from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "ensure_sandbox_image.py"
    spec = importlib.util.spec_from_file_location("ensure_sandbox_image", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sandbox_image_build_command_uses_lightweight_default_base() -> None:
    module = _load_module()

    command = module.build_sandbox_image_command(
        docker_binary="docker",
        image="focus-agent-sandbox:latest",
        dockerfile=Path("docker/sandbox.Dockerfile"),
        context=Path("."),
        base_image=None,
        apt_mirror=None,
        apt_security_mirror=None,
        pull=False,
    )

    assert command == [
        "docker",
        "build",
        "--build-arg",
        "BASE_IMAGE=node:20-bookworm-slim",
        "-f",
        "docker/sandbox.Dockerfile",
        "-t",
        "focus-agent-sandbox:latest",
        ".",
    ]


def test_sandbox_image_cli_check_only_reports_missing_image(capsys) -> None:
    module = _load_module()
    calls: list[list[str]] = []

    def fake_runner(command, **_kwargs):
        calls.append(list(command))
        if command[:2] == ["docker", "version"]:
            return module.CommandResult(returncode=0, stdout="18.09.1\n", stderr="")
        if command[:3] == ["docker", "image", "inspect"]:
            return module.CommandResult(returncode=1, stdout="", stderr="No such image")
        raise AssertionError(f"unexpected command: {command}")

    exit_code = module.main(
        ["--check-only", "--image", "focus-agent-sandbox:latest"],
        runner=fake_runner,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "focus-agent-sandbox:latest is missing" in captured.err
    assert "scripts/ensure_sandbox_image.py --image focus-agent-sandbox:latest" in captured.err
    assert calls == [
        ["docker", "version", "--format", "{{.Server.Version}}"],
        ["docker", "image", "inspect", "focus-agent-sandbox:latest"],
    ]


def test_sandbox_image_cli_rejects_too_old_docker(capsys) -> None:
    module = _load_module()

    def fake_runner(command, **_kwargs):
        if command[:2] == ["docker", "version"]:
            return module.CommandResult(returncode=0, stdout="18.06.0\n", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    exit_code = module.main(["--check-only"], runner=fake_runner)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Docker server 18.06.0 is older than supported minimum 18.09.0" in captured.err
