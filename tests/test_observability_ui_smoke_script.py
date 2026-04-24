from pathlib import Path


def test_observability_ui_smoke_script_targets_overview_and_trajectory():
    root = Path(__file__).resolve().parents[1]
    script_text = (root / "scripts" / "observability_ui_smoke.py").read_text(encoding="utf-8")

    assert 'DEFAULT_APP_BASE_URL = "http://127.0.0.1:8000/app"' in script_text
    assert "/observability/overview" in script_text
    assert "/observability/trajectory" in script_text
    assert "seed_observability_record" in script_text
    assert "./scripts/run-api.sh" in script_text
    assert "--no-start-api" in script_text
    assert "--scenario" in script_text
    assert '"success", "failed", "zero-step", "missing-detail", "all"' in script_text
    assert "request_id" in script_text
    assert "trace_id" in script_text
    assert "fa-trajectory-overview-metric-card" in script_text
    assert "fa-trajectory-overview-column" in script_text
    assert "fa-observability-correlation-item" in script_text
    assert "fa-trajectory-workbench-rail-section" in script_text
    assert "fa-trajectory-workbench-batch-action-panel" in script_text
    assert "/promote" in script_text
    assert "zero-step" in script_text
    assert "missing-detail" in script_text
