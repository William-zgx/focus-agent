#!/usr/bin/env python3

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_IMAGE = "focus-agent-sandbox:latest"
DEFAULT_BASE_IMAGE = "node:20-bookworm-slim"
DEFAULT_DOCKERFILE = Path("docker/sandbox.Dockerfile")
DEFAULT_CONTEXT = Path(".")
MIN_DOCKER_VERSION = (18, 9, 0)


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., CommandResult | subprocess.CompletedProcess[str]]


def build_sandbox_image_command(
    *,
    docker_binary: str,
    image: str,
    dockerfile: Path,
    context: Path,
    base_image: str | None,
    apt_mirror: str | None,
    apt_security_mirror: str | None,
    pull: bool,
    npm_registry: str | None = None,
    pip_index_url: str | None = None,
    pip_default_timeout: int | None = None,
) -> list[str]:
    command = [
        docker_binary,
        "build",
        "--build-arg",
        f"BASE_IMAGE={base_image or DEFAULT_BASE_IMAGE}",
    ]
    if apt_mirror:
        command.extend(["--build-arg", f"APT_MIRROR={apt_mirror}"])
    if apt_security_mirror:
        command.extend(["--build-arg", f"APT_SECURITY_MIRROR={apt_security_mirror}"])
    if npm_registry is not None:
        command.extend(["--build-arg", f"NPM_REGISTRY={npm_registry}"])
    if pip_index_url is not None:
        command.extend(["--build-arg", f"PIP_INDEX_URL={pip_index_url}"])
    if pip_default_timeout is not None:
        command.extend(["--build-arg", f"PIP_DEFAULT_TIMEOUT={pip_default_timeout}"])
    if pull:
        command.append("--pull")
    command.extend(["-f", str(dockerfile), "-t", image, str(context)])
    return command


def main(argv: Sequence[str] | None = None, *, runner: Runner | None = None) -> int:
    args = _parse_args(argv)
    run = runner or _run_command
    version_result = _coerce_result(
        run(
            [args.docker_binary, "version", "--format", "{{.Server.Version}}"],
            timeout=10,
        )
    )
    if version_result.returncode != 0:
        print(
            f"Docker server is unavailable: {version_result.stderr or version_result.stdout}",
            file=sys.stderr,
        )
        return 2

    version_text = version_result.stdout.strip()
    version = parse_docker_version(version_text)
    if version is None or version < MIN_DOCKER_VERSION:
        print(
            f"Docker server {version_text or 'unknown'} is older than supported minimum "
            f"{_format_version(MIN_DOCKER_VERSION)}.",
            file=sys.stderr,
        )
        return 2

    inspect_result = _coerce_result(
        run(
            [args.docker_binary, "image", "inspect", args.image],
            timeout=10,
        )
    )
    if inspect_result.returncode == 0:
        print(f"Sandbox image {args.image} is available.")
        return 0

    build_command = build_sandbox_image_command(
        docker_binary=args.docker_binary,
        image=args.image,
        dockerfile=args.dockerfile,
        context=args.context,
        base_image=args.base_image,
        apt_mirror=args.apt_mirror,
        apt_security_mirror=args.apt_security_mirror,
        pull=args.pull,
        npm_registry=args.npm_registry,
        pip_index_url=args.pip_index_url,
        pip_default_timeout=args.pip_default_timeout,
    )
    friendly_command = " ".join(build_command)
    script_command = f"python scripts/ensure_sandbox_image.py --image {args.image}"
    if args.check_only or args.no_build:
        print(
            f"Sandbox image {args.image} is missing. Run `{script_command}` or `{friendly_command}`.",
            file=sys.stderr,
        )
        return 1

    print(f"Sandbox image {args.image} is missing; building with: {friendly_command}")
    build_result = _coerce_result(run(build_command, timeout=args.timeout_seconds))
    if build_result.returncode != 0:
        print(build_result.stderr or build_result.stdout, file=sys.stderr)
        return build_result.returncode or 1
    print(f"Sandbox image {args.image} is ready.")
    return 0


def parse_docker_version(value: str) -> tuple[int, int, int] | None:
    parts: list[int] = []
    for raw_part in value.strip().split("."):
        digits = ""
        for char in raw_part:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
        if len(parts) == 3:
            break
    if not parts:
        return None
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # type: ignore[return-value]


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check or build the Focus Agent sandbox execution image.",
    )
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--dockerfile", type=Path, default=DEFAULT_DOCKERFILE)
    parser.add_argument("--context", type=Path, default=DEFAULT_CONTEXT)
    parser.add_argument("--base-image", default=None)
    parser.add_argument("--apt-mirror", default=None)
    parser.add_argument("--apt-security-mirror", default=None)
    parser.add_argument("--npm-registry", default=None)
    parser.add_argument("--pip-index-url", default=None)
    parser.add_argument("--pip-default-timeout", type=_positive_int, default=None)
    parser.add_argument("--docker-binary", default="docker")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    return parser.parse_args(argv)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _run_command(command: list[str], *, timeout: int) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(returncode=127, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=_coerce_output(exc.stdout),
            stderr=_coerce_output(exc.stderr) or f"Timed out after {timeout} seconds.",
        )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _coerce_result(result: CommandResult | subprocess.CompletedProcess[str]) -> CommandResult:
    if isinstance(result, CommandResult):
        return result
    return CommandResult(
        returncode=result.returncode,
        stdout=_coerce_output(result.stdout),
        stderr=_coerce_output(result.stderr),
    )


def _coerce_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _format_version(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    return f"{major}.{minor:02d}.{patch}"


if __name__ == "__main__":
    raise SystemExit(main())
