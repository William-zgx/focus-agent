from __future__ import annotations

from pathlib import Path


def bundled_skills_dir() -> Path:
    return Path(__file__).resolve().parent / "builtin"


def _normalize_skill_id(value: str) -> str:
    return value.strip().lower().replace("_", "-")


__all__ = ["_normalize_skill_id", "bundled_skills_dir"]
