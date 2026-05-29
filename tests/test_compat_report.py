from __future__ import annotations

import json
from pathlib import Path

from scripts import compat_report


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_compat_report_classifies_core_legacy_inventory(tmp_path: Path) -> None:
    _write(tmp_path / "src/focus_agent/state.py", '"""Compatibility shim."""\n')
    _write(
        tmp_path / "src/focus_agent/core/state.py",
        "# New records should write here and mirror legacy keys for current consumers.\n",
    )
    _write(
        tmp_path / "src/focus_agent/api/routers/agent_team.py",
        '_mark_deprecated_route(response, canonical_path="/v1/agent-team/tasks/1")\n',
    )
    _write(
        tmp_path / "src/focus_agent/services/agent_team/service.py",
        'plan_source="legacy_template"\n',
    )
    _write(
        tmp_path / "src/focus_agent/repositories/postgres_memory_repository.py",
        "_PSYCOPG_MODULE = psycopg  # Preserve the legacy monkeypatch path used by unit tests.\n",
    )
    _write(
        tmp_path / "tests/test_not_inventory.py",
        "def test_regular_pytest_usage(monkeypatch):\n    monkeypatch.setattr(obj, 'x', 1)\n",
    )
    _write(
        tmp_path / "src/focus_agent/fallback.py",
        "# normal provider fallback path without an explicit legacy marker\n",
    )

    report = compat_report.build_compat_report(root=tmp_path, scan_paths=["src", "tests"])

    assert report["summary"]["total"] == 5
    assert report["summary"]["by_kind"] == {
        "compatibility_shim": 1,
        "deprecated_route": 1,
        "legacy_override_or_monkeypatch": 1,
        "legacy_state_or_mirror": 1,
        "legacy_template": 1,
    }
    assert {item["kind"] for item in report["items"]} == set(compat_report.COMPAT_KINDS)
    assert "tests/test_not_inventory.py" not in {item["path"] for item in report["items"]}
    assert "src/focus_agent/fallback.py" not in {item["path"] for item in report["items"]}
    assert set(report["items"][0]) == {"kind", "line", "path", "snippet", "text"}


def test_compat_report_cli_writes_json_and_excludes_ignored_dirs(
    tmp_path: Path, capsys
) -> None:
    _write(tmp_path / "src/focus_agent/auth.py", '"""Compatibility shim."""\n')
    _write(tmp_path / "node_modules/pkg/legacy.py", '"""Compatibility shim."""\n')
    _write(tmp_path / "generated/client.py", "_mark_deprecated_route(response)\n")
    _write(tmp_path / "scripts/compat_report.py", '"legacy_template"\n')
    report_json = tmp_path / "reports/custom/compat.json"

    exit_code = compat_report.main(
        [
            "--root",
            str(tmp_path),
            "--scan-path",
            "src/focus_agent",
            "--scan-path",
            "node_modules",
            "--scan-path",
            "generated",
            "--scan-path",
            "scripts",
            "--report-json",
            str(report_json),
        ]
    )

    stdout = json.loads(capsys.readouterr().out)
    saved = json.loads(report_json.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert stdout["status"] == "issues"
    assert stdout["total"] == 1
    assert stdout["report_json"] == str(report_json)
    assert saved["summary"]["total"] == 1
    assert saved["items"] == [
        {
            "kind": "compatibility_shim",
            "line": 1,
            "path": "src/focus_agent/auth.py",
            "snippet": '"""Compatibility shim."""',
            "text": '"""Compatibility shim."""',
        }
    ]
    assert compat_report.DEFAULT_REPORT_JSON == Path("reports/compat/latest.json")
