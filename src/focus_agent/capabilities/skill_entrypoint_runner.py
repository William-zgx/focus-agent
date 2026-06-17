from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
import venv
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..skills.models import SkillDefinition, SkillEntrypoint
from .default_tool_modules.workspace_command import workspace_command_env
from .sandbox_execution import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    default_sandbox_execution_service,
)

_PYTHON_NAMES = {"python", "python3"}
_DEFAULT_TIMEOUT_SECONDS = 60
_MAX_TIMEOUT_SECONDS = 600
_MAX_OUTPUT_CHARS = 20_000
_DEFAULT_MEMORY_MB = 1024
_MAX_MEMORY_MB = 8192
_ARGUMENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_VENV_MARKER = ".focus-agent-venv.json"
_MAX_OUTPUT_FILES = 200
_MAX_OUTPUT_BYTES = 50 * 1024 * 1024
_MAX_FILE_BYTES = 512 * 1024 * 1024
_MAX_PROCESSES = 1024


def run_skill_entrypoint_in_sandbox_service(
    *,
    workspace_root: Path,
    skill: SkillDefinition,
    entrypoint_name: str,
    arguments: Mapping[str, Any] | None = None,
    thread_id: str | None = None,
    branch_id: str | None = None,
) -> str:
    entrypoint = _entrypoint_for(skill, entrypoint_name)
    skill_dir = skill.path.parent.expanduser().resolve()
    workspace = workspace_root.expanduser().resolve()
    _validated_script_path(
        entrypoint=entrypoint,
        skill_dir=skill_dir,
    )
    try:
        cwd = skill_dir.relative_to(workspace).as_posix()
    except ValueError as exc:
        raise ValueError("Skill entrypoint path must stay inside the workspace.") from exc
    timeout_seconds = _resolved_timeout(entrypoint.timeout_seconds)
    memory_mb = _resolved_memory_mb(entrypoint.memory_mb)
    try:
        dependencies = _validated_dependencies(entrypoint.dependencies)
    except RuntimeError as exc:
        run_id = uuid.uuid4().hex
        return json.dumps(
            {
                "status": "dependency_error",
                "skill_id": skill.skill_id,
                "entrypoint": entrypoint.name,
                "run_id": run_id,
                "exit_code": None,
                "timed_out": False,
                "timeout_seconds": timeout_seconds,
                "memory_mb": memory_mb,
                "stdout": "",
                "stderr": str(exc),
                "stdout_truncated": False,
                "stderr_truncated": False,
                "outputs": [],
                "outputs_truncated": False,
                "duration_ms": 0.0,
                "sandbox_backend": "none",
                "sandbox_id": None,
                "fallback_used": False,
                "workspace_mode": "thread_persistent_copy",
                "network_policy": "bridge" if entrypoint.network else "none",
                "resource_limits": {"memory_mb": memory_mb},
                "network": entrypoint.network,
            },
            ensure_ascii=False,
        )
    command = [
        *entrypoint.command,
        *_arguments_to_argv(
            arguments or {},
            reserved_flags=(entrypoint.output_dir_arg,) if entrypoint.output_dir_arg else (),
        ),
    ]
    service = default_sandbox_execution_service(
        fallback_backend=_LocalVenvSkillEntrypointBackend(
            workspace_root=workspace,
            skill=skill,
            entrypoint_name=entrypoint.name,
            arguments=arguments or {},
        )
    )
    result = service.run(
        SandboxExecutionRequest(
            workspace_root=workspace,
            command=command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_chars=_MAX_OUTPUT_CHARS,
            allow_network=entrypoint.network,
            memory_mb=memory_mb,
            env={},
            tool_name="run_skill_entrypoint",
            skill_id=skill.skill_id,
            entrypoint=entrypoint.name,
            dependencies=dependencies,
            output_dir_arg=entrypoint.output_dir_arg,
            thread_id=thread_id,
            branch_id=branch_id,
        )
    )
    payload = result.to_payload()
    payload["network"] = entrypoint.network
    return json.dumps(payload, ensure_ascii=False)


def run_skill_entrypoint_in_local_venv(
    *,
    workspace_root: Path,
    skill: SkillDefinition,
    entrypoint_name: str,
    arguments: Mapping[str, Any] | None = None,
) -> str:
    return run_skill_entrypoint_in_sandbox_service(
        workspace_root=workspace_root,
        skill=skill,
        entrypoint_name=entrypoint_name,
        arguments=arguments,
    )


class _LocalVenvSkillEntrypointBackend:
    backend_name = "local_venv"

    def __init__(
        self,
        *,
        workspace_root: Path,
        skill: SkillDefinition,
        entrypoint_name: str,
        arguments: Mapping[str, Any],
    ) -> None:
        self.workspace_root = workspace_root
        self.skill = skill
        self.entrypoint_name = entrypoint_name
        self.arguments = arguments

    def run(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        payload = json.loads(
            _run_skill_entrypoint_in_local_venv(
                workspace_root=self.workspace_root,
                skill=self.skill,
                entrypoint_name=self.entrypoint_name,
                arguments=self.arguments,
            )
        )
        return SandboxExecutionResult(
            status=str(payload.get("status") or "failed"),
            command=list(request.command),
            cwd=request.cwd,
            exit_code=payload.get("exit_code") if isinstance(payload.get("exit_code"), int) else None,
            timed_out=bool(payload.get("timed_out", False)),
            timeout_seconds=int(payload.get("timeout_seconds") or request.timeout_seconds),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            stdout_truncated=bool(payload.get("stdout_truncated", False)),
            stderr_truncated=bool(payload.get("stderr_truncated", False)),
            outputs=list(payload.get("outputs") or []),
            outputs_truncated=bool(payload.get("outputs_truncated", False)),
            duration_ms=float(payload.get("duration_ms") or 0.0),
            sandbox_backend="local_venv",
            run_id=str(payload.get("run_id") or ""),
            policy={
                "backend": "local_venv",
                "network": "host",
                "workspace": "host",
                "fallback": True,
            },
            skill_id=self.skill.skill_id,
            entrypoint=self.entrypoint_name,
            memory_mb=payload.get("memory_mb") if isinstance(payload.get("memory_mb"), int) else None,
            sandbox_id=request.sandbox_id,
            fallback_used=True,
            workspace_mode="host",
            network_policy="host",
            resource_limits={},
        )


def _run_skill_entrypoint_in_local_venv(
    *,
    workspace_root: Path,
    skill: SkillDefinition,
    entrypoint_name: str,
    arguments: Mapping[str, Any] | None = None,
) -> str:
    entrypoint = _entrypoint_for(skill, entrypoint_name)
    skill_dir = skill.path.parent.expanduser().resolve()
    workspace = workspace_root.expanduser().resolve()
    script_path = _validated_script_path(
        entrypoint=entrypoint,
        skill_dir=skill_dir,
    )
    sandbox_root = workspace / ".focus_agent" / "sandboxes" / skill.skill_id
    venv_dir = sandbox_root / "venv"
    runs_root = sandbox_root / "runs"
    run_id = uuid.uuid4().hex
    run_dir = runs_root / run_id
    _prepare_sandbox_root(sandbox_root=sandbox_root, workspace_root=workspace)
    run_dir.mkdir(parents=True, exist_ok=True)
    _assert_no_symlink_components(run_dir, root=workspace)
    started = time.monotonic()

    try:
        python_path = _ensure_venv(
            venv_dir=venv_dir,
            dependencies=entrypoint.dependencies,
        )
    except RuntimeError as exc:
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        return json.dumps(
            {
                "status": "dependency_error",
                "skill_id": skill.skill_id,
                "entrypoint": entrypoint.name,
                "run_id": run_id,
                "exit_code": None,
                "timed_out": False,
                "timeout_seconds": _MAX_TIMEOUT_SECONDS,
                "memory_mb": _resolved_memory_mb(entrypoint.memory_mb),
                "stdout": "",
                "stderr": str(exc),
                "stdout_truncated": False,
                "stderr_truncated": False,
                "outputs": [],
                "outputs_truncated": False,
                "duration_ms": duration_ms,
                "sandbox_backend": "local_venv",
                "network": entrypoint.network,
            },
            ensure_ascii=False,
        )
    timeout_seconds = _resolved_timeout(entrypoint.timeout_seconds)
    memory_mb = _resolved_memory_mb(entrypoint.memory_mb)
    command = [
        str(python_path),
        str(script_path),
        *entrypoint.command[2:],
        *_arguments_to_argv(
            arguments or {},
            reserved_flags=(entrypoint.output_dir_arg,) if entrypoint.output_dir_arg else (),
        ),
    ]
    if entrypoint.output_dir_arg:
        command.extend([entrypoint.output_dir_arg, str(run_dir)])

    env = _skill_runtime_env(
        venv_dir=venv_dir,
        run_dir=run_dir,
        python_path=python_path,
    )

    timed_out = False
    exit_code, stdout, stderr, timed_out = _run_entrypoint_process(
        command=command,
        cwd=skill_dir,
        env=env,
        timeout_seconds=timeout_seconds,
        memory_mb=memory_mb,
    )

    duration_ms = round((time.monotonic() - started) * 1000, 3)
    stdout, stdout_truncated = _trim_output(stdout)
    stderr, stderr_truncated = _trim_output(stderr)
    outputs, outputs_truncated = _run_outputs(run_dir=run_dir, workspace_root=workspace)
    payload = {
        "status": "timeout" if timed_out else ("completed" if exit_code == 0 else "failed"),
        "skill_id": skill.skill_id,
        "entrypoint": entrypoint.name,
        "run_id": run_id,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "memory_mb": memory_mb,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "outputs": outputs,
        "outputs_truncated": outputs_truncated,
        "duration_ms": duration_ms,
        "sandbox_backend": "local_venv",
        "network": entrypoint.network,
    }
    return json.dumps(payload, ensure_ascii=False)


def _entrypoint_for(skill: SkillDefinition, name: str) -> SkillEntrypoint:
    normalized = str(name or "").strip()
    for entrypoint in skill.entrypoints:
        if entrypoint.name == normalized:
            return entrypoint
    raise ValueError(f"Skill '{skill.skill_id}' has no declared entrypoint '{normalized}'.")


def _validated_script_path(*, entrypoint: SkillEntrypoint, skill_dir: Path) -> Path:
    command = list(entrypoint.command)
    if len(command) < 2:
        raise ValueError("Skill entrypoint command must include a Python script path.")
    command_name = Path(command[0]).name
    if command_name not in _PYTHON_NAMES or "/" in command[0] or "\\" in command[0]:
        raise ValueError("Skill entrypoint command must use python or python3.")
    script_arg = str(command[1] or "").strip()
    if not script_arg or script_arg.startswith("-"):
        raise ValueError("Skill entrypoint command must reference a script file.")
    script_candidate = Path(script_arg)
    if script_candidate.is_absolute():
        raise ValueError("Skill entrypoint script path must be relative.")
    script_path = (skill_dir / script_candidate).resolve()
    try:
        relative = script_path.relative_to(skill_dir)
    except ValueError as exc:
        raise ValueError("Skill entrypoint script must stay inside the skill directory.") from exc
    if relative.parts[:1] != ("scripts",) or script_path.suffix != ".py":
        raise ValueError("Skill entrypoint script must be a Python file under scripts/.")
    if not script_path.is_file():
        raise FileNotFoundError(script_arg)
    return script_path


def _ensure_venv(*, venv_dir: Path, dependencies: tuple[str, ...]) -> Path:
    validated_dependencies = _validated_dependencies(dependencies)
    python_path = _venv_python(venv_dir)
    if _venv_needs_rebuild(venv_dir=venv_dir, python_path=python_path):
        if venv_dir.exists() or venv_dir.is_symlink():
            _safe_rmtree(venv_dir)
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        _write_venv_marker(venv_dir)
    if validated_dependencies:
        deps_hash = hashlib.sha256(
            "\n".join(validated_dependencies).encode("utf-8")
        ).hexdigest()
        marker = venv_dir / f".focus-agent-deps-{deps_hash}"
        if not marker.exists():
            completed = subprocess.run(
                [str(python_path), "-m", "pip", "install", *validated_dependencies],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_MAX_TIMEOUT_SECONDS,
                env=workspace_command_env(),
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise RuntimeError(f"Skill dependency install failed: {detail}")
            marker.write_text("ok\n", encoding="utf-8")
    return python_path


def _venv_needs_rebuild(*, venv_dir: Path, python_path: Path) -> bool:
    if venv_dir.is_symlink():
        raise RuntimeError("Skill sandbox venv path must not be a symlink.")
    if not venv_dir.exists():
        return True
    return not (
        python_path.exists()
        and (venv_dir / "pyvenv.cfg").is_file()
        and (venv_dir / _VENV_MARKER).is_file()
    )


def _write_venv_marker(venv_dir: Path) -> None:
    marker = {
        "created_by": "focus-agent",
        "backend": "local_venv",
        "version": 1,
    }
    (venv_dir / _VENV_MARKER).write_text(
        json.dumps(marker, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_rmtree(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError("Refusing to remove symlinked skill sandbox path.")
    shutil.rmtree(path)


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _skill_runtime_env(*, venv_dir: Path, run_dir: Path, python_path: Path) -> dict[str, str]:
    env = workspace_command_env()
    for key in list(env):
        normalized = key.upper()
        if normalized == "PYTHONPATH" or normalized.startswith("PIP_"):
            env.pop(key, None)
    env["VIRTUAL_ENV"] = str(venv_dir)
    env["PATH"] = f"{python_path.parent}{os.pathsep}{env.get('PATH', '')}"
    env["HOME"] = str(run_dir)
    env["XDG_CACHE_HOME"] = str(run_dir / ".cache")
    env["PYTHONUNBUFFERED"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["NUMEXPR_NUM_THREADS"] = "1"
    return env


def _prepare_sandbox_root(*, sandbox_root: Path, workspace_root: Path) -> None:
    focus_dir = workspace_root / ".focus_agent"
    sandboxes_root = focus_dir / "sandboxes"
    _assert_no_symlink_components(focus_dir, root=workspace_root)
    focus_dir.mkdir(exist_ok=True)
    _assert_no_symlink_components(sandboxes_root, root=workspace_root)
    sandboxes_root.mkdir(mode=0o700, exist_ok=True)
    _assert_no_symlink_components(sandbox_root, root=workspace_root)
    sandbox_root.mkdir(mode=0o700, exist_ok=True)
    _chmod_private(sandboxes_root)
    _chmod_private(sandbox_root)


def _assert_no_symlink_components(path: Path, *, root: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("Skill sandbox path must stay inside the workspace.") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"Skill sandbox path must not contain symlinks: {current}")


def _chmod_private(path: Path) -> None:
    try:
        path.chmod(0o700)
    except OSError:
        return None


def _arguments_to_argv(
    arguments: Mapping[str, Any],
    *,
    reserved_flags: tuple[str | None, ...] = (),
) -> list[str]:
    reserved = {
        _normalize_argument_name(flag.removeprefix("--"))
        for flag in reserved_flags
        if flag
    }
    argv: list[str] = []
    for key, value in arguments.items():
        name = _normalize_argument_name(str(key))
        if not name:
            continue
        if name in reserved:
            continue
        if not _ARGUMENT_NAME_RE.fullmatch(name):
            raise ValueError(f"Unsafe skill entrypoint argument name: {key!r}.")
        flag = f"--{name}"
        if isinstance(value, bool):
            if value:
                argv.append(flag)
            continue
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                argv.extend([flag, str(item)])
            continue
        argv.extend([flag, str(value)])
    return argv


def _normalize_argument_name(value: str) -> str:
    return value.strip().replace("_", "-")


def _validated_dependencies(dependencies: tuple[str, ...]) -> tuple[str, ...]:
    validated: list[str] = []
    for raw_dependency in dependencies:
        dependency = str(raw_dependency).strip()
        if not dependency:
            continue
        if (
            dependency.startswith("-")
            or "/" in dependency
            or "\\" in dependency
            or any(char in dependency for char in "\r\n\t")
        ):
            raise RuntimeError(
                f"Unsafe skill dependency declaration: {raw_dependency!r}."
            )
        validated.append(dependency)
    return tuple(validated)


def _resolved_timeout(value: int | None) -> int:
    return max(1, min(int(value or _DEFAULT_TIMEOUT_SECONDS), _MAX_TIMEOUT_SECONDS))


def _resolved_memory_mb(value: int | None) -> int:
    return max(256, min(int(value or _DEFAULT_MEMORY_MB), _MAX_MEMORY_MB))


def _trim_output(value: str) -> tuple[str, bool]:
    if len(value) <= _MAX_OUTPUT_CHARS:
        return value, False
    return value[:_MAX_OUTPUT_CHARS], True


def _coerce_process_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _run_outputs(*, run_dir: Path, workspace_root: Path) -> tuple[list[dict[str, Any]], bool]:
    outputs: list[dict[str, Any]] = []
    total_bytes = 0
    truncated = False
    for path in sorted(run_dir.rglob("*")):
        if len(outputs) >= _MAX_OUTPUT_FILES:
            truncated = True
            break
        try:
            stat_result = path.lstat()
        except OSError:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        try:
            path.resolve().relative_to(run_dir)
        except ValueError:
            continue
        size_bytes = stat_result.st_size
        if total_bytes + size_bytes > _MAX_OUTPUT_BYTES:
            truncated = True
            break
        try:
            relative = path.relative_to(workspace_root).as_posix()
        except ValueError:
            relative = str(path)
        total_bytes += size_bytes
        outputs.append(
            {
                "path": relative,
                "size_bytes": size_bytes,
            }
        )
    return outputs, truncated


def _run_entrypoint_process(
    *,
    command: list[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
    memory_mb: int,
) -> tuple[int | None, str, str, bool]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        preexec_fn=_resource_limiter(timeout_seconds, memory_mb),
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        stdout, stderr = process.communicate()
        return None, _coerce_process_output(stdout), _coerce_process_output(stderr), True


def _resource_limiter(timeout_seconds: int, memory_mb: int):
    if os.name == "nt":
        return None

    def limit() -> None:
        try:
            import resource

            cpu_limit = max(1, int(timeout_seconds) + 5)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
            memory_limit = int(memory_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
            resource.setrlimit(resource.RLIMIT_FSIZE, (_MAX_FILE_BYTES, _MAX_FILE_BYTES))
            if hasattr(resource, "RLIMIT_NPROC"):
                resource.setrlimit(resource.RLIMIT_NPROC, (_MAX_PROCESSES, _MAX_PROCESSES))
        except Exception:
            return None

    return limit


__all__ = [
    "run_skill_entrypoint_in_local_venv",
    "run_skill_entrypoint_in_sandbox_service",
]
