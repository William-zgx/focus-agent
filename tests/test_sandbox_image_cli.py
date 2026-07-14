from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


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


def test_sandbox_image_build_command_forwards_explicit_registry_arguments() -> None:
    module = _load_module()

    command = module.build_sandbox_image_command(
        docker_binary="docker",
        image="focus-agent-sandbox:managed",
        dockerfile=Path("docker/sandbox.Dockerfile"),
        context=Path("."),
        base_image="node:20-bookworm-slim",
        apt_mirror="https://apt.example.invalid/debian",
        apt_security_mirror="https://apt.example.invalid/debian-security",
        npm_registry="https://npm.example.invalid",
        pip_index_url="https://pypi.example.invalid/simple",
        pip_default_timeout=300,
        pull=True,
    )

    assert command == [
        "docker",
        "build",
        "--build-arg",
        "BASE_IMAGE=node:20-bookworm-slim",
        "--build-arg",
        "APT_MIRROR=https://apt.example.invalid/debian",
        "--build-arg",
        "APT_SECURITY_MIRROR=https://apt.example.invalid/debian-security",
        "--build-arg",
        "NPM_REGISTRY=https://npm.example.invalid",
        "--build-arg",
        "PIP_INDEX_URL=https://pypi.example.invalid/simple",
        "--build-arg",
        "PIP_DEFAULT_TIMEOUT=300",
        "--pull",
        "-f",
        "docker/sandbox.Dockerfile",
        "-t",
        "focus-agent-sandbox:managed",
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


def test_sandbox_image_cli_check_only_reports_supplied_registry_build_arguments(capsys) -> None:
    module = _load_module()

    def fake_runner(command, **_kwargs):
        if command[:2] == ["docker", "version"]:
            return module.CommandResult(returncode=0, stdout="18.09.1\n", stderr="")
        if command[:3] == ["docker", "image", "inspect"]:
            return module.CommandResult(returncode=1, stdout="", stderr="No such image")
        raise AssertionError(f"unexpected command: {command}")

    exit_code = module.main(
        [
            "--check-only",
            "--npm-registry",
            "https://npm.example.invalid",
            "--pip-index-url",
            "https://pypi.example.invalid/simple",
            "--pip-default-timeout",
            "300",
        ],
        runner=fake_runner,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "NPM_REGISTRY=https://npm.example.invalid" in captured.err
    assert "PIP_INDEX_URL=https://pypi.example.invalid/simple" in captured.err
    assert "PIP_DEFAULT_TIMEOUT=300" in captured.err


def test_sandbox_image_cli_rejects_non_positive_pip_default_timeout(capsys) -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as exc_info:
        module.main(["--pip-default-timeout", "0"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "--pip-default-timeout: must be a positive integer" in captured.err


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
