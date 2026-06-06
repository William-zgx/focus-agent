from __future__ import annotations

from pathlib import Path


def bundled_skills_dir() -> Path:
    return Path(__file__).resolve().parent / "builtin"


def _normalize_skill_id(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _is_safe_skill_id(value: str) -> bool:
    normalized = _normalize_skill_id(value)
    if not normalized or normalized in {".", ".."} or normalized.startswith("."):
        return False
    return "/" not in normalized and "\\" not in normalized


__all__ = ["_is_safe_skill_id", "_normalize_skill_id", "bundled_skills_dir"]
