#!/usr/bin/env python3
"""Inventory compatibility and legacy markers without enforcing a gate."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_JSON = Path("reports/compat/latest.json")
DEFAULT_SCAN_PATHS = (
    "src/focus_agent",
    "scripts",
    "apps/web/src",
    "frontend-sdk/src",
    "docs",
)
COMPAT_KINDS = (
    "compatibility_shim",
    "deprecated_route",
    "legacy_template",
    "legacy_state_or_mirror",
    "legacy_override_or_monkeypatch",
)
SCANNED_SUFFIXES = {
    ".cjs",
    ".css",
    ".js",
    ".jsx",
    ".md",
    ".mdx",
    ".mjs",
    ".py",
    ".sh",
    ".ts",
    ".tsx",
}
IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__generated__",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "generated",
    "node_modules",
    "reports",
    "venv",
}
IGNORED_FILES = {
    "scripts/compat_report.py",
}
GENERATED_FILE_MARKERS = (
    "This file was auto-generated",
    "This file is auto-generated",
    "Do not make direct changes",
    "@generated",
)

DEPRECATED_ROUTE_PATTERNS = (
    re.compile(r"\b_mark_deprecated_route\b"),
    re.compile(r"\bdeprecated\s*=\s*True\b"),
    re.compile(r"\bdeprecated route\b", re.IGNORECASE),
)
LEGACY_TEMPLATE_PATTERNS = (
    re.compile(r"\blegacy_template\b"),
    re.compile(r"\blegacy dispatch template\b", re.IGNORECASE),
)
LEGACY_OVERRIDE_OR_MONKEYPATCH_PATTERNS = (
    re.compile(r"\blegacy[_ -].*monkey[-_ ]?patch\b", re.IGNORECASE),
    re.compile(r"\bmonkey[-_ ]?patch.*legacy\b", re.IGNORECASE),
    re.compile(r"\bcompatibility\s+monkey[-_ ]?patch\s+hook\b", re.IGNORECASE),
    re.compile(r"\blegacy[_ -].*hook\b", re.IGNORECASE),
    re.compile(r"\b_legacy_[a-z0-9_]*hook\b", re.IGNORECASE),
    re.compile(r"\blegacy\s+override\b", re.IGNORECASE),
)
LEGACY_STATE_OR_MIRROR_PATTERNS = (
    re.compile(r"\blegacy[_ -]state\b", re.IGNORECASE),
    re.compile(r"\bstate[_ -]mirror\b", re.IGNORECASE),
    re.compile(r"\bmirror(?:ed|ing)?\s+legacy\b", re.IGNORECASE),
    re.compile(r"\blegacy\s+\w+\s+mirror\b", re.IGNORECASE),
)
COMPATIBILITY_SHIM_PATTERNS = (
    re.compile(r"\bcompatibility\s+shim\b", re.IGNORECASE),
    re.compile(r"\bcompatibility\s+facade\b", re.IGNORECASE),
    re.compile(r"\bcompatibility\s+(?:re-)?exports?\b", re.IGNORECASE),
    re.compile(r"\bcompatibility\s+alias(?:es)?\b", re.IGNORECASE),
    re.compile(r"\bpublic\s+compatibility\s+name\b", re.IGNORECASE),
    re.compile(r"\blegacy\s+shims?\b", re.IGNORECASE),
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve(path: str | Path, *, root: Path) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = root / target
    return target


def _relative(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def _is_ignored_file(path: Path, *, root: Path) -> bool:
    return _relative(path, root=root) in IGNORED_FILES


def _is_generated_file(path: Path) -> bool:
    header = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:8])
    return any(marker in header for marker in GENERATED_FILE_MARKERS)


def _iter_files(paths: Sequence[str | Path], *, root: Path) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        target = _resolve(raw_path, root=root)
        if not target.exists() or _is_ignored(target):
            continue
        candidates = [target] if target.is_file() else target.rglob("*")
        for path in candidates:
            if (
                not path.is_file()
                or path.suffix not in SCANNED_SUFFIXES
                or _is_ignored(path)
                or _is_ignored_file(path, root=root)
            ):
                continue
            resolved = path.resolve()
            if resolved in seen or _is_generated_file(path):
                continue
            seen.add(resolved)
            files.append(path)
    return sorted(files, key=lambda path: _relative(path, root=root))


def _matches_any(patterns: Sequence[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _is_state_legacy_line(path: Path, text: str) -> bool:
    lowered = text.lower()
    if "legacy" not in lowered:
        return False
    if path.name not in {"state.py", "state_schema.py"}:
        return False
    return any(marker in lowered for marker in ("keys", "pinned strings", "plan lines", "records"))


def classify_line(path: Path, text: str) -> str | None:
    if _matches_any(DEPRECATED_ROUTE_PATTERNS, text):
        return "deprecated_route"
    if _matches_any(LEGACY_TEMPLATE_PATTERNS, text):
        return "legacy_template"
    if _matches_any(LEGACY_OVERRIDE_OR_MONKEYPATCH_PATTERNS, text):
        return "legacy_override_or_monkeypatch"
    if _matches_any(LEGACY_STATE_OR_MIRROR_PATTERNS, text) or _is_state_legacy_line(path, text):
        return "legacy_state_or_mirror"
    if _matches_any(COMPATIBILITY_SHIM_PATTERNS, text):
        return "compatibility_shim"
    return None


def _snippet(text: str, *, limit: int = 240) -> str:
    stripped = " ".join(text.strip().split())
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[: limit - 3]}..."


def collect_compat_items(files: Sequence[Path], *, root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in files:
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            kind = classify_line(path, line)
            if kind is None:
                continue
            snippet = _snippet(line)
            items.append(
                {
                    "kind": kind,
                    "line": line_no,
                    "path": _relative(path, root=root),
                    "snippet": snippet,
                    "text": snippet,
                }
            )
    return sorted(items, key=lambda item: (item["path"], item["line"], item["kind"]))


def build_compat_report(
    *,
    root: str | Path = REPO_ROOT,
    scan_paths: Sequence[str | Path] = DEFAULT_SCAN_PATHS,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    files = _iter_files(scan_paths, root=root_path)
    items = collect_compat_items(files, root=root_path)
    counts = Counter(item["kind"] for item in items)
    by_kind = {kind: counts.get(kind, 0) for kind in COMPAT_KINDS}
    return {
        "meta": {
            "generated_at": _now_iso(),
            "root": str(root_path),
            "suite": "compat_legacy_inventory",
        },
        "config": {
            "ignored_dirs": sorted(IGNORED_DIRS),
            "scan_paths": [str(path) for path in scan_paths],
            "scanned_suffixes": sorted(SCANNED_SUFFIXES),
        },
        "summary": {
            "blocking": False,
            "by_kind": by_kind,
            "scanned_file_count": len(files),
            "status": "issues" if items else "ok",
            "total": len(items),
        },
        "items": items,
    }


def write_compat_report(path: str | Path, report: dict[str, Any], *, root: Path = REPO_ROOT) -> Path:
    target = _resolve(path, root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root to scan.")
    parser.add_argument(
        "--report-json",
        default=str(DEFAULT_REPORT_JSON),
        help="Structured JSON report path.",
    )
    parser.add_argument(
        "--scan-path",
        action="append",
        default=[],
        help="Path to scan relative to --root. Repeatable; defaults to project code paths.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    report = build_compat_report(root=root, scan_paths=args.scan_path or DEFAULT_SCAN_PATHS)
    target = write_compat_report(args.report_json, report, root=root)
    print(
        json.dumps(
            {
                "blocking": False,
                "by_kind": report["summary"]["by_kind"],
                "report_json": str(target),
                "status": report["summary"]["status"],
                "total": report["summary"]["total"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
