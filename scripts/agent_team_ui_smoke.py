#!/usr/bin/env python3
"""Agent Team UI evidence gate with deterministic and explicitly-disabled modes.

The deterministic mode performs source-level contract checks and requires no
browser, Docker daemon, API server, or model provider. Real browser execution
is intentionally disabled until a dedicated provider/browser harness is wired.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_JSON = Path("reports/agent-team-evidence/ui-smoke.json")
REQUIRED_SOURCE_MARKERS = {
    "route": 'path: "/agent-team"',
    "workbench": "AgentTeamCockpit",
    "adoption": 'data-smoke="agent-team-adoption"',
}


def _source_paths(repo_root: Path) -> dict[str, Path]:
    return {
        "route": repo_root / "apps/web/src/app/router.tsx",
        "workbench": repo_root / "apps/web/src/features/agent-team/agent-team-workbench.tsx",
        "adoption": repo_root
        / "apps/web/src/features/agent-team/agent-team-workbench-adoption.tsx",
    }


def deterministic_ui_evidence(*, repo_root: Path = REPO_ROOT) -> dict[str, object]:
    checks: dict[str, bool] = {}
    for name, marker in REQUIRED_SOURCE_MARKERS.items():
        path = _source_paths(repo_root)[name]
        checks[name] = path.is_file() and marker in path.read_text(encoding="utf-8")
    return {
        "mode": "deterministic_fixture",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "requires": ["repository source fixture"],
        "provider_used": False,
        "browser_used": False,
    }


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run(*, mode: str, report_json: Path, repo_root: Path = REPO_ROOT) -> int:
    if mode == "real":
        payload: dict[str, object] = {
            "mode": "real_provider",
            "status": "disabled",
            "reason": (
                "Real Agent Team UI evidence requires an approved browser/provider adapter and is "
                "disabled rather than reported as passed."
            ),
            "provider_used": False,
            "browser_used": False,
        }
        _write_report(report_json, payload)
        print(f"[agent-team-ui-smoke] disabled: {payload['reason']}")
        return 2

    payload = deterministic_ui_evidence(repo_root=repo_root)
    payload["generated_at"] = datetime.now(UTC).isoformat()
    _write_report(report_json, payload)
    print(f"[agent-team-ui-smoke] {payload['status']}: deterministic fixture evidence")
    return 0 if payload["status"] == "passed" else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("deterministic", "real"), default="deterministic")
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run(mode=args.mode, report_json=args.report_json)


if __name__ == "__main__":
    raise SystemExit(main())
