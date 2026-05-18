#!/usr/bin/env python3
"""Report architecture guardrail signals without enforcing a gate."""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_JSON = Path("reports/architecture/latest.json")
DEFAULT_SCAN_PATHS = (
    "src/focus_agent",
    "scripts",
    "apps/web/src",
    "frontend-sdk/src",
    "tests/eval",
)
DEFAULT_LARGE_FILE_THRESHOLD = 800
SCANNED_SUFFIXES = {".css", ".js", ".jsx", ".md", ".mjs", ".py", ".ts", ".tsx"}
IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "reports",
}


@dataclass(frozen=True)
class ImportBoundaryRule:
    source_prefix: str
    forbidden_imports: tuple[str, ...]
    reason: str


PYTHON_IMPORT_RULES: tuple[ImportBoundaryRule, ...] = (
    ImportBoundaryRule(
        "src/focus_agent",
        ("scripts", "tests", "apps", "frontend_sdk", "frontend-sdk"),
        "production package code must not depend on scripts, tests, or frontend workspaces",
    ),
    ImportBoundaryRule(
        "scripts",
        ("apps", "frontend_sdk", "frontend-sdk"),
        "automation scripts must not depend on frontend implementation modules",
    ),
)
TEXT_IMPORT_RULES: tuple[ImportBoundaryRule, ...] = (
    ImportBoundaryRule(
        "apps/web/src",
        ("src/focus_agent", "scripts"),
        "web source must use API/SDK contracts instead of importing backend or script code",
    ),
    ImportBoundaryRule(
        "frontend-sdk/src",
        ("apps/web", "src/focus_agent", "scripts"),
        "SDK source must stay independent of app, backend, and script internals",
    ),
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
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def _iter_files(paths: Sequence[str | Path], *, root: Path) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        target = _resolve(raw_path, root=root)
        if not target.exists():
            continue
        candidates = [target] if target.is_file() else target.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix not in SCANNED_SUFFIXES or _is_ignored(path):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)
    return sorted(files, key=lambda path: _relative(path, root=root))


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def collect_large_files(
    files: Iterable[Path],
    *,
    root: Path,
    threshold: int,
) -> list[dict[str, Any]]:
    large_files: list[dict[str, Any]] = []
    for path in files:
        lines = _line_count(path)
        if lines <= threshold:
            continue
        large_files.append(
            {
                "lines": lines,
                "path": _relative(path, root=root),
                "threshold": threshold,
            }
        )
    return large_files


def _python_imports(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [(exc.lineno or 1, "<syntax-error>")]
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.lineno, "." * node.level + node.module))
    return imports


def _text_imports(path: Path) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        stripped = line.strip()
        if " from " not in stripped and not stripped.startswith("import "):
            continue
        for quote in ("'", '"'):
            parts = stripped.split(quote)
            if len(parts) >= 3:
                imports.append((line_no, parts[-2]))
                break
    return imports


def _matches_prefix(path: Path, *, root: Path, prefix: str) -> bool:
    relative = _relative(path, root=root)
    return relative == prefix or relative.startswith(f"{prefix}/")


def _violates(import_name: str, forbidden_import: str) -> bool:
    normalized = import_name.lstrip(".")
    return (
        normalized == forbidden_import
        or normalized.startswith(f"{forbidden_import}.")
        or normalized.startswith(f"{forbidden_import}/")
    )


def _boundary_issues_for_file(path: Path, *, root: Path) -> list[dict[str, Any]]:
    rules = PYTHON_IMPORT_RULES if path.suffix == ".py" else TEXT_IMPORT_RULES
    imports = _python_imports(path) if path.suffix == ".py" else _text_imports(path)
    issues: list[dict[str, Any]] = []
    for rule in rules:
        if not _matches_prefix(path, root=root, prefix=rule.source_prefix):
            continue
        for line_no, import_name in imports:
            for forbidden in rule.forbidden_imports:
                if _violates(import_name, forbidden):
                    issues.append(
                        {
                            "forbidden_import": forbidden,
                            "import_name": import_name,
                            "line": line_no,
                            "path": _relative(path, root=root),
                            "reason": rule.reason,
                            "source_prefix": rule.source_prefix,
                        }
                    )
    return issues


def collect_import_boundary_issues(files: Iterable[Path], *, root: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for path in files:
        if path.suffix not in {".js", ".jsx", ".mjs", ".py", ".ts", ".tsx"}:
            continue
        issues.extend(_boundary_issues_for_file(path, root=root))
    return issues


def build_architecture_report(
    *,
    root: str | Path = REPO_ROOT,
    scan_paths: Sequence[str | Path] = DEFAULT_SCAN_PATHS,
    large_file_threshold: int = DEFAULT_LARGE_FILE_THRESHOLD,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    files = _iter_files(scan_paths, root=root_path)
    large_files = collect_large_files(files, root=root_path, threshold=large_file_threshold)
    boundary_issues = collect_import_boundary_issues(files, root=root_path)
    issue_count = len(large_files) + len(boundary_issues)
    return {
        "meta": {
            "generated_at": _now_iso(),
            "root": str(root_path),
            "suite": "architecture_guardrails",
        },
        "config": {
            "large_file_threshold": large_file_threshold,
            "scan_paths": [str(path) for path in scan_paths],
        },
        "summary": {
            "status": "issues" if issue_count else "ok",
            "issue_count": issue_count,
            "large_file_count": len(large_files),
            "import_boundary_issue_count": len(boundary_issues),
            "scanned_file_count": len(files),
            "blocking": False,
        },
        "large_files": large_files,
        "import_boundary_issues": boundary_issues,
    }


def write_architecture_report(path: str | Path, report: dict[str, Any], *, root: Path = REPO_ROOT) -> Path:
    target = _resolve(path, root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON), help="Structured JSON report path.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root to scan.")
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Path to scan relative to --root. Repeatable; defaults to core architecture paths.",
    )
    parser.add_argument(
        "--large-file-threshold",
        type=int,
        default=DEFAULT_LARGE_FILE_THRESHOLD,
        help="Line count above which a scanned file is reported as large.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    report = build_architecture_report(
        root=root,
        scan_paths=args.path or DEFAULT_SCAN_PATHS,
        large_file_threshold=int(args.large_file_threshold),
    )
    target = write_architecture_report(args.report_json, report, root=root)
    print(
        json.dumps(
            {
                "blocking": False,
                "issue_count": report["summary"]["issue_count"],
                "report_json": str(target),
                "status": report["summary"]["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
