#!/usr/bin/env python3
"""Inventory compatibility structures and enforce the versioned regression gate."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_JSON = Path("reports/compat/latest.json")
DEFAULT_BASELINE_JSON = Path("docs/compat-debt-baseline.json")
BASELINE_SCHEMA_VERSION = 2
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


def _text_item_id(
    *,
    kind: str,
    path: str,
    occurrence: int,
) -> str:
    return f"text:{kind}:{path}:{occurrence}"


def _import_source(node: ast.ImportFrom) -> str:
    return f"{'.' * node.level}{node.module or ''}"


def _is_stdlib_import(source: str) -> bool:
    top_level = source.lstrip(".").partition(".")[0]
    return bool(top_level) and top_level in sys.stdlib_module_names


def _is_local_import(source: str) -> bool:
    return source.startswith(".") or source == "focus_agent" or source.startswith("focus_agent.")


def _same_name_reexport_items(
    tree: ast.Module,
    *,
    path: Path,
    relative_path: str,
) -> list[dict[str, Any]]:
    if path.name == "__init__.py":
        return []
    items: list[dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        source = _import_source(node)
        if _is_stdlib_import(source) or not _is_local_import(source):
            continue
        for alias in node.names:
            if alias.name == "*" or alias.asname != alias.name:
                continue
            items.append(
                {
                    "detector": "python_same_name_reexport",
                    "id": (
                        "structure:compatibility_shim:python_same_name_reexport:"
                        f"{relative_path}:{source}:{alias.name}"
                    ),
                    "kind": "compatibility_shim",
                    "line": node.lineno,
                    "path": relative_path,
                    "snippet": f"from {source} import {alias.name} as {alias.name}",
                    "text": f"from {source} import {alias.name} as {alias.name}",
                }
            )
    return items


def _is_facade_statement(node: ast.stmt) -> bool:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return True
    if isinstance(node, ast.Expr):
        return isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    if isinstance(node, ast.Assign):
        return all(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        )
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and node.target.id == "__all__"
    return False


def _import_star_facade_items(
    tree: ast.Module,
    *,
    path: Path,
    relative_path: str,
) -> list[dict[str, Any]]:
    if path.name == "__init__.py" or not all(_is_facade_statement(node) for node in tree.body):
        return []
    star_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and not _is_stdlib_import(_import_source(node))
        and _is_local_import(_import_source(node))
        and any(alias.name == "*" for alias in node.names)
    ]
    if not star_imports:
        return []
    sources = sorted({_import_source(node) for node in star_imports})
    source_key = ",".join(sources)
    snippet = f"import-star facade: {', '.join(sources)}"
    return [
        {
            "detector": "python_import_star_facade",
            "id": (
                "structure:compatibility_shim:python_import_star_facade:"
                f"{relative_path}:{source_key}"
            ),
            "kind": "compatibility_shim",
            "line": min(node.lineno for node in star_imports),
            "path": relative_path,
            "snippet": snippet,
            "text": snippet,
        }
    ]


def _scope_nodes(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    scopes: list[tuple[str, ast.AST]] = []

    def visit_scope(node: ast.AST, prefix: str) -> None:
        scopes.append((prefix or "<module>", node))
        body = getattr(node, "body", ())
        for child in body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                visit_scope(child, name)

    visit_scope(tree, "")
    return scopes


def _walk_scope(node: ast.AST) -> list[ast.AST]:
    descendants: list[ast.AST] = []

    def visit(current: ast.AST) -> None:
        descendants.append(current)
        for child in ast.iter_child_nodes(current):
            if child is not node and isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                continue
            visit(child)

    visit(node)
    return descendants


def _is_sys_modules(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "modules"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def _is_static_sys_modules_subscript(node: ast.AST) -> bool:
    if not isinstance(node, ast.Subscript) or not _is_sys_modules(node.value):
        return False
    return (
        isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
        or isinstance(node.slice, ast.Name)
        and node.slice.id == "__name__"
    )


def _contains_sys_modules_lookup(node: ast.AST) -> bool:
    return any(
        isinstance(candidate, ast.Call)
        and isinstance(candidate.func, ast.Attribute)
        and candidate.func.attr == "get"
        and _is_sys_modules(candidate.func.value)
        for candidate in ast.walk(node)
    )


def _contains_globals_lookup(node: ast.AST) -> bool:
    return any(
        isinstance(candidate, ast.Call)
        and isinstance(candidate.func, ast.Name)
        and candidate.func.id == "globals"
        for candidate in ast.walk(node)
    )


def _is_globals_subscript(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "globals"
    )


def _module_patch_seam_line(scope_node: ast.AST) -> int | None:
    nodes = _walk_scope(scope_node)
    module_names: set[str] = set()
    evidence_lines: list[int] = []
    is_lazy_module_cache = (
        isinstance(scope_node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and scope_node.name == "__getattr__"
    )
    for node in nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if value is not None and _contains_sys_modules_lookup(value):
                module_names.update(target.id for target in targets if isinstance(target, ast.Name))
            if isinstance(node, ast.Assign):
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == "__class__"
                        and _is_static_sys_modules_subscript(target.value)
                    ):
                        evidence_lines.append(node.lineno)
                    elif _is_static_sys_modules_subscript(target):
                        evidence_lines.append(node.lineno)
                    elif _is_globals_subscript(target) and not is_lazy_module_cache:
                        evidence_lines.append(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setdefault"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "globals"
        ):
            evidence_lines.append(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and any(_contains_globals_lookup(argument) for argument in node.args[1:])
        ):
            evidence_lines.append(node.lineno)
    for node in nodes:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in module_names
            and not (
                len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and node.args[1].value.startswith("__")
            )
        ):
            evidence_lines.append(node.lineno)
    return min(evidence_lines) if evidence_lines else None


def _module_patch_seam_items(
    tree: ast.Module,
    *,
    relative_path: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for scope, scope_node in _scope_nodes(tree):
        line = _module_patch_seam_line(scope_node)
        if line is None:
            continue
        snippet = f"module patch seam in {scope}"
        items.append(
            {
                "detector": "python_module_patch_seam",
                "id": (
                    "structure:legacy_override_or_monkeypatch:python_module_patch_seam:"
                    f"{relative_path}:{scope}"
                ),
                "kind": "legacy_override_or_monkeypatch",
                "line": line,
                "path": relative_path,
                "snippet": snippet,
                "text": snippet,
            }
        )
    return items


def _python_structure_items(
    path: Path,
    text: str,
    *,
    root: Path,
) -> list[dict[str, Any]]:
    if path.suffix != ".py":
        return []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    relative_path = _relative(path, root=root)
    return [
        *_same_name_reexport_items(tree, path=path, relative_path=relative_path),
        *_import_star_facade_items(tree, path=path, relative_path=relative_path),
        *_module_patch_seam_items(tree, relative_path=relative_path),
    ]


def collect_compat_items(files: Sequence[Path], *, root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    text_occurrences: Counter[tuple[str, str]] = Counter()
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        relative_path = _relative(path, root=root)
        structural_items = _python_structure_items(path, text, root=root)
        structural_kinds = {item["kind"] for item in structural_items}
        for line_no, line in enumerate(text.splitlines(), start=1):
            kind = classify_line(path, line)
            if kind is None:
                continue
            if kind in structural_kinds and (
                kind == "legacy_override_or_monkeypatch" or line_no <= 8
            ):
                continue
            snippet = _snippet(line)
            occurrence_key = (kind, relative_path)
            text_occurrences[occurrence_key] += 1
            items.append(
                {
                    "detector": "text_marker",
                    "id": _text_item_id(
                        kind=kind,
                        path=relative_path,
                        occurrence=text_occurrences[occurrence_key],
                    ),
                    "kind": kind,
                    "line": line_no,
                    "path": relative_path,
                    "snippet": snippet,
                    "text": snippet,
                }
            )
        items.extend(structural_items)
    return sorted(
        items,
        key=lambda item: (item["path"], item["line"], item["kind"], item["id"]),
    )


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


def write_compat_report(
    path: str | Path, report: dict[str, Any], *, root: Path = REPO_ROOT
) -> Path:
    target = _resolve(path, root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def compatibility_regressions(
    report: dict[str, Any],
    baseline: dict[str, Any],
) -> list[str]:
    baseline_item_ids = baseline.get("item_ids")
    report_items = report.get("items")
    if isinstance(baseline_item_ids, list) and isinstance(report_items, list):
        allowed_ids = {str(item_id) for item_id in baseline_item_ids}
        actual_ids = {str(item["id"]) for item in report_items}
        return [
            f"new compatibility item: {item_id}" for item_id in sorted(actual_ids - allowed_ids)
        ]

    allowed = {
        str(kind): int(limit) for kind, limit in dict(baseline.get("max_by_kind") or {}).items()
    }
    regressions: list[str] = []
    actual = dict(report["summary"]["by_kind"])
    for kind in COMPAT_KINDS:
        count = int(actual.get(kind, 0))
        maximum = int(allowed.get(kind, 0))
        if count > maximum:
            regressions.append(f"{kind} grew: {count} > {maximum}")
    allowed_total = int(baseline.get("max_total", sum(allowed.values())))
    if int(report["summary"]["total"]) > allowed_total:
        regressions.append(
            f"compatibility inventory grew: {report['summary']['total']} > {allowed_total}"
        )
    return regressions


def load_compatibility_baseline(path: str | Path, *, root: Path) -> dict[str, Any]:
    target = _resolve(path, root=root)
    return json.loads(target.read_text(encoding="utf-8"))


def _kind_from_item_id(item_id: str) -> str:
    parts = item_id.split(":", 3)
    if len(parts) < 3 or parts[0] not in {"structure", "text"}:
        raise ValueError(f"invalid compatibility item ID: {item_id}")
    kind = parts[1]
    if kind not in COMPAT_KINDS:
        raise ValueError(f"invalid compatibility kind in item ID: {item_id}")
    return kind


def _canonical_gate_configuration(
    args: argparse.Namespace,
) -> tuple[Path, tuple[str, ...], Path, dict[str, Any]]:
    root = Path(args.root).resolve()
    canonical_root = REPO_ROOT.resolve()
    canonical_baseline = (canonical_root / DEFAULT_BASELINE_JSON).resolve()
    requested_baseline = _resolve(args.baseline_json, root=root).resolve()
    invalid_options: list[str] = []
    if root != canonical_root:
        invalid_options.append("--root")
    if args.scan_path:
        invalid_options.append("--scan-path")
    if requested_baseline != canonical_baseline:
        invalid_options.append("--baseline-json")
    if invalid_options:
        joined = ", ".join(invalid_options)
        raise ValueError(
            "compatibility regression gate uses the repository's canonical policy; "
            f"the following override(s) are not allowed: {joined}"
        )
    baseline = load_compatibility_baseline(canonical_baseline, root=canonical_root)
    if int(baseline.get("schema_version", 0)) != BASELINE_SCHEMA_VERSION:
        raise ValueError(
            "compatibility baseline schema_version must match the canonical "
            f"version {BASELINE_SCHEMA_VERSION}"
        )
    item_ids = baseline.get("item_ids")
    if not isinstance(item_ids, list) or any(not isinstance(item_id, str) for item_id in item_ids):
        raise ValueError("compatibility baseline must contain a string item_ids inventory")
    if item_ids != sorted(set(item_ids)):
        raise ValueError("compatibility baseline item_ids must be sorted and unique")
    expected_counts = Counter(_kind_from_item_id(item_id) for item_id in item_ids)
    configured_counts = {
        str(kind): int(count) for kind, count in dict(baseline.get("max_by_kind") or {}).items()
    }
    canonical_counts = {kind: expected_counts.get(kind, 0) for kind in COMPAT_KINDS}
    if configured_counts != canonical_counts:
        raise ValueError("compatibility baseline max_by_kind must match its item_ids inventory")
    if int(baseline.get("max_total", -1)) != len(item_ids):
        raise ValueError("compatibility baseline max_total must match its item_ids inventory")
    return canonical_root, DEFAULT_SCAN_PATHS, canonical_baseline, baseline


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
    parser.add_argument(
        "--baseline-json",
        default=str(DEFAULT_BASELINE_JSON),
        help="Versioned compatibility debt baseline used by --fail-on-regression.",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Fail when compatibility inventory grows beyond its versioned baseline.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.fail_on_regression:
        try:
            root, scan_paths, baseline_path, baseline = _canonical_gate_configuration(args)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"blocking": True, "error": str(exc), "status": "invalid"}))
            return 2
    else:
        root = Path(args.root).resolve()
        scan_paths = tuple(args.scan_path) or DEFAULT_SCAN_PATHS
        baseline_path = _resolve(args.baseline_json, root=root)
        baseline = None
    report = build_compat_report(root=root, scan_paths=scan_paths)
    regressions = (
        compatibility_regressions(
            report,
            baseline
            if baseline is not None
            else load_compatibility_baseline(baseline_path, root=root),
        )
        if args.fail_on_regression
        else []
    )
    report["regressions"] = regressions
    report["summary"]["blocking"] = bool(regressions)
    target = write_compat_report(args.report_json, report, root=root)
    print(
        json.dumps(
            {
                "blocking": bool(regressions),
                "by_kind": report["summary"]["by_kind"],
                "report_json": str(target),
                "regressions": regressions,
                "status": report["summary"]["status"],
                "total": report["summary"]["total"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
