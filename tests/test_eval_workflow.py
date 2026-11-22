from pathlib import Path


def test_continuity_diagnostics_run_in_deterministic_eval_workflow():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "eval.yml").read_text(
        encoding="utf-8"
    )

    assert "-name 'test_handoff_continuity_suite.py'" in workflow
    assert "-name 'test_memory_layered_suite.py'" in workflow
    assert "uv run pytest tests/test_eval_framework.py" in workflow
