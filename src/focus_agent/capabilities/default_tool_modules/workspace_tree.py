from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain.tools import tool

from .common import _coerce_relative_posix
from .workspace_paths import _resolve_workspace_path

_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    ".tox",
    ".cache",
    ".claude",
    ".focus_agent",
    "dist",
    "build",
}


def _build_workspace_tree_lines(
    dir_path: Path,
    *,
    prefix: str,
    remaining_depth: int,
    max_entries: int,
    lines: list[str],
) -> bool:
    if remaining_depth <= 0 or len(lines) >= max_entries:
        return len(lines) >= max_entries
    try:
        entries = sorted(
            (
                entry
                for entry in dir_path.iterdir()
                if entry.name not in _SKIP_DIR_NAMES and not entry.name.startswith(".")
            ),
            key=lambda entry: (not entry.is_dir(), entry.name.lower()),
        )
    except OSError:
        return False
    for index, entry in enumerate(entries):
        if len(lines) >= max_entries:
            return True
        is_last = index == len(entries) - 1
        connector = "└── " if is_last else "├── "
        is_dir = entry.is_dir()
        lines.append(f"{prefix}{connector}{entry.name}{'/' if is_dir else ''}")
        if is_dir and remaining_depth > 1:
            child_prefix = f"{prefix}{'    ' if is_last else '│   '}"
            if _build_workspace_tree_lines(
                entry,
                prefix=child_prefix,
                remaining_depth=remaining_depth - 1,
                max_entries=max_entries,
                lines=lines,
            ):
                return True
    return False


def build_workspace_tree_tool(
    *,
    workspace_root: Path,
    tree_config: Any,
    emit_tool_event: Callable[..., None],
) -> Any:
    @tool
    def workspace_tree(
        path: str = ".",
        max_depth: int | None = None,
        max_entries: int | None = None,
    ) -> str:
        """Print a workspace directory as an indented tree up to a max depth."""
        tool_name = "workspace_tree"
        emit_tool_event(
            tool_name=tool_name,
            stage="start",
            path=path,
            max_depth=max_depth,
            max_entries=max_entries,
        )
        try:
            root = _resolve_workspace_path(raw_path=path, workspace_root=workspace_root)
            if not root.exists():
                raise FileNotFoundError(path)
            if root.is_file():
                raise NotADirectoryError(path)
            requested_depth = tree_config.default_max_depth if max_depth is None else int(max_depth)
            capped_depth = max(1, min(requested_depth, tree_config.max_depth_cap))
            requested_entries = (
                tree_config.default_max_entries if max_entries is None else int(max_entries)
            )
            capped_entries = max(1, min(requested_entries, tree_config.max_entries_cap))
            relative_root = _coerce_relative_posix(root, workspace_root)
            lines = [relative_root if relative_root != "." else str(workspace_root.name)]
            truncated = _build_workspace_tree_lines(
                root,
                prefix="",
                remaining_depth=capped_depth,
                max_entries=capped_entries,
                lines=lines,
            )
            payload = {
                "workspace_root": str(workspace_root),
                "path": relative_root,
                "max_depth": capped_depth,
                "max_entries": capped_entries,
                "tree": "\n".join(lines),
                "entry_count": max(0, len(lines) - 1),
                "truncated": truncated,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name,
                stage="end",
                result_count=payload["entry_count"],
                output=result[:800],
            )
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), path=path)
            raise

    return workspace_tree
