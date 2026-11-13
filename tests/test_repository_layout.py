import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONED_SKILL_PREFIXES = (
    ".focus_agent/skills/china-stock-analysis/",
    ".focus_agent/skills/finviz-screener/",
    ".focus_agent/skills/stock-metrics/",
)
VERSIONED_REPORTS = {
    "reports/release-gate/perf-final.json",
    "reports/release-gate/review-report.md",
}


def _ignored_paths(paths: list[str]) -> set[str]:
    completed = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=ROOT,
        input="".join(f"{path}\n" for path in paths),
        capture_output=True,
        text=True,
    )
    assert completed.returncode in {0, 1}, completed.stderr
    return set(completed.stdout.splitlines())


def test_versioned_overlay_exceptions_are_narrow() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", ".focus_agent", "reports"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert tracked
    assert all(
        path.startswith(VERSIONED_SKILL_PREFIXES) or path in VERSIONED_REPORTS for path in tracked
    )
    assert _ignored_paths(tracked) == set()

    local_paths = {
        ".focus_agent/branches.sqlite3",
        ".focus_agent/local.env",
        ".focus_agent/models.toml",
        ".focus_agent/postgres/runtime.env",
        ".focus_agent/sandboxes/threads/local/workspace/output.txt",
        ".focus_agent/skills/china-stock-analysis/.env",
        ".focus_agent/skills/china-stock-analysis/scripts/.cache/local.json",
        ".focus_agent/skills/china-stock-analysis/local.log",
        ".focus_agent/skills/local-only/SKILL.md",
        ".serena/cache/python/raw_document_symbols.pkl",
        "apps/web/reports/visual-baseline/local.json",
        "reports/architecture/latest.json",
        "reports/release-gate/local-only.json",
    }
    assert _ignored_paths(sorted(local_paths)) == local_paths
