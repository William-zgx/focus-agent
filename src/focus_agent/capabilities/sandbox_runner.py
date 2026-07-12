from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .sandbox_snapshot import _COPY_SKIP_NAMES, _sandbox_id_for_request

if TYPE_CHECKING:
    from .sandbox_execution import SandboxExecutionRequest, SandboxExecutionResult

_DEFAULT_MEMORY_MB = 1024
_DEFAULT_PIDS_LIMIT = 512
_MAX_OUTPUT_FILES = 200
_MAX_OUTPUT_BYTES = 50 * 1024 * 1024
_RUNNER_FILENAME = "sandbox_runner.py"
_REQUEST_FILENAME = "sandbox_request.json"
_RESULT_FILENAME = "result.json"
_DEFAULT_RUN_TTL_SECONDS = 7 * 24 * 60 * 60
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


def _result_from_parts(
    *,
    request: SandboxExecutionRequest,
    run_id: str,
    backend: str,
    exit_code: int | None,
    timed_out: bool,
    stdout: str,
    stderr: str,
    duration_ms: float,
    output_dir: Path | None,
    policy: dict[str, Any],
) -> SandboxExecutionResult:
    from .sandbox_execution import SandboxExecutionResult

    stdout, stdout_truncated = _trim_output(stdout, request.max_output_chars)
    stderr, stderr_truncated = _trim_output(stderr, request.max_output_chars)
    outputs, outputs_truncated = (
        _run_outputs(output_dir=output_dir, workspace_root=request.workspace_root)
        if output_dir is not None
        else ([], False)
    )
    status = "timeout" if timed_out else ("completed" if exit_code == 0 else "failed")
    network_policy = str(
        policy.get("network") or ("host" if backend.startswith("local") else "none")
    )
    workspace_mode = str(policy.get("workspace") or request.workspace_mode)
    degraded_reason = "local_host_execution" if backend.startswith("local") else None
    if degraded_reason:
        policy = {**policy, "degraded_reason": degraded_reason}
    memory_mb = int(request.memory_mb or _DEFAULT_MEMORY_MB)
    resource_limits: dict[str, Any] = {}
    if backend == "docker":
        resource_limits = {"memory_mb": memory_mb, "pids_limit": _DEFAULT_PIDS_LIMIT}
    elif request.memory_mb is not None:
        resource_limits = {"memory_mb": request.memory_mb}
    return SandboxExecutionResult(
        status=status,
        command=list(request.command),
        cwd=request.cwd,
        exit_code=exit_code,
        timed_out=timed_out,
        timeout_seconds=request.timeout_seconds,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        outputs=outputs,
        outputs_truncated=outputs_truncated,
        duration_ms=duration_ms,
        sandbox_backend=backend,
        run_id=run_id,
        policy=policy,
        skill_id=request.skill_id,
        entrypoint=request.entrypoint,
        memory_mb=request.memory_mb,
        sandbox_id=request.sandbox_id or _sandbox_id_for_request(request, run_id=run_id),
        fallback_used=bool(policy.get("fallback")) or backend.startswith("local"),
        workspace_mode=workspace_mode,
        network_policy=network_policy,
        resource_limits=resource_limits,
        degraded_reason=degraded_reason,
    )


def _write_runner(path: Path) -> None:
    template = r"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

INPUT = Path(os.environ.get("SANDBOX_INPUT", "/workspace_input"))
WORKSPACE = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace"))
OUTPUT = Path(os.environ.get("SANDBOX_OUTPUT", "/sandbox_output"))
CACHE = Path(os.environ.get("SANDBOX_CACHE", "/sandbox_cache"))
REQUEST = Path(os.environ.get("SANDBOX_REQUEST", "/sandbox_request.json"))
RESULT = OUTPUT / "result.json"
SKIP_NAMES = __SKIP_NAMES__
SEED_MARKER = WORKSPACE / ".focus-agent-workspace-seeded"


def _ignore(_dir, names):
    return {{name for name in names if name in SKIP_NAMES or name == ".focus_agent"}}


def _copy_workspace():
    for child in INPUT.iterdir():
        target = WORKSPACE / child.name
        if child.name == ".focus_agent":
            skills = child / "skills"
            if skills.is_dir():
                (target).mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    skills,
                    target / "skills",
                    symlinks=False,
                    ignore=_ignore,
                    dirs_exist_ok=True,
                )
            continue
        if child.name in SKIP_NAMES:
            continue
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.copytree(child, target, symlinks=False, ignore=_ignore, dirs_exist_ok=True)
        elif child.is_file():
            shutil.copy2(child, target)


def _prepare_workspace(workspace_mode):
    if workspace_mode == "thread_persistent_copy" and SEED_MARKER.exists():
        return
    _copy_workspace()
    if workspace_mode == "thread_persistent_copy":
        SEED_MARKER.write_text("ok\n", encoding="utf-8")


def _ensure_venv(dependencies):
    if not dependencies:
        return None
    digest = hashlib.sha256("\n".join(dependencies).encode("utf-8")).hexdigest()
    venv_dir = CACHE / "venvs" / digest
    python = venv_dir / "bin" / "python"
    marker = venv_dir / ".focus-agent-deps-ok"
    if not marker.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        subprocess.run([str(python), "-m", "pip", "install", *dependencies], check=True)
        marker.write_text("ok\n", encoding="utf-8")
    return python


def main():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _prepare_workspace(request.get("workspace_mode") or "thread_persistent_copy")
    command = list(request["command"])
    output_dir_arg = request.get("output_dir_arg")
    if output_dir_arg:
        command.extend([str(output_dir_arg), str(OUTPUT)])
    venv_python = _ensure_venv(request.get("dependencies") or [])
    if venv_python is not None and Path(command[0]).name in {"python", "python3"}:
        command[0] = str(venv_python)
    cwd = WORKSPACE / request.get("cwd", ".")
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=int(request.get("timeout_seconds") or 60),
        check=False,
    )
    RESULT.write_text(
        json.dumps(
            {
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "timed_out": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as exc:
        RESULT.write_text(
            json.dumps(
                {
                    "exit_code": None,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                    "timed_out": True,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        RESULT.write_text(
            json.dumps(
                {
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": f"{type(exc).__name__}: {exc}",
                    "timed_out": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        raise
"""
    path.write_text(
        template.replace("__SKIP_NAMES__", repr(sorted(_COPY_SKIP_NAMES))).lstrip(),
        encoding="utf-8",
    )


def _sandbox_env(env: Mapping[str, str]) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for key, value in env.items():
        normalized = str(key).upper()
        if (
            normalized == "PYTHONPATH"
            or normalized.startswith("PIP_")
            or any(marker in normalized for marker in _SENSITIVE_ENV_NAME_MARKERS)
        ):
            continue
        allowed[str(key)] = str(value)
    return allowed


def _run_docker_command(
    command: list[str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _docker_image_available(*, docker_binary: str, image: str) -> bool:
    try:
        completed = subprocess.run(
            [docker_binary, "image", "inspect", image],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _docker_image_unavailable_message(image: str) -> str:
    return (
        f"docker image is not available: {image}. "
        f"Run `python scripts/ensure_sandbox_image.py --image {image}` "
        "to check Docker compatibility and build the sandbox image, or set "
        "FOCUS_AGENT_SANDBOX_IMAGE to an existing trusted image."
    )


def _force_remove_container(docker_binary: str, container_name: str) -> None:
    try:
        subprocess.run(
            [docker_binary, "rm", "-f", container_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return None


def _cleanup_old_run_dirs(*, runs_root: Path, now: float, ttl_seconds: int) -> None:
    if ttl_seconds <= 0 or not runs_root.exists():
        return
    cutoff = now - ttl_seconds
    for path in runs_root.iterdir():
        try:
            stat_result = path.stat()
        except OSError:
            continue
        if not path.is_dir() or path.is_symlink() or stat_result.st_mtime >= cutoff:
            continue
        try:
            shutil.rmtree(path)
        except OSError:
            continue


def _looks_like_docker_unavailable(output: str) -> bool:
    lowered = output.lower()
    return (
        "cannot connect to the docker daemon" in lowered
        or "is the docker daemon running" in lowered
        or "command not found" in lowered
    )


def _looks_like_container_missing_or_stopped(output: str) -> bool:
    lowered = output.lower()
    return (
        "no such container" in lowered
        or "is not running" in lowered
        or "container is not running" in lowered
    )


def _trim_output(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def _coerce_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _run_outputs(
    *,
    output_dir: Path,
    workspace_root: Path,
) -> tuple[list[dict[str, Any]], bool]:
    outputs: list[dict[str, Any]] = []
    total_bytes = 0
    truncated = False
    for path in sorted(output_dir.rglob("*")):
        if len(outputs) >= _MAX_OUTPUT_FILES:
            truncated = True
            break
        try:
            stat_result = path.lstat()
        except OSError:
            continue
        if path.name == _RESULT_FILENAME or path.is_symlink() or not path.is_file():
            continue
        size_bytes = stat_result.st_size
        if total_bytes + size_bytes > _MAX_OUTPUT_BYTES:
            truncated = True
            break
        try:
            relative = path.relative_to(workspace_root).as_posix()
        except ValueError:
            relative = path.as_posix()
        total_bytes += size_bytes
        outputs.append({"path": relative, "size_bytes": size_bytes})
    return outputs, truncated
