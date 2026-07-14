from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from focus_agent import task_cli
from focus_agent.harness.runtime import RunManager
from focus_agent.harness.subagents import SubagentExecutor, SubagentTaskRequest
from focus_agent.harness.subagents.process_runner import (
    ProcessSubagentConfig,
    ProcessSubagentRunner,
    ProcessSubagentTaskRunner,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"


def test_build_command_uses_stable_task_run_protocol():
    runner = ProcessSubagentRunner("/bin/focus-agent")

    command = runner._build_command(
        ProcessSubagentConfig(
            model="test-model",
            system_prompt="system prompt",
            tools_allowed=["read_file", "search_code"],
        ),
        task="review this",
        thread_id="thread-1",
    )

    assert command == [
        "/bin/focus-agent",
        "task",
        "run",
        "--thread-id",
        "thread-1",
        "--model",
        "test-model",
        "--system-prompt",
        "system prompt",
        "--tools",
        "read_file,search_code",
        "--task",
        "review this",
    ]


def test_build_command_omits_unrestricted_tools_flag():
    runner = ProcessSubagentRunner("focus-agent")

    command = runner._build_command(
        ProcessSubagentConfig(model="test-model", system_prompt="", tools_allowed=["*"]),
        task="review this",
        thread_id="thread-1",
    )

    assert "--tools" not in command


def test_task_cli_run_emits_success_envelope(capsys):
    exit_code = task_cli.main(
        [
            "task",
            "run",
            "--thread-id",
            "thread-1",
            "--model",
            "test-model",
            "--system-prompt",
            "be concise",
            "--tools",
            "read_file",
            "--task",
            "summarize this",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "error": None,
        "result": "summarize this",
        "success": True,
        "token_usage": {},
    }


def test_task_cli_module_command_emits_success_without_network():
    env = _module_environment()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "focus_agent.task_cli",
            "task",
            "run",
            "--thread-id",
            "thread-1",
            "--model",
            "test-model",
            "--task",
            "local protocol task",
        ],
        cwd=_REPOSITORY_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "error": None,
        "result": "local protocol task",
        "success": True,
        "token_usage": {},
    }


def test_task_cli_module_command_emits_failure_envelope_without_network():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "focus_agent.task_cli",
            "task",
            "run",
            "--thread-id",
            "thread-1",
            "--model",
            "test-model",
            "--task",
            "",
        ],
        cwd=_REPOSITORY_ROOT,
        env=_module_environment(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout) == {
        "error": "task must not be empty",
        "result": "",
        "success": False,
        "token_usage": {},
    }


def test_runner_parses_success_envelope_from_local_module(tmp_path):
    async def scenario():
        runner = ProcessSubagentRunner(str(_task_cli_script(tmp_path)))
        result = await runner.run(
            ProcessSubagentConfig(model="test-model", system_prompt=""),
            task="local protocol task",
            thread_id="thread-1",
        )

        assert result.success is True
        assert result.output == "local protocol task"
        assert result.error is None
        assert result.token_usage == {}

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("raw", "expected_message"),
    [
        ("not json", "invalid JSON result envelope"),
        ('{"success": true}', "requires string result"),
        ('{"success": false}', "requires string error"),
        ('{"result": "missing success"}', "requires boolean success"),
    ],
)
def test_parse_output_rejects_invalid_envelopes(raw, expected_message):
    output, usage, success, error = ProcessSubagentRunner._parse_output(raw)

    assert output
    assert usage is None
    assert success is False
    assert error is not None
    assert expected_message in error


def test_runner_marks_failed_envelope_as_failure(tmp_path):
    async def scenario():
        runner = ProcessSubagentRunner(
            str(
                _script(
                    tmp_path,
                    "failed-envelope.py",
                    (
                        f"#!{sys.executable}\n"
                        "import json\n"
                        "print(json.dumps({'success': False, 'error': 'child failed'}))\n"
                    ),
                )
            )
        )
        result = await runner.run(
            ProcessSubagentConfig(model="test-model", system_prompt=""),
            task="fail",
            thread_id="thread-1",
        )

        assert result.success is False
        assert result.output == "child failed"
        assert result.error == "child failed"
        assert result.return_code == 0

    asyncio.run(scenario())


def test_process_task_runner_propagates_child_nonzero_to_executor_error_envelope(tmp_path):
    async def scenario():
        runner = ProcessSubagentTaskRunner(
            cli_entry_point=str(
                _script(
                    tmp_path,
                    "nonzero.py",
                    (
                        f"#!{sys.executable}\n"
                        "import sys\n"
                        "print('child exploded', file=sys.stderr)\n"
                        "sys.exit(7)\n"
                    ),
                )
            )
        )
        executor = SubagentExecutor(runner, run_manager=RunManager())

        envelope = await executor.execute(
            SubagentTaskRequest("fail", thread_id="thread-1"),
            tool_call_id="call-1",
        )

        assert envelope.status == "error"
        assert envelope.runtime["error_type"] == "RuntimeError"
        assert "process exited with code 7" in envelope.content

    asyncio.run(scenario())


def test_process_task_runner_propagates_failed_envelope_to_executor_error(tmp_path):
    async def scenario():
        runner = ProcessSubagentTaskRunner(
            cli_entry_point=str(
                _script(
                    tmp_path,
                    "failed-envelope.py",
                    (
                        f"#!{sys.executable}\n"
                        "import json\n"
                        "print(json.dumps({'success': False, 'error': 'child rejected task'}))\n"
                    ),
                )
            )
        )
        executor = SubagentExecutor(runner, run_manager=RunManager())

        envelope = await executor.execute(
            SubagentTaskRequest("fail", thread_id="thread-1"),
            tool_call_id="call-1",
        )

        assert envelope.status == "error"
        assert envelope.runtime["error_type"] == "RuntimeError"
        assert "child rejected task" in envelope.content

    asyncio.run(scenario())


def test_runner_times_out_child_process(tmp_path):
    async def scenario():
        runner = ProcessSubagentRunner(
            str(
                _script(
                    tmp_path,
                    "sleep.py",
                    f"#!{sys.executable}\nimport time\ntime.sleep(1)\n",
                )
            )
        )
        result = await runner.run(
            ProcessSubagentConfig(
                model="test-model",
                system_prompt="",
                timeout_seconds=0.05,
                graceful_shutdown_seconds=0.05,
            ),
            task="timeout",
            thread_id="thread-1",
        )

        assert result.success is False
        assert result.return_code < 0
        assert result.error is not None
        assert "process exited with code" in result.error

    asyncio.run(scenario())


def test_child_environment_is_minimal_and_marks_subagent(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("CUSTOM_PARENT_SETTING", "must-not-leak")
    monkeypatch.setenv("PATH", "/usr/bin")

    environment = ProcessSubagentRunner._child_environment()

    assert environment["FOCUS_AGENT_SUBAGENT"] == "1"
    assert environment["PATH"] == "/usr/bin"
    assert "OPENAI_API_KEY" not in environment
    assert "CUSTOM_PARENT_SETTING" not in environment
    assert set(environment) <= {
        "FOCUS_AGENT_SUBAGENT",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "TMPDIR",
        "TZ",
    }


def _module_environment() -> dict[str, str]:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    paths = [str(_SOURCE_ROOT)]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return environment


def _task_cli_script(directory: Path) -> Path:
    return _script(
        directory,
        "focus-agent",
        (
            "#!"
            f"{sys.executable}\n"
            "import sys\n"
            f"sys.path.insert(0, {str(_SOURCE_ROOT)!r})\n"
            "from focus_agent.task_cli import main\n"
            "raise SystemExit(main())\n"
        ),
    )


def _script(directory: Path, name: str, content: str) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path
