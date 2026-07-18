from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from scripts import agent_team_ui_smoke

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "agent-team-evidence.yml"
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


def test_agent_team_evidence_workflow_runs_deterministic_fixtures_for_prs() -> None:
    workflow = _load_workflow()
    deterministic = workflow["jobs"]["deterministic-fixtures"]
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow["name"] == "Agent Team Evidence"
    assert set(workflow["on"]) == {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert workflow["on"]["pull_request"] is None
    assert workflow["on"]["schedule"] == [{"cron": "23 18 * * *"}]
    assert deterministic["runs-on"] == "ubuntu-latest"
    assert deterministic["timeout-minutes"] == 15
    assert "if" not in deterministic
    assert "make agent-team-evidence" in source
    assert "secrets." not in yaml.safe_dump(deterministic, sort_keys=True)


def test_agent_team_evidence_workflow_limits_real_provider_to_protected_or_nightly_runs() -> None:
    workflow = _load_workflow()
    provider = workflow["jobs"]["real-provider-evidence"]
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert provider["needs"] == "deterministic-fixtures"
    assert provider["if"] == "${{ github.event_name == 'schedule' || github.ref_protected }}"
    assert provider["env"]["OPENAI_API_KEY"] == "${{ secrets.OPENAI_API_KEY }}"
    assert (
        provider["env"]["AGENT_TEAM_REAL_PROVIDER_EVIDENCE_COMMAND"]
        == "${{ vars.AGENT_TEAM_REAL_PROVIDER_EVIDENCE_COMMAND }}"
    )
    assert "--missing-policy fail" in source
    assert "AGENT_TEAM_REAL_PROVIDER_EVIDENCE_COMMAND" in source
    assert '"status": "disabled"' in source
    assert "No provider result was claimed." in source
    assert "bash -lc" in source


def test_agent_team_evidence_disabled_provider_script_writes_valid_report(
    tmp_path: Path,
) -> None:
    workflow = _load_workflow()
    provider = workflow["jobs"]["real-provider-evidence"]
    step = next(
        step
        for step in provider["steps"]
        if step["name"] == "Run configured real-provider evidence or record disabled state"
    )

    result = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env={"AGENT_TEAM_REAL_PROVIDER_EVIDENCE_COMMAND": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    report_path = tmp_path / "reports" / "agent-team-evidence" / "real-provider.json"

    assert result.returncode == 0, result.stderr
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "disabled"
    assert "real-provider evidence disabled" in result.stdout


def test_agent_team_evidence_make_target_only_runs_agent_team_evidence() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "agent-team-evidence:" in makefile
    assert (
        "$(PYTEST) -q tests/integration/agent_team/test_real_worktree_sandbox.py "
        "tests/integration/agent_team/test_chat_isolation.py "
        "tests/test_agent_team_evidence_workflow.py" in makefile
    )
    assert "$(PYTHON) scripts/agent_team_ui_smoke.py --mode deterministic" in makefile
    assert "ui-smoke:" in makefile


def test_agent_team_ui_smoke_deterministic_mode_writes_real_fixture_evidence(
    tmp_path: Path,
) -> None:
    report_json = tmp_path / "deterministic.json"

    exit_code = agent_team_ui_smoke.run(
        mode="deterministic",
        report_json=report_json,
        repo_root=REPO_ROOT,
    )
    report = json.loads(report_json.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["status"] == "passed"
    assert report["mode"] == "deterministic_fixture"
    assert report["provider_used"] is False
    assert report["browser_used"] is False
    assert report["checks"] == {"route": True, "workbench": True, "adoption": True}


def test_agent_team_ui_smoke_real_mode_is_disabled_not_passed(tmp_path: Path) -> None:
    report_json = tmp_path / "real.json"

    exit_code = agent_team_ui_smoke.run(mode="real", report_json=report_json)
    report = json.loads(report_json.read_text(encoding="utf-8"))

    assert exit_code == 2
    assert report["status"] == "disabled"
    assert "disabled rather than reported as passed" in str(report["reason"])


def test_agent_team_docs_keep_readiness_and_durable_resume_boundaries_explicit() -> None:
    rollout = (REPO_ROOT / "docs" / "agent-team-v2-rollout.md").read_text(encoding="utf-8")
    workbench = (REPO_ROOT / "docs" / "agent-team-workbench.md").read_text(encoding="utf-8")
    validation = (REPO_ROOT / "docs" / "validation-runbook.md").read_text(encoding="utf-8")
    environment_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    local_environment_example = (REPO_ROOT / "docs" / "local.env.example").read_text(
        encoding="utf-8"
    )

    for document in (rollout, workbench, validation):
        assert "/v2/agent-team/readiness" in document
        assert "build_agent_team_readiness" in document
        assert "provider" in document.lower()
        assert "docker" in document.lower()
        assert "approval resume" in document.lower()

    assert "Postgres persists v2 execution records" in environment_example
    assert "Approval-resume adapters are not" in environment_example
    assert "AGENT_TEAM_KILL_SWITCH_ENABLED=true" in environment_example
    assert "# AGENT_TEAM_KILL_SWITCH_ENABLED=true" in local_environment_example
    assert "Postgres persists v2 execution" in local_environment_example
    assert "restart-recovery evidence" in local_environment_example
