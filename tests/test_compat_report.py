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
    assert set(report["items"][0]) == {
        "detector",
        "id",
        "kind",
        "line",
        "path",
        "snippet",
        "text",
    }
    assert all(item["id"] for item in report["items"])


def test_compat_report_cli_writes_json_and_excludes_ignored_dirs(tmp_path: Path, capsys) -> None:
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
            "detector": "text_marker",
            "id": "text:compatibility_shim:src/focus_agent/auth.py:1",
            "kind": "compatibility_shim",
            "line": 1,
            "path": "src/focus_agent/auth.py",
            "snippet": '"""Compatibility shim."""',
            "text": '"""Compatibility shim."""',
        }
    ]
    assert compat_report.DEFAULT_REPORT_JSON == Path("reports/compat/latest.json")


def test_compat_report_detects_python_structures_without_marker_text(tmp_path: Path) -> None:
    _write(
        tmp_path / "src/focus_agent/public_api.py",
        "from .implementation import PublicThing as PublicThing\n",
    )
    _write(
        tmp_path / "src/focus_agent/old_surface.py",
        "from .new_surface import *\n",
    )
    _write(
        tmp_path / "src/focus_agent/patch_surface.py",
        "\n".join(
            [
                "import sys",
                "",
                "def select_handler():",
                '    surface = sys.modules.get("focus_agent.public_api")',
                '    candidate = getattr(surface, "handler", None)',
                "    return candidate or handler",
            ]
        ),
    )
    _write(
        tmp_path / "src/focus_agent/globals_surface.py",
        "\n".join(
            [
                "def invoke():",
                '    setattr(implementation, "handler", globals()["handler"])',
                "    return implementation.handler()",
            ]
        ),
    )
    _write(
        tmp_path / "src/focus_agent/globals_assignment.py",
        "\n".join(
            [
                "def sync_surface():",
                '    globals()["handler"] = implementation.handler',
            ]
        ),
    )
    _write(
        tmp_path / "src/focus_agent/module_injection.py",
        "\n".join(
            [
                "import sys",
                "from types import ModuleType",
                "",
                'sys.modules["focus_agent.synthetic"] = ModuleType("focus_agent.synthetic")',
            ]
        ),
    )

    report = compat_report.build_compat_report(root=tmp_path, scan_paths=["src/focus_agent"])

    assert report["summary"]["by_kind"] == {
        "compatibility_shim": 2,
        "deprecated_route": 0,
        "legacy_override_or_monkeypatch": 4,
        "legacy_state_or_mirror": 0,
        "legacy_template": 0,
    }
    assert {item["detector"] for item in report["items"]} == {
        "python_import_star_facade",
        "python_module_patch_seam",
        "python_same_name_reexport",
    }
    assert {item["path"] for item in report["items"]} == {
        "src/focus_agent/globals_assignment.py",
        "src/focus_agent/globals_surface.py",
        "src/focus_agent/module_injection.py",
        "src/focus_agent/old_surface.py",
        "src/focus_agent/patch_surface.py",
        "src/focus_agent/public_api.py",
    }


def test_compat_report_avoids_common_python_structure_false_positives(tmp_path: Path) -> None:
    _write(
        tmp_path / "src/focus_agent/service.py",
        "\n".join(
            [
                "import sys",
                "from typing import Protocol as Protocol",
                "from .models import *",
                "",
                "def execute():",
                '    module = sys.modules.get("focus_agent.service")',
                '    return getattr(module, "__file__", None)',
                "",
                "def __getattr__(name):",
                "    value = load(name)",
                "    globals()[name] = value",
                "    return value",
            ]
        ),
    )
    _write(tmp_path / "src/focus_agent/pkg/__init__.py", "from .models import *\n")

    report = compat_report.build_compat_report(root=tmp_path, scan_paths=["src/focus_agent"])

    assert report["summary"]["total"] == 0
    assert report["items"] == []


def test_structural_item_ids_do_not_depend_on_line_numbers(tmp_path: Path) -> None:
    target = tmp_path / "src/focus_agent/public_api.py"
    _write(target, "from .implementation import PublicThing as PublicThing\n")
    before = compat_report.build_compat_report(root=tmp_path, scan_paths=["src/focus_agent"])

    _write(target, "\n\nfrom .implementation import PublicThing as PublicThing\n")
    after = compat_report.build_compat_report(root=tmp_path, scan_paths=["src/focus_agent"])

    assert [item["id"] for item in before["items"]] == [item["id"] for item in after["items"]]
    assert before["items"][0]["line"] == 1
    assert after["items"][0]["line"] == 3


def test_compatibility_regression_gate_rejects_category_or_total_growth() -> None:
    report = {
        "summary": {
            "by_kind": {
                "compatibility_shim": 3,
                "deprecated_route": 1,
                "legacy_template": 0,
                "legacy_state_or_mirror": 0,
                "legacy_override_or_monkeypatch": 0,
            },
            "total": 4,
        }
    }
    baseline = {
        "max_by_kind": {
            "compatibility_shim": 2,
            "deprecated_route": 1,
            "legacy_template": 0,
            "legacy_state_or_mirror": 0,
            "legacy_override_or_monkeypatch": 0,
        },
        "max_total": 3,
    }

    assert compat_report.compatibility_regressions(report, baseline) == [
        "compatibility_shim grew: 3 > 2",
        "compatibility inventory grew: 4 > 3",
    ]


def test_compatibility_regression_gate_allows_inventory_reduction() -> None:
    report = {
        "summary": {
            "by_kind": {kind: 0 for kind in compat_report.COMPAT_KINDS},
            "total": 0,
        }
    }
    baseline = {
        "max_by_kind": {kind: 1 for kind in compat_report.COMPAT_KINDS},
        "max_total": len(compat_report.COMPAT_KINDS),
    }

    assert compat_report.compatibility_regressions(report, baseline) == []


def test_compatibility_regression_gate_rejects_new_item_id_at_same_count() -> None:
    report = {
        "summary": {
            "by_kind": {kind: 0 for kind in compat_report.COMPAT_KINDS},
            "total": 1,
        },
        "items": [{"id": "structure:compatibility_shim:new"}],
    }
    baseline = {
        "item_ids": ["structure:compatibility_shim:old"],
        "max_by_kind": {kind: 0 for kind in compat_report.COMPAT_KINDS},
        "max_total": 1,
    }

    assert compat_report.compatibility_regressions(report, baseline) == [
        "new compatibility item: structure:compatibility_shim:new"
    ]


def test_compatibility_regression_gate_allows_item_id_removal() -> None:
    report = {
        "summary": {
            "by_kind": {kind: 0 for kind in compat_report.COMPAT_KINDS},
            "total": 1,
        },
        "items": [{"id": "structure:compatibility_shim:kept"}],
    }
    baseline = {
        "item_ids": [
            "structure:compatibility_shim:kept",
            "structure:compatibility_shim:removed",
        ],
        "max_by_kind": {kind: 0 for kind in compat_report.COMPAT_KINDS},
        "max_total": 2,
    }

    assert compat_report.compatibility_regressions(report, baseline) == []


def test_compatibility_regression_gate_rejects_policy_overrides(capsys) -> None:
    override_sets = [
        ["--root", "/tmp"],
        ["--scan-path", "src/focus_agent/engine"],
        ["--baseline-json", "/tmp/empty-baseline.json"],
    ]

    for override in override_sets:
        assert compat_report.main(["--fail-on-regression", *override]) == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["blocking"] is True
        assert payload["status"] == "invalid"
        assert override[0] in payload["error"]


def test_compat_report_mode_still_allows_policy_overrides(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "custom/compat.py", '"""Compatibility shim."""\n')
    report_json = tmp_path / "report.json"

    assert (
        compat_report.main(
            [
                "--root",
                str(tmp_path),
                "--scan-path",
                "custom",
                "--baseline-json",
                "unused-baseline.json",
                "--report-json",
                str(report_json),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["blocking"] is False
    assert payload["total"] == 1
    assert json.loads(report_json.read_text(encoding="utf-8"))["config"]["scan_paths"] == ["custom"]


def test_repository_baseline_matches_current_inventory_and_blocks_regrowth() -> None:
    root = Path(__file__).resolve().parents[1]
    baseline = compat_report.load_compatibility_baseline(
        "docs/compat-debt-baseline.json",
        root=root,
    )
    report = compat_report.build_compat_report(root=root)

    assert baseline["max_by_kind"] == report["summary"]["by_kind"]
    assert baseline["max_total"] == report["summary"]["total"]
    assert baseline["schema_version"] == compat_report.BASELINE_SCHEMA_VERSION
    assert baseline["item_ids"] == sorted(item["id"] for item in report["items"])

    regressed = {
        "summary": {
            "by_kind": {
                **report["summary"]["by_kind"],
                "legacy_override_or_monkeypatch": (
                    report["summary"]["by_kind"]["legacy_override_or_monkeypatch"] + 1
                ),
            },
            "total": report["summary"]["total"] + 1,
        },
        "items": [
            *report["items"],
            {
                "id": "structure:legacy_override_or_monkeypatch:synthetic",
            },
        ],
    }
    assert compat_report.compatibility_regressions(regressed, baseline) == [
        "new compatibility item: structure:legacy_override_or_monkeypatch:synthetic"
    ]
