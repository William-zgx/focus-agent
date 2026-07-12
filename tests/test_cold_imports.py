from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _run_cold_import(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    pythonpath = str(_REPOSITORY_ROOT / "src")
    if existing_pythonpath:
        pythonpath = os.pathsep.join((pythonpath, existing_pythonpath))
    env["PYTHONPATH"] = pythonpath
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=_REPOSITORY_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "code",
    [
        """
        import sys

        from focus_agent.engine.model_factory import GraphModelFactory

        assert GraphModelFactory.__name__ == "GraphModelFactory"
        assert "focus_agent.engine.graph.builder" not in sys.modules
        assert "focus_agent.harness.agents.factory" not in sys.modules
        """,
        """
        import sys

        from focus_agent.engine.graph.tool_execution import HarnessToolServices

        assert HarnessToolServices.__name__ == "HarnessToolServices"
        assert "focus_agent.engine.graph.builder" not in sys.modules
        assert "focus_agent.engine.model_factory" not in sys.modules
        assert "focus_agent.harness.agents.factory" not in sys.modules
        """,
        """
        import sys

        from focus_agent.harness.agents.mention import parse_mentions

        assert callable(parse_mentions)
        assert "focus_agent.harness.agents.factory" not in sys.modules
        assert "focus_agent.engine.graph.builder" not in sys.modules
        """,
    ],
)
def test_leaf_modules_import_cleanly_in_fresh_process(code: str) -> None:
    result = _run_cold_import(code)

    assert result.returncode == 0, result.stderr or result.stdout


def test_graph_package_preserves_eager_export_contract_lazily() -> None:
    result = _run_cold_import(
        """
        import importlib
        import sys

        import focus_agent.engine.graph as graph

        assert "focus_agent.engine.graph.builder" not in sys.modules
        assert "focus_agent.engine.model_factory" not in sys.modules

        module_names = (
            "agent_loop",
            "builder",
            "policy",
            "policy_intent",
            "tool_execution",
            "tool_repair",
        )
        modules = [
            importlib.import_module(f"focus_agent.engine.graph.{module_name}")
            for module_name in module_names
        ]
        expected_exports = list(
            dict.fromkeys(
                name
                for module in modules
                for name in module.__all__
            )
        )
        expected_owners = {
            name: module
            for module in modules
            for name in module.__all__
        }

        assert graph.__all__ == expected_exports
        for name in expected_exports:
            assert getattr(graph, name) is getattr(expected_owners[name], name)
        """
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_harness_packages_preserve_public_exports_lazily() -> None:
    result = _run_cold_import(
        """
        import sys

        import focus_agent.harness as harness
        import focus_agent.harness.agents as agents

        assert "focus_agent.harness.agents.factory" not in sys.modules
        assert "focus_agent.engine.graph.builder" not in sys.modules

        from focus_agent.harness.schemas.config import HarnessConfig

        assert harness.HarnessConfig is HarnessConfig
        assert harness.RuntimeHarnessConfig is HarnessConfig
        assert all(getattr(harness, name) is not None for name in harness.__all__)
        assert all(getattr(agents, name) is not None for name in agents.__all__)

        from focus_agent.harness.agents.factory import (
            FocusAgentHarness,
            create_focus_agent,
        )

        assert harness.FocusAgentHarness is FocusAgentHarness
        assert agents.FocusAgentHarness is FocusAgentHarness
        assert agents.create_focus_agent is create_focus_agent
        """
    )

    assert result.returncode == 0, result.stderr or result.stdout
