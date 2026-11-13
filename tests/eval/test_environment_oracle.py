"""Offline checks for candidate-scoped environment oracles."""

from __future__ import annotations

import sys
from dataclasses import replace
from difflib import unified_diff
from pathlib import Path

import pytest
from langchain.messages import AIMessage

from focus_agent.capabilities.sandbox_execution import SandboxBackendUnavailableError
from focus_agent.capabilities.sandbox_execution_backends import (
    LocalSubprocessSandboxBackend,
    SandboxExecutionService,
)
from focus_agent.eval.environment_oracle import (
    EnvironmentOracleResult,
    run_environment_oracle,
)
from focus_agent.eval.environment_oracle import (
    WorkspaceCommandOracle as _WorkspaceCommandOracle,
)
from focus_agent.eval.runner import run_case as run_production_case

from .judges.environment_judge import EnvironmentJudge
from .metrics import aggregate_metrics
from .runner import run_case
from .schema import EvalCase

_BUGGY_SOLUTION = """\
def add(left, right):
    return left - right
"""

_INDEPENDENT_TEST = """\
import runpy
import os
import unittest
from pathlib import Path

add = runpy.run_path(str(Path(os.environ["ORACLE_CANDIDATE_ROOT"]) / "solution.py"))["add"]


class AdditionTest(unittest.TestCase):
    def test_adds_positive_and_negative_numbers(self):
        self.assertEqual(add(2, 3), 5)
        self.assertEqual(add(-2, 3), 1)


if __name__ == "__main__":
    unittest.main()
"""

_GOLD_PATCH = """\
--- a/solution.py
+++ b/solution.py
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left - right
+    return left + right
"""


def _answer_script(messages, allow_tools):  # noqa: ARG001
    return AIMessage(content=_GOLD_PATCH)


@pytest.fixture(autouse=True)
def _use_existing_local_sandbox(monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_SANDBOX_BACKEND", "local")


def _code_case(test_path: str = "test_solution.py") -> EvalCase:
    return EvalCase.from_dict(
        {
            "id": "workspace_addition",
            "input": {"user_message": "Fix addition."},
            "expected": {},
            "environment": {
                "oracle": {
                    "type": "workspace_command",
                    "files": {"solution.py": _BUGGY_SOLUTION},
                    "oracle_files": {test_path: _INDEPENDENT_TEST},
                    "command": [sys.executable, "-I", "-B", test_path],
                    "timeout_s": 10,
                }
            },
            "judge": {"rule": False, "llm": {"enabled": False}},
        }
    )


def _oracle() -> _WorkspaceCommandOracle:
    return _WorkspaceCommandOracle(
        sandbox=SandboxExecutionService(
            primary_backend=LocalSubprocessSandboxBackend(),
            allow_fallback=False,
        )
    )


def _verdict(result, kind: str):
    return next(verdict for verdict in result.verdicts if verdict.kind == kind)


def test_empty_patch_fails_and_gold_patch_passes():
    empty_patch = _oracle().validate(case=_code_case(), candidate_patch="")
    gold_patch = _oracle().validate(case=_code_case(), candidate_patch=_GOLD_PATCH)

    assert empty_patch is not None
    assert empty_patch.status == "failed"
    assert empty_patch.command["exit_code"] == 1
    assert "AssertionError" in empty_patch.stderr
    assert gold_patch is not None
    assert gold_patch.status == "passed"
    assert gold_patch.command["exit_code"] == 0
    assert gold_patch.environment["sandbox_backend"] == "local_subprocess"
    assert gold_patch.environment["workspace_mode"] == "host"
    assert gold_patch.environment["fallback_used"] is True
    assert gold_patch.environment["degraded_reason"] == "local_host_execution"


def test_nested_oracle_tests_preserve_layout_and_command():
    case = _code_case(test_path="tests/test_solution.py")
    case.environment["oracle"]["files"]["tests/test_existing.py"] = "# candidate-owned\n"

    class InspectingBackend(LocalSubprocessSandboxBackend):
        def run(self, request):
            root = Path(request.workspace_root)
            assert (root / "oracle/tests/test_solution.py").is_file()
            assert not (root / "oracle/test_solution.py").exists()
            assert not (root / "candidate/tests/test_solution.py").exists()
            assert (root / "candidate/tests/test_existing.py").is_file()
            assert (root / "candidate/solution.py").is_file()
            assert request.command[-1] == "tests/test_solution.py"
            assert request.command[0] == "python3"
            assert request.env["ORACLE_CANDIDATE_ROOT"] == "."
            return super().run(request)

    oracle = _WorkspaceCommandOracle(
        sandbox=SandboxExecutionService(
            primary_backend=InspectingBackend(),
            allow_fallback=False,
        )
    )
    result = oracle.validate(case=case, candidate_patch=_GOLD_PATCH)

    assert result is not None
    assert result.status == "passed", result.stderr
    assert result.command["argv"] == [
        sys.executable,
        "-I",
        "-B",
        "tests/test_solution.py",
    ]


def test_nested_unittest_discovery_supports_normal_imports_and_file_layout():
    case = _code_case(test_path="tests/test_solution.py")
    case.environment["oracle"]["oracle_files"]["tests/test_solution.py"] = """\
from pathlib import Path
import unittest

from solution import add


class AdditionTest(unittest.TestCase):
    def test_addition_and_project_layout(self):
        self.assertEqual(add(2, 3), 5)
        self.assertTrue((Path(__file__).resolve().parents[1] / "solution.py").is_file())
"""
    case.environment["oracle"]["command"] = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
    ]

    gold = _oracle().validate(case=case, candidate_patch=_GOLD_PATCH)
    empty = _oracle().validate(case=case, candidate_patch="")

    assert gold is not None
    assert gold.status == "passed", gold.stderr
    assert "Ran 1 test" in gold.stderr
    assert empty is not None
    assert empty.status == "failed"


def test_checker_exit_two_is_not_misreported_as_patch_failure():
    case = _code_case(test_path="check.py")
    case.environment["oracle"]["oracle_files"]["check.py"] = "raise SystemExit(2)\n"
    case.environment["oracle"]["command"] = [sys.executable, "check.py"]

    result = _oracle().validate(case=case, candidate_patch=_GOLD_PATCH)

    assert result is not None
    assert result.status == "failed"
    assert result.command["exit_code"] == 2
    assert result.command["driver_exit_code"] == 1
    assert result.reason == "workspace command exited with code 2"


def test_checker_exit_code_survives_output_truncation():
    case = _code_case(test_path="check.py")
    case.environment["oracle"]["oracle_files"]["check.py"] = (
        "print('x' * 1000)\nraise SystemExit(7)\n"
    )
    case.environment["oracle"]["command"] = [sys.executable, "check.py"]
    case.environment["oracle"]["max_output_chars"] = 100

    result = _oracle().validate(case=case, candidate_patch=_GOLD_PATCH)

    assert result is not None
    assert result.status == "failed"
    assert result.command["exit_code"] == 7
    assert result.command["driver_exit_code"] == 1
    assert result.reason == "workspace command exited with code 7"
    assert len(result.stdout) <= 100


def test_command_launch_failure_is_environment_invalid():
    case = _code_case()
    case.environment["oracle"]["command"] = ["/definitely/missing/oracle-command"]

    result = _oracle().validate(case=case, candidate_patch=_GOLD_PATCH)

    assert result is not None
    assert result.status == "environment_invalid"
    assert "launch failed" in result.reason


def test_multiple_fenced_patches_preserve_trailing_context_lines():
    case = _code_case()
    case.environment["oracle"]["files"]["other.py"] = "def value():\n    return 1\n"
    second_patch = """\
--- a/other.py
+++ b/other.py
@@ -1,2 +1,2 @@
-def value():
+def answer():
     return 1
"""
    answer = f"```diff\n{_GOLD_PATCH}```\n```diff\n{second_patch}```\n"

    result = _oracle().validate(case=case, candidate_patch=answer)

    assert result is not None
    assert result.status == "passed", result.stderr


def test_candidate_cannot_rewrite_oracle_tests():
    test_path = "check.py"
    tampered_patch = (
        _GOLD_PATCH
        + "\n"
        + "\n".join(
            unified_diff(
                _INDEPENDENT_TEST.splitlines(),
                ["pass"],
                fromfile=test_path,
                tofile=test_path,
                lineterm="",
            )
        )
    )

    result = _oracle().validate(
        case=_code_case(test_path=test_path),
        candidate_patch=tampered_patch,
    )

    assert result is not None
    assert result.status == "failed"
    assert result.command["exit_code"] is None
    assert result.command["driver_exit_code"] == 2
    assert "could not be applied" in result.reason


@pytest.mark.parametrize(
    ("test_path", "link_path", "target"),
    [
        ("check.py", "check.py", "/dev/null"),
        ("tests/test_solution.py", "tests", "/tmp"),
    ],
)
def test_candidate_symlinks_cannot_escape_oracle_overlay(test_path, link_path, target):
    symlink_patch = f"""\
diff --git a/{link_path} b/{link_path}
new file mode 120000
--- /dev/null
+++ b/{link_path}
@@ -0,0 +1 @@
+{target}
\\ No newline at end of file
"""

    result = _oracle().validate(
        case=_code_case(test_path=test_path),
        candidate_patch=_GOLD_PATCH + "\n" + symlink_patch,
    )

    assert result is not None
    assert result.status == "failed"
    assert result.command["exit_code"] is None
    assert result.command["driver_exit_code"] == 2
    assert "symlink" in result.stderr
    assert "could not be applied" in result.reason


def test_invalid_candidate_patch_is_an_agent_failure_not_environment_invalid():
    result = _oracle().validate(case=_code_case(), candidate_patch="not a unified diff")

    assert result is not None
    assert result.status == "failed"
    assert result.command["exit_code"] is None
    assert "could not be applied" in result.reason


def test_environment_judge_uses_oracle_state_only_for_explicit_oracle_source():
    case = _code_case()
    case.environment["assertions"] = [
        {"source": "oracle", "path": "status", "equals": "passed"},
        {"path": "status", "equals": "final"},
    ]

    verdict = EnvironmentJudge().evaluate(
        case=case,
        answer="",
        trajectory=[],
        state={"status": "final"},
        oracle_state={"status": "passed"},
    )

    assert verdict.passed, verdict.reasoning
    assert verdict.kind == "environment"
    assert [item["source"] for item in verdict.details["assertions"]] == [
        "oracle",
        "final_state",
    ]

    case.environment["assertions"] = [{"source": "oracle", "path": "status", "equals": "passed"}]
    missing_oracle = EnvironmentJudge().evaluate(
        case=case,
        answer="",
        trajectory=[],
        state={"status": "passed"},
    )
    assert not missing_oracle.passed
    assert missing_oracle.details["assertions"][0]["source"] is None
    assert "not found in oracle" in missing_oracle.reasoning


@pytest.mark.parametrize("runner", [run_case, run_production_case])
def test_runners_wire_oracle_result_into_explicit_oracle_assertions(runner, eval_runtime_factory):
    case = _code_case()
    case.environment["assertions"] = [{"source": "oracle", "path": "status", "equals": "passed"}]

    result = runner(case, runtime=eval_runtime_factory(script=_answer_script), timeout_s=0)

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    assert [verdict.kind for verdict in result.verdicts] == [
        "environment_oracle",
        "environment",
    ]
    assert _verdict(result, "environment").details["assertions"][0]["actual"] == "passed"


def test_environment_judge_preserves_falsey_oracle_mapping():
    class FalseyState(dict):
        def __bool__(self):
            return False

    case = _code_case()
    case.environment["assertions"] = [{"source": "oracle", "path": "status", "equals": "passed"}]

    verdict = EnvironmentJudge().evaluate(
        case=case,
        answer="",
        trajectory=[],
        oracle_state=FalseyState(status="passed"),
    )

    assert verdict.passed, verdict.reasoning


def test_run_case_uses_agent_answer_as_candidate_patch(eval_runtime_factory):
    result = run_case(
        _code_case(), runtime=eval_runtime_factory(script=_answer_script), timeout_s=0
    )

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    assert [verdict.kind for verdict in result.verdicts] == ["environment_oracle"]
    assert _verdict(result, "environment_oracle").details["status"] == "passed"
    assert result.environment_invalid is False


def test_production_runner_uses_the_same_candidate_contract(eval_runtime_factory):
    result = run_production_case(
        _code_case(), runtime=eval_runtime_factory(script=_answer_script), timeout_s=0
    )

    assert result.passed
    assert _verdict(result, "environment_oracle").details["status"] == "passed"


def test_empty_agent_patch_fails_without_becoming_environment_invalid(eval_runtime_factory):
    def empty_answer(messages, allow_tools):  # noqa: ARG001
        return AIMessage(content="")

    result = run_case(_code_case(), runtime=eval_runtime_factory(script=empty_answer), timeout_s=0)

    assert not result.passed
    assert result.error is None
    assert result.environment_invalid is False
    assert _verdict(result, "environment_oracle").details["status"] == "failed"


def test_run_case_without_oracle_preserves_legacy_verdicts(eval_runtime_factory):
    case = EvalCase.from_dict(
        {
            "id": "legacy_environment_only",
            "input": {"user_message": "hello"},
            "expected": {},
            "environment": {"assertions": [{"path": "llm_calls", "exists": True}]},
            "judge": {"rule": False, "llm": {"enabled": False}},
        }
    )

    result = run_case(case, runtime=eval_runtime_factory(script=_answer_script), timeout_s=0)

    assert result.passed
    assert [verdict.kind for verdict in result.verdicts] == ["environment"]
    assert result.verdicts[0].details["assertions"][0]["source"] == "final_state"


def test_legacy_injected_judge_signature_stays_compatible(eval_runtime_factory):
    class LegacyJudge:
        def evaluate(self, *, case, answer, trajectory, state, before_state):  # noqa: ARG002
            from focus_agent.eval.schema import JudgeVerdict

            return JudgeVerdict(kind="environment", passed=True)

    case = EvalCase.from_dict(
        {
            "id": "legacy_custom_judge",
            "input": {"user_message": "hello"},
            "expected": {},
            "environment": {"assertions": [{"path": "llm_calls", "exists": True}]},
            "judge": {"rule": False, "llm": {"enabled": False}},
        }
    )
    runtime = replace(eval_runtime_factory(script=_answer_script), environment_judge=LegacyJudge())

    result = run_case(case, runtime=runtime, timeout_s=0)

    assert result.passed
    assert [verdict.kind for verdict in result.verdicts] == ["environment"]


def test_legacy_custom_judge_gets_no_oracle_state_without_oracle_assertions(
    eval_runtime_factory,
):
    class LegacyJudge:
        def evaluate(self, *, case, answer, trajectory, state, before_state):  # noqa: ARG002
            from focus_agent.eval.schema import JudgeVerdict

            return JudgeVerdict(kind="environment", passed=True)

    case = _code_case()
    case.environment["assertions"] = [{"path": "llm_calls", "exists": True}]
    runtime = replace(eval_runtime_factory(script=_answer_script), environment_judge=LegacyJudge())

    result = run_case(case, runtime=runtime, timeout_s=0)

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    assert [verdict.kind for verdict in result.verdicts] == [
        "environment_oracle",
        "environment",
    ]


def test_environment_invalid_has_a_distinct_result_and_metric(eval_runtime_factory, monkeypatch):
    class UnavailableService:
        def run(self, request):  # noqa: ARG002
            raise SandboxBackendUnavailableError("sandbox unavailable for test")

    monkeypatch.setattr(
        "focus_agent.eval.environment_oracle.default_sandbox_execution_service",
        lambda allow_fallback: UnavailableService(),
    )

    result = run_case(
        _code_case(), runtime=eval_runtime_factory(script=_answer_script), timeout_s=0
    )

    assert not result.passed
    assert result.error is None
    assert result.environment_invalid is True
    assert _verdict(result, "environment_oracle").details["status"] == "environment_invalid"
    summary = aggregate_metrics([result])
    assert summary.total == 1
    assert summary.environment_invalid == 1
    assert summary.failed == 0
    assert summary.errors == 0
    assert summary.failed_case_ids == []
    assert summary.environment_invalid_case_ids == [result.case_id]
    assert summary.model_matrix == {}


def test_malformed_configuration_is_environment_invalid():
    case = _code_case()
    case.environment["oracle"]["timeout_s"] = float("nan")

    result = _oracle().validate(case=case, candidate_patch=_GOLD_PATCH)

    assert result is not None
    assert result.status == "environment_invalid"


def test_falsey_custom_oracle_is_not_replaced():
    class FalseyOracle:
        def __bool__(self):
            return False

        def validate(self, *, case, candidate_patch=""):
            return EnvironmentOracleResult(status="passed", reason="custom oracle")

    custom = FalseyOracle()
    dispatched = run_environment_oracle(_code_case(), candidate_patch=_GOLD_PATCH, oracle=custom)
    assert dispatched is not None
    assert dispatched.reason == "custom oracle"


def test_falsey_sandbox_service_is_not_replaced():
    class FalseyService:
        def __init__(self):
            self.delegate = SandboxExecutionService(
                primary_backend=LocalSubprocessSandboxBackend(),
                allow_fallback=False,
            )
            self.calls = 0

        def __bool__(self):
            return False

        def run(self, request):
            self.calls += 1
            return self.delegate.run(request)

    service = FalseyService()
    oracle = _WorkspaceCommandOracle(sandbox=service)

    result = oracle.validate(case=_code_case(), candidate_patch=_GOLD_PATCH)

    assert result is not None
    assert result.status == "passed", result.stderr
    assert service.calls == 1


def test_result_snapshot_is_deep_copied():
    result = EnvironmentOracleResult(
        status="passed",
        reason="ok",
        environment={"nested": {"value": 1}},
        command={"argv": ["python", "-I"]},
    )
    snapshot = result.to_dict()
    snapshot["environment"]["nested"]["value"] = 2
    snapshot["command"]["argv"].append("mutated")

    assert result.environment["nested"]["value"] == 1
    assert result.command["argv"] == ["python", "-I"]
