"""Small helpers for observability UI smoke script."""

from __future__ import annotations

from pathlib import Path


def _tail_text(path: Path, *, max_lines: int = 40) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])
