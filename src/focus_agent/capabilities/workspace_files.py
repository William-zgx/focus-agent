"""Shared workspace file-walking constants for tools and retrieval indexing."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

WORKSPACE_SKIP_DIR_NAMES = frozenset(
    {
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
)
TEXT_FILE_SUFFIX_TO_LANGUAGE: Mapping[str, str] = MappingProxyType(
    {
        ".c": "C",
        ".cc": "C++",
        ".cpp": "C++",
        ".cs": "C#",
        ".css": "CSS",
        ".go": "Go",
        ".h": "C/C++ Header",
        ".hpp": "C++ Header",
        ".html": "HTML",
        ".java": "Java",
        ".js": "JavaScript",
        ".json": "JSON",
        ".kt": "Kotlin",
        ".md": "Markdown",
        ".mjs": "JavaScript",
        ".php": "PHP",
        ".py": "Python",
        ".rb": "Ruby",
        ".rs": "Rust",
        ".sh": "Shell",
        ".sql": "SQL",
        ".swift": "Swift",
        ".toml": "TOML",
        ".ts": "TypeScript",
        ".tsx": "TSX",
        ".txt": "Text",
        ".xml": "XML",
        ".yaml": "YAML",
        ".yml": "YAML",
    }
)


def language_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return TEXT_FILE_SUFFIX_TO_LANGUAGE.get(suffix, suffix or "no_extension")
