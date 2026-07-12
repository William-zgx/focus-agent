from __future__ import annotations

import json
import os
import re
import shutil
import stat
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sandbox_execution import SandboxExecutionRequest

_WORKSPACE_MANIFEST_FILENAME = ".focus-agent-workspace-manifest.json"
_WORKSPACE_MODE_COPY_DISCARD = "copy_discard"
_WORKSPACE_MODE_THREAD_PERSISTENT_COPY = "thread_persistent_copy"
_WORKSPACE_MODE_HOST = "host"
_SANDBOX_ID_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_COPY_SKIP_NAMES = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def _write_request(path: Path, request: SandboxExecutionRequest) -> None:
    payload = {
        "command": request.command,
        "cwd": request.cwd,
        "timeout_seconds": request.timeout_seconds,
        "dependencies": list(request.dependencies),
        "output_dir_arg": request.output_dir_arg,
        "workspace_mode": request.workspace_mode,
        "sandbox_id": request.sandbox_id,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _sync_workspace_snapshot(*, source_root: Path, target_root: Path) -> None:
    source_root, target_root = _validate_workspace_snapshot_roots(
        source_root=source_root,
        target_root=target_root,
    )
    target_root.mkdir(parents=True, exist_ok=True)
    _remove_snapshot_symlinks(target_root)
    manifest_path = target_root.parent / _WORKSPACE_MANIFEST_FILENAME
    current_manifest = _workspace_snapshot_manifest(source_root)
    previous_manifest = _read_workspace_snapshot_manifest(manifest_path)
    if previous_manifest is None:
        _prune_workspace_to_manifest(target_root=target_root, manifest=current_manifest)
    else:
        _delete_removed_snapshot_paths(
            target_root=target_root,
            previous_manifest=previous_manifest,
            current_manifest=current_manifest,
        )
    for child in source_root.iterdir():
        if child.name in _COPY_SKIP_NAMES or child.name == ".git":
            continue
        child_kind = _snapshot_entry_kind(child)
        if child_kind is None:
            continue
        target = target_root / child.name
        if child.name == ".focus_agent":
            skills = child / "skills"
            if _snapshot_entry_kind(skills) == "directory":
                skills_target = target / "skills"
                _ensure_snapshot_target_type(target, directory=True)
                _ensure_snapshot_target_type(skills_target, directory=True)
                shutil.copytree(
                    skills,
                    skills_target,
                    symlinks=True,
                    ignore=_copytree_ignore,
                    dirs_exist_ok=True,
                )
                _remove_snapshot_symlinks(skills_target)
            continue
        if child_kind == "directory":
            _ensure_snapshot_target_type(target, directory=True)
            shutil.copytree(
                child,
                target,
                symlinks=True,
                ignore=_copytree_ignore,
                dirs_exist_ok=True,
            )
            _remove_snapshot_symlinks(target)
        elif child_kind == "file":
            _ensure_snapshot_target_type(target, directory=False)
            shutil.copy2(child, target, follow_symlinks=False)
            if _is_snapshot_symlink(target):
                target.unlink()
    _write_workspace_snapshot_manifest(manifest_path, current_manifest)


def _workspace_snapshot_manifest(source_root: Path) -> set[str]:
    source_root = _assert_path_has_no_symlink_components(
        source_root,
        label="workspace snapshot source",
    )
    if _snapshot_entry_kind(source_root) != "directory":
        raise ValueError("workspace snapshot source must be a directory.")
    manifest: set[str] = set()
    for child in source_root.iterdir():
        if child.name in _COPY_SKIP_NAMES or child.name == ".git":
            continue
        if _snapshot_entry_kind(child) is None:
            continue
        if child.name == ".focus_agent":
            skills = child / "skills"
            if _snapshot_entry_kind(skills) == "directory":
                manifest.add(".focus_agent")
                _add_snapshot_manifest_entry(
                    manifest,
                    source=skills,
                    relative_path=PurePosixPath(".focus_agent") / "skills",
                )
            continue
        _add_snapshot_manifest_entry(
            manifest,
            source=child,
            relative_path=PurePosixPath(child.name),
        )
    return manifest


def _add_snapshot_manifest_entry(
    manifest: set[str],
    *,
    source: Path,
    relative_path: PurePosixPath,
) -> None:
    source_kind = _snapshot_entry_kind(source)
    if source_kind == "directory":
        manifest.add(relative_path.as_posix())
        for child in source.iterdir():
            if child.name in _COPY_SKIP_NAMES or child.name == ".focus_agent":
                continue
            _add_snapshot_manifest_entry(
                manifest,
                source=child,
                relative_path=relative_path / child.name,
            )
    elif source_kind == "file":
        manifest.add(relative_path.as_posix())


def _read_workspace_snapshot_manifest(path: Path) -> set[str] | None:
    try:
        _assert_path_has_no_symlink_components(path.parent, label="workspace manifest")
    except ValueError:
        return None
    if _is_snapshot_symlink(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    manifest: set[str] = set()
    for item in payload:
        if not isinstance(item, str) or not _is_safe_manifest_path(item):
            return None
        manifest.add(item)
    return manifest


def _write_workspace_snapshot_manifest(path: Path, manifest: set[str]) -> None:
    _assert_path_has_no_symlink_components(path.parent, label="workspace manifest")
    _ensure_snapshot_target_type(path, directory=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(manifest), ensure_ascii=False), encoding="utf-8")


def _is_safe_manifest_path(value: str) -> bool:
    relative_path = PurePosixPath(value)
    return bool(value) and not relative_path.is_absolute() and ".." not in relative_path.parts


def _delete_removed_snapshot_paths(
    *,
    target_root: Path,
    previous_manifest: set[str],
    current_manifest: set[str],
) -> None:
    removed_paths = previous_manifest - current_manifest
    for relative_path in sorted(
        removed_paths,
        key=lambda value: (value.count("/"), value),
        reverse=True,
    ):
        _remove_snapshot_path(target_root / Path(relative_path))


def _prune_workspace_to_manifest(*, target_root: Path, manifest: set[str]) -> None:
    for child in list(target_root.iterdir()):
        _prune_snapshot_entry_to_manifest(
            target=child,
            relative_path=PurePosixPath(child.name),
            manifest=manifest,
        )


def _prune_snapshot_entry_to_manifest(
    *,
    target: Path,
    relative_path: PurePosixPath,
    manifest: set[str],
) -> None:
    if _is_snapshot_symlink(target):
        _remove_snapshot_path(target)
        return
    if relative_path.as_posix() not in manifest:
        _remove_snapshot_path(target)
        return
    if _snapshot_entry_kind(target) == "directory":
        for child in list(target.iterdir()):
            _prune_snapshot_entry_to_manifest(
                target=child,
                relative_path=relative_path / child.name,
                manifest=manifest,
            )


def _remove_snapshot_path(path: Path) -> None:
    try:
        path_mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(path_mode) and not stat.S_ISLNK(path_mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _copytree_ignore(_dir: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in _COPY_SKIP_NAMES or name == ".focus_agent"}
    for name in names:
        if _snapshot_entry_kind(Path(_dir) / name) is None:
            ignored.add(name)
    return ignored


def _validate_workspace_snapshot_roots(
    *,
    source_root: Path,
    target_root: Path,
) -> tuple[Path, Path]:
    source_root = _assert_path_has_no_symlink_components(
        source_root,
        label="workspace snapshot source",
    )
    target_root = _assert_path_has_no_symlink_components(
        target_root,
        label="workspace snapshot target",
    )
    try:
        source_mode = source_root.lstat().st_mode
    except FileNotFoundError as exc:
        raise ValueError("workspace snapshot source does not exist.") from exc
    if not stat.S_ISDIR(source_mode):
        raise ValueError("workspace snapshot source must be a directory.")
    try:
        relative_target = target_root.relative_to(source_root)
    except ValueError as exc:
        raise ValueError("workspace snapshot target must stay inside the workspace.") from exc
    if relative_target == Path("."):
        raise ValueError("workspace snapshot target must not replace the workspace.")
    return source_root, target_root


def _assert_path_has_no_symlink_components(path: Path, *, label: str) -> Path:
    absolute_path = path.absolute()
    current = Path(absolute_path.anchor)
    for part in absolute_path.parts[1:]:
        current /= part
        try:
            path_mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError(f"{label} cannot be inspected safely: {current}") from exc
        if stat.S_ISLNK(path_mode):
            raise ValueError(f"{label} must not contain symbolic links: {current}")
    return Path(os.path.normpath(absolute_path))


def _snapshot_entry_kind(path: Path) -> str | None:
    try:
        path_mode = path.lstat().st_mode
    except OSError:
        return None
    if stat.S_ISDIR(path_mode):
        return "directory"
    if stat.S_ISREG(path_mode):
        return "file"
    return None


def _is_snapshot_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(path.lstat().st_mode)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValueError(f"workspace snapshot path cannot be inspected safely: {path}") from exc


def _ensure_snapshot_target_type(path: Path, *, directory: bool) -> None:
    try:
        path_mode = path.lstat().st_mode
    except FileNotFoundError:
        path_mode = None
    if path_mode is not None:
        expected_type = stat.S_ISDIR(path_mode) if directory else stat.S_ISREG(path_mode)
        if not expected_type:
            _remove_snapshot_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)


def _remove_snapshot_symlinks(root: Path) -> None:
    for child in list(root.iterdir()):
        if _is_snapshot_symlink(child):
            child.unlink()
        elif _snapshot_entry_kind(child) == "directory":
            _remove_snapshot_symlinks(child)


def _sandbox_paths(
    *,
    request: SandboxExecutionRequest,
    run_id: str,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    if request.workspace_mode == _WORKSPACE_MODE_COPY_DISCARD:
        runs_root = request.workspace_root / ".focus_agent" / "sandboxes" / "runs"
        run_root = runs_root / run_id
        return (
            run_root,
            runs_root,
            run_root / "workspace",
            run_root / "output",
            run_root / "tmp",
            run_root / "cache",
        )

    sandbox_id = request.sandbox_id or _sandbox_id_for_request(request, run_id=run_id)
    sandbox_root = request.workspace_root / ".focus_agent" / "sandboxes" / "threads" / sandbox_id
    runs_root = sandbox_root / "runs"
    run_root = runs_root / run_id
    return (
        run_root,
        runs_root,
        sandbox_root / "workspace",
        run_root / "output",
        run_root / "tmp",
        sandbox_root / "cache",
    )


def _sandbox_id_for_request(request: SandboxExecutionRequest, *, run_id: str) -> str:
    return _sandbox_id_for_parts(
        thread_id=request.thread_id,
        branch_id=request.branch_id,
        sandbox_id=request.sandbox_id,
        run_id=run_id,
    )


def _sandbox_id_for_parts(
    *,
    thread_id: str | None,
    branch_id: str | None,
    sandbox_id: str | None = None,
    run_id: str | None = None,
) -> str:
    if sandbox_id:
        return _sanitize_sandbox_identifier(sandbox_id, prefix="sandbox")
    if branch_id:
        return f"branch-{_sanitize_sandbox_identifier(branch_id, prefix='branch')}"
    if thread_id:
        return f"thread-{_sanitize_sandbox_identifier(thread_id, prefix='thread')}"
    if run_id:
        return f"run-{_sanitize_sandbox_identifier(run_id, prefix='run')}"
    return "anonymous"


def _sanitize_sandbox_identifier(value: str, *, prefix: str) -> str:
    sanitized = _SANDBOX_ID_UNSAFE_RE.sub("-", str(value)).strip(".-_")
    sanitized = sanitized[:96].strip(".-_")
    return sanitized or prefix


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
