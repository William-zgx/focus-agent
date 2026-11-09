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
        assert "focus_agent.engine.loop.builder" not in sys.modules
        assert "focus_agent.harness.agents.factory" not in sys.modules
        """,
        """
        import sys

        from focus_agent.engine.tools.execution import HarnessToolServices

        assert HarnessToolServices.__name__ == "HarnessToolServices"
        assert "focus_agent.engine.loop.builder" not in sys.modules
        assert "focus_agent.engine.model_factory" not in sys.modules
        assert "focus_agent.harness.agents.factory" not in sys.modules
        """,
        """
        import sys

        from focus_agent.harness.agents.mention import parse_mentions

        assert callable(parse_mentions)
        assert "focus_agent.harness.agents.factory" not in sys.modules
        assert "focus_agent.engine.loop.builder" not in sys.modules
        """,
    ],
)
def test_leaf_modules_import_cleanly_in_fresh_process(code: str) -> None:
    result = _run_cold_import(code)

    assert result.returncode == 0, result.stderr or result.stdout


def test_tools_package_does_not_eagerly_import_execution() -> None:
    result = _run_cold_import(
        """
        import sys

        import focus_agent.engine.tools as tools

        assert "focus_agent.engine.tools.execution" not in sys.modules
        assert "focus_agent.engine.loop.builder" not in sys.modules
        assert "focus_agent.engine.model_factory" not in sys.modules
        assert not hasattr(tools, "HarnessToolServices")
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
        assert "focus_agent.engine.loop.builder" not in sys.modules

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
