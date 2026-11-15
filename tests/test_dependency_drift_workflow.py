from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "dependency-drift.yml"


def test_dependency_drift_prepares_node_before_web_install():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["latest-dependencies"]["steps"]
    names = [step["name"] for step in steps]

    setup_node = names.index("Set up Node.js")
    enable_pnpm = names.index("Enable pnpm")
    web_install = names.index("Install Web dependencies")
    pytest = names.index("Run pytest")

    assert setup_node < enable_pnpm < web_install < pytest
    assert steps[setup_node]["uses"] == "actions/setup-node@v6"
    assert steps[setup_node]["with"]["node-version"] == "20"
    assert "corepack enable" in steps[enable_pnpm]["run"]
    assert "corepack prepare pnpm@9.15.9 --activate" in steps[enable_pnpm]["run"]
    assert steps[web_install]["run"] == "make web-install"
    assert steps[pytest]["run"] == "make ci-test"
