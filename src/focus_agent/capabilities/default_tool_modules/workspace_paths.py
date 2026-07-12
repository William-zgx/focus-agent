from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

_FOCUS_HOME_FOCUS_AGENT_PARTS = PurePosixPath("/home/focus/.focus_agent").parts
_FOCUS_HOME_SKILLS_PARTS = PurePosixPath("/home/focus/.focus_agent/skills").parts
_TRUSTED_SKILL_PYTHON_RE = re.compile(r"python(?:3(?:\.\d+)?)?\Z")
_DEFAULT_WORKSPACE_SKILL_COLLECTION_ROOT_PARTS: tuple[tuple[str, ...], ...] = (
    (".focus_agent", "skills"),
)


def _resolve_workspace_path(*, raw_path: str, workspace_root: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    resolved = (
        candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()
    )
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"Path must stay within workspace root: {workspace_root}") from exc
    return resolved


def _resolve_workspace_command_cwd(*, raw_cwd: object, workspace_root: Path) -> Path:
    cwd_text = "." if raw_cwd is None else str(raw_cwd)
    if not cwd_text.strip():
        raise ValueError("cwd must not be empty.")
    repaired = _resolve_focus_home_skill_cwd(raw_cwd=cwd_text, workspace_root=workspace_root)
    if repaired is not None:
        return repaired
    return _resolve_workspace_path(raw_path=cwd_text, workspace_root=workspace_root)


def _resolve_focus_home_skill_cwd(*, raw_cwd: str, workspace_root: Path) -> Path | None:
    parts = PurePosixPath(raw_cwd).parts
    if parts[: len(_FOCUS_HOME_FOCUS_AGENT_PARTS)] != _FOCUS_HOME_FOCUS_AGENT_PARTS:
        return None
    if parts[: len(_FOCUS_HOME_SKILLS_PARTS)] != _FOCUS_HOME_SKILLS_PARTS:
        raise ValueError("Skill cwd must start with /home/focus/.focus_agent/skills/<id>.")
    relative_parts = parts[len(_FOCUS_HOME_SKILLS_PARTS) :]
    if not relative_parts:
        raise ValueError("Skill cwd must include a non-empty skill id.")
    if any(part == ".." for part in relative_parts):
        raise ValueError("Skill cwd must not contain '..'.")

    skill_id = relative_parts[0]
    if not skill_id:
        raise ValueError("Skill cwd must include a non-empty skill id.")

    skill_root = workspace_root / ".focus_agent" / "skills" / skill_id
    target = workspace_root / ".focus_agent" / "skills" / Path(*relative_parts)
    resolved = target.resolve()
    try:
        resolved.relative_to(skill_root)
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("Skill cwd must not escape the workspace skill directory.") from exc
    return resolved


def _trusted_skill_python_interpreter_name(command_name: str) -> bool:
    if "/" in command_name or "\\" in command_name:
        return False
    return bool(_TRUSTED_SKILL_PYTHON_RE.fullmatch(command_name))


def _resolve_workspace_skill_collection_root(
    *, raw_root: str | Path, workspace_root: Path
) -> Path | None:
    root_text = os.fspath(raw_root).strip()
    if not root_text:
        return None
    candidate = Path(root_text).expanduser()
    resolved = (
        candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()
    )
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        return None
    return resolved


def _trusted_workspace_skill_collection_roots(
    *, workspace_root: Path, configured_roots: Iterable[str | Path]
) -> tuple[Path, ...]:
    roots: list[Path] = []

    def append_root(root: Path | None) -> None:
        if root is not None and root not in roots:
            roots.append(root)

    for root_parts in _DEFAULT_WORKSPACE_SKILL_COLLECTION_ROOT_PARTS:
        append_root((workspace_root / Path(*root_parts)).resolve())
    for configured_root in configured_roots:
        append_root(
            _resolve_workspace_skill_collection_root(
                raw_root=configured_root, workspace_root=workspace_root
            )
        )
    return tuple(roots)


def _workspace_skill_root_for_path(
    *,
    path: Path,
    workspace_root: Path,
    skill_collection_roots: Iterable[Path],
) -> Path | None:
    for skill_collection_root in skill_collection_roots:
        try:
            skill_collection_root.relative_to(workspace_root)
            relative = path.relative_to(skill_collection_root)
        except ValueError:
            continue
        if not relative.parts:
            return None
        skill_root = (skill_collection_root / relative.parts[0]).resolve()
        try:
            skill_root.relative_to(workspace_root)
            path.relative_to(skill_root)
        except ValueError:
            continue
        return skill_root
    return None
