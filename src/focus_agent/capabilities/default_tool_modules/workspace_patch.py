from __future__ import annotations

import shlex
from pathlib import Path

from .common import _read_text_file
from .workspace_paths import _resolve_workspace_path

_UNSUPPORTED_PATCH_FILE_MODES = {"120000", "160000"}


def _patch_token_path(token: str) -> str | None:
    path = token.strip()
    if not path or path in {"/dev/null", "dev/null"}:
        return None
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path or None


def _patch_line_token(value: str) -> str | None:
    try:
        parts = shlex.split(value, posix=True)
    except ValueError:
        parts = value.split()
    return parts[0] if parts else None


def _patch_paths(patch: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in patch.splitlines():
        candidates: list[str] = []
        if line.startswith("diff --git "):
            try:
                parts = shlex.split(line, posix=True)
            except ValueError:
                parts = line.split()
            candidates.extend(parts[2:4])
        elif line.startswith(("--- ", "+++ ")):
            token = _patch_line_token(line[4:])
            if token is not None:
                candidates.append(token)
        elif line.startswith(("rename from ", "rename to ")):
            candidates.append(line.split(" ", 2)[2])
        elif line.startswith(("copy from ", "copy to ")):
            candidates.append(line.split(" ", 2)[2])

        for token in candidates:
            path = _patch_token_path(token)
            if path is not None:
                paths.append(path)
    return tuple(dict.fromkeys(paths))


def _validate_patch_paths(
    *, patch: str, workspace_root: Path, max_patch_bytes: int
) -> tuple[str, ...]:
    patch_size = len(patch.encode("utf-8"))
    if patch_size > max_patch_bytes:
        raise ValueError(f"patch exceeds max_patch_bytes ({max_patch_bytes}).")
    if "GIT binary patch" in patch:
        raise ValueError("Binary patches are not supported.")
    if _patch_mentions_unsupported_file_mode(patch):
        raise ValueError("Symlink and submodule patches are not supported.")
    paths = _patch_paths(patch)
    if not paths:
        raise ValueError("patch must include at least one file path.")
    for path in paths:
        resolved = _resolve_workspace_path(raw_path=path, workspace_root=workspace_root)
        if resolved.exists() and resolved.is_file():
            _read_text_file(resolved)
    return paths


def _patch_mentions_unsupported_file_mode(patch: str) -> bool:
    for line in patch.splitlines():
        if not line.startswith(("new file mode ", "deleted file mode ", "old mode ", "new mode ")):
            continue
        mode = line.rsplit(" ", 1)[-1].strip()
        if mode in _UNSUPPORTED_PATCH_FILE_MODES:
            return True
    return False
