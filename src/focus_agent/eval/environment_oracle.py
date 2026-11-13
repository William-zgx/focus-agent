"""Candidate-scoped environment oracles for deterministic eval checks."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from ..capabilities.sandbox_execution import SandboxExecutionRequest
from ..capabilities.sandbox_execution_backends import (
    SandboxExecutionService,
    default_sandbox_execution_service,
)

if TYPE_CHECKING:
    from .schema import EvalCase

OracleStatus = Literal["passed", "failed", "environment_invalid"]
_DEFAULT_TIMEOUT_S = 30
_MAX_OUTPUT_CHARS = 20_000
_COMMAND_EXIT_MARKER = "__FOCUS_AGENT_ORACLE_COMMAND_EXIT__"
_RESERVED_ORACLE_FILES = frozenset(
    {".candidate.patch", ".command.stdout", ".command.stderr", "__oracle_driver__.py"}
)
_DRIVER = """\
import shutil
import subprocess
import sys
from pathlib import Path

_COMMAND_EXIT_MARKER = "__FOCUS_AGENT_ORACLE_COMMAND_EXIT__"
_RESERVED = {".candidate.patch", ".command.stdout", ".command.stderr", "__oracle_driver__.py"}


class UnsafeCandidatePath(Exception):
    pass


def overlay_destination(root, relative):
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise UnsafeCandidatePath(f"candidate oracle path contains a symlink: {relative}")
    return current


def replay(path, destination):
    with path.open("rb") as source:
        shutil.copyfileobj(source, destination)


def main():
    try:
        initialized = subprocess.run(["git", "init", "-q"], capture_output=True, text=True)
        if initialized.returncode:
            sys.stderr.write(initialized.stderr)
            return 3
        patch_text = Path("../oracle/.candidate.patch").read_text(encoding="utf-8")
        if patch_text.strip():
            applied = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "../oracle/.candidate.patch"],
                capture_output=True,
                text=True,
            )
            if applied.returncode:
                sys.stderr.write(applied.stderr)
                return 2
        oracle_root = Path("../oracle")
        for source in oracle_root.rglob("*"):
            if not source.is_file() or source.relative_to(oracle_root).as_posix() in _RESERVED:
                continue
            relative = source.relative_to(oracle_root)
            destination = overlay_destination(Path.cwd(), relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        stdout_path = oracle_root / ".command.stdout"
        stderr_path = oracle_root / ".command.stderr"
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            completed = subprocess.run(sys.argv[1:], stdout=stdout_file, stderr=stderr_file)
    except UnsafeCandidatePath as exc:
        sys.stderr.write(str(exc))
        return 2
    except (OSError, shutil.Error) as exc:
        sys.stderr.write(f"oracle setup or command launch failed: {exc}")
        return 3
    sys.stdout.buffer.write(f"{_COMMAND_EXIT_MARKER}{completed.returncode}\\n".encode("ascii"))
    sys.stdout.buffer.flush()
    replay(stdout_path, sys.stdout.buffer)
    replay(stderr_path, sys.stderr.buffer)
    return 0 if completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""


@dataclass(frozen=True, slots=True)
class EnvironmentOracleResult:
    status: OracleStatus
    reason: str
    stdout: str = ""
    stderr: str = ""
    environment: dict[str, object] = field(default_factory=dict)
    command: dict[str, object] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


class EnvironmentOracle(Protocol):
    def validate(
        self, *, case: EvalCase, candidate_patch: str = ""
    ) -> EnvironmentOracleResult | None: ...


def run_environment_oracle(
    case: EvalCase,
    *,
    candidate_patch: str = "",
    oracle: EnvironmentOracle | None = None,
) -> EnvironmentOracleResult | None:
    environment = case.environment or {}
    if "oracle" not in environment or environment["oracle"] is None:
        return None
    implementation = oracle if oracle is not None else WorkspaceCommandOracle()
    return implementation.validate(case=case, candidate_patch=candidate_patch)


class WorkspaceCommandOracle:
    """Apply a unified diff, then overlay independent oracle files and run checks."""

    def __init__(self, sandbox: SandboxExecutionService | None = None) -> None:
        self._sandbox = sandbox

    def validate(
        self, *, case: EvalCase, candidate_patch: str = ""
    ) -> EnvironmentOracleResult | None:
        config = case.environment.get("oracle")
        environment: dict[str, object] = {
            "type": "workspace_command",
            "temporary_workspace": True,
        }
        command: dict[str, object] = {
            "argv": [],
            "cwd": "candidate",
            "exit_code": None,
            "timeout_s": _DEFAULT_TIMEOUT_S,
        }
        if not isinstance(config, Mapping):
            return _invalid("oracle config must be a mapping", environment, command)
        if config.get("type", "workspace_command") != "workspace_command":
            return _invalid("unsupported oracle type", environment, command)
        try:
            candidate_files = _normalized_manifest(config.get("files"), "files")
            oracle_files = _normalized_manifest(config.get("oracle_files"), "oracle_files")
        except ValueError as exc:
            return _invalid(str(exc), environment, command)
        overlap = sorted(candidate_files.keys() & oracle_files.keys())
        if overlap or _RESERVED_ORACLE_FILES & oracle_files.keys():
            return _invalid(
                "oracle file paths overlap candidate or reserved paths", environment, command
            )
        environment["files"] = sorted(candidate_files)
        environment["oracle_files"] = sorted(oracle_files)

        argv = config.get("command")
        if (
            not isinstance(argv, Sequence)
            or isinstance(argv, (str, bytes, bytearray))
            or not argv
            or not all(isinstance(item, str) and item and "\x00" not in item for item in argv)
        ):
            return _invalid("oracle command must be a non-empty string list", environment, command)
        command["argv"] = list(argv)

        timeout_s = config.get("timeout_s", _DEFAULT_TIMEOUT_S)
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or timeout_s < 1:
            return _invalid("oracle timeout_s must be a positive integer", environment, command)
        command["timeout_s"] = timeout_s
        max_output_chars = config.get("max_output_chars", _MAX_OUTPUT_CHARS)
        if (
            isinstance(max_output_chars, bool)
            or not isinstance(max_output_chars, int)
            or max_output_chars < 100
        ):
            return _invalid("max_output_chars must be at least 100", environment, command)
        command["max_output_chars"] = max_output_chars
        patch_text = _candidate_patch_text(candidate_patch)

        try:
            with tempfile.TemporaryDirectory(prefix="focus-agent-env-oracle-") as temp_dir:
                workspace = Path(temp_dir)
                candidate = workspace / "candidate"
                oracle_root = workspace / "oracle"
                candidate.mkdir()
                oracle_root.mkdir()
                _write_manifest(candidate, candidate_files)
                _write_manifest(oracle_root, oracle_files)
                (oracle_root / ".candidate.patch").write_text(patch_text, encoding="utf-8")
                (oracle_root / "__oracle_driver__.py").write_text(_DRIVER, encoding="utf-8")
                request = SandboxExecutionRequest(
                    workspace_root=workspace,
                    command=[
                        "python3",
                        "-I",
                        "-B",
                        "../oracle/__oracle_driver__.py",
                        *argv,
                    ],
                    cwd="candidate",
                    timeout_seconds=timeout_s,
                    max_output_chars=max_output_chars,
                    allow_network=False,
                    env={
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONHASHSEED": "0",
                        "ORACLE_CANDIDATE_ROOT": ".",
                    },
                    workspace_mode="copy_discard",
                )
                sandbox = (
                    self._sandbox
                    if self._sandbox is not None
                    else default_sandbox_execution_service(allow_fallback=False)
                )
                completed = sandbox.run(request)
        except Exception as exc:  # noqa: BLE001 - backend failures are not Agent failures
            return _invalid(f"oracle could not run safely: {exc}", environment, command)

        payload = completed.to_payload()
        environment.update(
            {
                "sandbox_backend": payload.get("sandbox_backend"),
                "workspace_mode": payload.get("workspace_mode"),
                "network_policy": payload.get("network_policy"),
                "fallback_used": payload.get("fallback_used", False),
                "degraded_reason": payload.get("degraded_reason"),
            }
        )
        stdout, command_exit_code = _command_result(completed.stdout)
        command["exit_code"] = command_exit_code
        command["driver_exit_code"] = completed.exit_code
        if completed.timed_out:
            return _invalid(
                f"oracle command timed out after {timeout_s}s",
                environment,
                command,
                stdout=stdout,
                stderr=completed.stderr,
            )
        if completed.exit_code == 3:
            return _invalid(
                "oracle setup or command launch failed",
                environment,
                command,
                stdout=stdout,
                stderr=completed.stderr,
            )
        if completed.exit_code == 2:
            return EnvironmentOracleResult(
                status="failed",
                reason="candidate patch or oracle overlay could not be applied safely",
                stdout=stdout,
                stderr=completed.stderr,
                environment=environment,
                command=command,
            )
        if command_exit_code is None:
            return _invalid("oracle driver did not return command status", environment, command)
        if completed.exit_code != 0:
            return EnvironmentOracleResult(
                status="failed",
                reason=f"workspace command exited with code {command_exit_code}",
                stdout=stdout,
                stderr=completed.stderr,
                environment=environment,
                command=command,
            )
        if command_exit_code != 0:
            return _invalid(
                "oracle driver returned inconsistent command status", environment, command
            )
        return EnvironmentOracleResult(
            status="passed",
            reason="workspace command passed",
            stdout=stdout,
            stderr=completed.stderr,
            environment=environment,
            command=command,
        )


def _normalized_manifest(manifest: object, label: str) -> dict[str, str]:
    if not isinstance(manifest, Mapping) or not manifest:
        raise ValueError(f"oracle {label} must be a non-empty mapping")
    normalized: dict[str, str] = {}
    for name, content in manifest.items():
        if not isinstance(name, str) or not _is_relative_file(name) or not isinstance(content, str):
            raise ValueError(f"oracle {label} must map relative file paths to text")
        destination = Path(name).as_posix()
        if destination in normalized:
            raise ValueError(f"oracle {label} paths must be unique")
        normalized[destination] = content
    return normalized


def _write_manifest(root: Path, files: Mapping[str, str]) -> None:
    for name, content in files.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _command_result(stdout: str) -> tuple[str, int | None]:
    match = re.match(rf"\A{re.escape(_COMMAND_EXIT_MARKER)}(-?\d+)\n", stdout)
    if match is None:
        return stdout, None
    return stdout[match.end() :], int(match.group(1))


def _candidate_patch_text(answer: str) -> str:
    text = str(answer or "")
    matches = list(re.finditer(r"```(?:diff|patch)[ \t]*\n(.*?)```", text, flags=re.DOTALL))
    if matches:
        return "".join(
            match.group(1) + ("" if match.group(1).endswith("\n") else "\n") for match in matches
        )
    return text + ("\n" if text and not text.endswith("\n") else "")


def _invalid(
    reason: str,
    environment: dict[str, object],
    command: dict[str, object],
    *,
    stdout: str = "",
    stderr: str = "",
) -> EnvironmentOracleResult:
    return EnvironmentOracleResult(
        status="environment_invalid",
        reason=reason,
        stdout=stdout,
        stderr=stderr,
        environment=environment,
        command=command,
    )


def _is_relative_file(name: str) -> bool:
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    path = Path(name)
    return (
        bool(name)
        and "\x00" not in name
        and path != Path(".")
        and not path.is_absolute()
        and ".." not in path.parts
    )


__all__ = [
    "EnvironmentOracle",
    "EnvironmentOracleResult",
    "WorkspaceCommandOracle",
    "run_environment_oracle",
]
