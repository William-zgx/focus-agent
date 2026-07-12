from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "browser-smoke.yml"
BOOL_TAG = "tag:yaml.org,2002:bool"


class _GitHubWorkflowLoader(yaml.SafeLoader):
    pass


_GitHubWorkflowLoader.yaml_implicit_resolvers = copy.deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)
for initial in ("o", "O"):
    _GitHubWorkflowLoader.yaml_implicit_resolvers[initial] = [
        (tag, pattern)
        for tag, pattern in _GitHubWorkflowLoader.yaml_implicit_resolvers.get(initial, [])
        if tag != BOOL_TAG
    ]


def _load_workflow() -> dict[str, Any]:
    workflow = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        Loader=_GitHubWorkflowLoader,
    )
    assert isinstance(workflow, dict)
    return workflow


def test_browser_smoke_workflow_is_an_unfiltered_stable_required_check() -> None:
    workflow = _load_workflow()
    triggers = workflow["on"]
    job = workflow["jobs"]["browser-smoke"]

    assert workflow["name"] == "Browser Smoke"
    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"}
    assert "paths" not in triggers["push"]
    assert triggers["pull_request"] is None
    assert job["name"] == "Real Chrome browser smoke"
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 30
    assert "if" not in job
    assert "needs" not in job


def test_browser_smoke_workflow_installs_chrome_and_runs_real_interactions() -> None:
    workflow = _load_workflow()
    job = workflow["jobs"]["browser-smoke"]
    steps = job["steps"]
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    chrome_step = next(
        step for step in steps if step["name"] == "Install Google Chrome with Playwright"
    )
    smoke_step = next(
        step for step in steps if step["name"] == "Run real Chrome interaction smoke gates"
    )
    start_step = next(
        step for step in steps if step["name"] == "Start built application and wait for health"
    )

    assert "playwright@1.55.0 install --with-deps chrome" in chrome_step["run"]
    assert "command -v google-chrome" in chrome_step["run"]
    assert "/opt/google/chrome/chrome" in chrome_step["run"]
    assert 'if [ -z "$chrome_path" ]' in chrome_step["run"]
    assert "CHROME_PATH" in chrome_step["run"]
    assert "make web-build" in source
    assert "./scripts/run-api.sh" in start_step["run"]
    assert "curl --fail --silent http://127.0.0.1:8000/healthz" in start_step["run"]
    assert "scripts/ui_smoke_test.py" in smoke_step["run"]
    assert "--app-url http://127.0.0.1:8000/app/" in smoke_step["run"]
    assert "scripts/observability_ui_smoke.py" in smoke_step["run"]
    assert "--scenario all" in smoke_step["run"]
    assert "--no-start-api" in smoke_step["run"]
    assert 'if [ "$ui_status" -ne 0 ] || [ "$observability_status" -ne 0 ]' in smoke_step["run"]


def test_browser_smoke_workflow_is_secret_free_and_fail_closed_with_diagnostics() -> None:
    workflow = _load_workflow()
    job = workflow["jobs"]["browser-smoke"]
    steps = job["steps"]
    job_source = yaml.safe_dump(job, sort_keys=True)

    fixture_step = next(
        step for step in steps if step["name"] == "Start deterministic local model fixture"
    )
    diagnostics_step = next(step for step in steps if step["name"] == "Capture failure diagnostics")
    cleanup_step = next(step for step in steps if step["name"] == "Stop background services")
    upload_step = next(step for step in steps if step["name"] == "Upload browser smoke diagnostics")

    assert "secrets." not in job_source
    assert job["env"]["OPENAI_BASE_URL"] == "http://127.0.0.1:18080/v1"
    assert job["env"]["DATABASE_URI"].startswith("postgresql://focus_agent:")
    assert job["services"]["postgres"]["image"] == "postgres:16-bookworm"
    assert "/v1/chat/completions" in fixture_step["run"]
    assert '"stream":' not in fixture_step["run"]
    assert 'request.get("stream")' in fixture_step["run"]
    assert 'fixture_pgid="$(ps -o pgid= -p "$fixture_pid"' in fixture_step["run"]
    assert 'if [ "$fixture_pgid" != "$fixture_pid" ]' in fixture_step["run"]
    assert diagnostics_step["if"] == "failure()"
    assert "mkdir -p reports/browser-smoke" in diagnostics_step["run"]
    assert "--screenshot=reports/browser-smoke/failure-page.png" in diagnostics_step["run"]
    assert cleanup_step["if"] == "always()"
    assert '[[ "$pid" =~ ^[1-9][0-9]*$ ]]' in cleanup_step["run"]
    assert "kill -TERM" in cleanup_step["run"]
    assert 'kill -0 -- "-$pid"' in cleanup_step["run"]
    assert "survived cleanup" in cleanup_step["run"]
    assert 'exit "$cleanup_failed"' in cleanup_step["run"]
    assert upload_step["if"] == "always()"
    assert upload_step["uses"] == "actions/upload-artifact@v7"
    assert upload_step["with"]["if-no-files-found"] == "error"
