from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

_FORBIDDEN_COMMAND_TOKENS = {
    "add",
    "create",
    "dlx",
    "exec",
    "install",
    "remove",
    "run-script",
    "shell",
    "uninstall",
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
_SAFE_VERSION_FLAGS = {"--version", "-V", "-v"}
_PACKAGE_SCRIPT_COMMANDS = {
    "a11y:baseline",
    "build",
    "check",
    "lint",
    "style:check",
    "test",
    "validate:transport",
}
_MAKE_TARGETS = {
    "architecture-report",
    "check",
    "ci",
    "ci-test",
    "contract-check",
    "format-check",
    "frontend-check",
    "frontend-check-full",
    "lint",
    "lint-strict",
    "openapi-export",
    "production-smoke",
    "sdk-build",
    "sdk-check",
    "sdk-openapi-types-check",
    "sdk-validate-transport",
    "test",
    "test-chat-service",
    "test-graph-builder",
    "test-thread-stream-frontend-regressions",
    "ui-smoke",
    "ui-smoke-agent-team-adoption",
    "ui-smoke-observability",
    "ui-smoke-productivity",
    "web-build",
    "web-check",
    "web-format-check",
    "web-format-check-full",
    "web-lint",
    "web-lint-full",
}
_UV_RUN_COMMANDS = {"mypy", "pytest", "ruff"}
_DIRECT_COMMANDS = {"mypy", "pytest", "ruff"}
_LANGUAGE_TEST_COMMANDS = {"cargo": "test", "go": "test"}

WorkspacePathResolver = Callable[[str], Path]


def normalize_command(command: object) -> list[str]:
    if not isinstance(command, list) or not command:
        raise ValueError("command must be a non-empty list of arguments.")
    normalized = [str(item) for item in command]
    if any(not item.strip() for item in normalized):
        raise ValueError("command arguments must not be empty.")
    return normalized


def allowed_command_names(raw: object) -> set[str]:
    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}
    if isinstance(raw, (list, tuple, set)):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _command_base(command: Sequence[str]) -> str:
    return Path(command[0]).name


def _has_forbidden_command_token(command: Sequence[str]) -> bool:
    return any(token.strip().lower() in _FORBIDDEN_COMMAND_TOKENS for token in command[1:])


def _package_command_allowed(command: Sequence[str]) -> bool:
    if _has_forbidden_command_token(command):
        return False
    if "run" in command:
        index = command.index("run")
        return len(command) > index + 1 and command[index + 1] in _PACKAGE_SCRIPT_COMMANDS
    return any(token in _PACKAGE_SCRIPT_COMMANDS for token in command[1:])


def _make_command_allowed(command: Sequence[str]) -> bool:
    if len(command) < 2:
        return False
    if any(token.startswith("-") for token in command[1:]):
        return False
    return all(token in _MAKE_TARGETS for token in command[1:])


def _uv_command_allowed(command: Sequence[str]) -> bool:
    if len(command) < 3 or command[1] != "run":
        return False
    if _has_forbidden_command_token(command):
        return False
    uv_command = Path(command[2]).name
    if uv_command == "ruff":
        return _ruff_command_allowed([uv_command, *command[3:]])
    return uv_command in _UV_RUN_COMMANDS


def _ruff_command_allowed(command: Sequence[str]) -> bool:
    if len(command) == 2 and command[1] in _SAFE_VERSION_FLAGS:
        return True
    if len(command) < 2:
        return False
    subcommand = command[1]
    args = command[2:]
    if subcommand == "check":
        return not any(arg in {"--fix", "--fix-only", "--unsafe-fixes"} for arg in args)
    if subcommand == "format":
        return "--check" in args
    return False


def workspace_command_allowed(command: Sequence[str], allowed_commands: set[str]) -> bool:
    base = _command_base(command)
    if base not in allowed_commands:
        return False
    if base == "ruff":
        return _ruff_command_allowed(command)
    if base in _DIRECT_COMMANDS:
        return True
    if base == "uv":
        return _uv_command_allowed(command)
    if base in {"npm", "pnpm"}:
        return _package_command_allowed(command)
    if base == "make":
        return _make_command_allowed(command)
    if base in _LANGUAGE_TEST_COMMANDS:
        return len(command) >= 2 and command[1] == _LANGUAGE_TEST_COMMANDS[base]
    return False


def _command_arg_path_candidate(argument: str) -> str | None:
    value = argument.strip()
    if not value:
        return None
    if value.startswith("-"):
        if "=" not in value:
            return None
        value = value.split("=", 1)[1].strip()
    if "::" in value:
        value = value.split("::", 1)[0]
    if _looks_like_scoped_package_name(value):
        return None
    if (
        value in {".", ".."}
        or value.startswith(("/", "./", "../", "~"))
        or "/" in value
        or "\\" in value
    ):
        return value
    return None


def _looks_like_scoped_package_name(value: str) -> bool:
    if not value.startswith("@") or value.count("/") != 1:
        return False
    scope, package = value.split("/", 1)
    if len(scope) <= 1 or not package:
        return False
    return not package.startswith((".", "/")) and "\\" not in package


def validate_command_paths(
    command: Sequence[str], *, resolve_path: WorkspacePathResolver
) -> None:
    for argument in command[1:]:
        path = _command_arg_path_candidate(argument)
        if path is None:
            continue
        resolve_path(path)


def resolve_command_executable(
    command: Sequence[str], *, resolve_path: WorkspacePathResolver
) -> list[str]:
    executable = command[0]
    if "/" not in executable and "\\" not in executable:
        return list(command)
    resolved = resolve_path(executable)
    if not resolved.exists():
        raise FileNotFoundError(executable)
    if not resolved.is_file():
        raise IsADirectoryError(executable)
    return [str(resolved), *command[1:]]


def workspace_command_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        normalized_key = key.upper()
        if any(marker in normalized_key for marker in _SENSITIVE_ENV_NAME_MARKERS):
            continue
        env[key] = value
    env["FOCUS_AGENT_WORKSPACE_COMMAND"] = "1"
    return env


__all__ = [
    "allowed_command_names",
    "normalize_command",
    "resolve_command_executable",
    "validate_command_paths",
    "workspace_command_allowed",
    "workspace_command_env",
]
