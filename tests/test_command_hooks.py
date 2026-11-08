from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

from focus_agent.capabilities.tool_messages import build_tool_message
from focus_agent.capabilities.tool_runtime import ToolExecutionResult
from focus_agent.config import CommandHookConfig
from focus_agent.engine.graph.tool_result_hooks import _apply_result_hooks
from focus_agent.harness.extensions import ExtensionContext, ExtensionRegistry
from focus_agent.harness.extensions.command_hooks import CommandHooksExtension


def _write_script(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def _hook(path, **overrides) -> CommandHookConfig:
    values = {
        "command": (sys.executable, str(path)),
        "matcher": "*",
        "timeout_seconds": 2.0,
    }
    values.update(overrides)
    return CommandHookConfig(**values)


def test_pre_hook_exit_two_blocks_with_stderr(tmp_path) -> None:
    script = _write_script(
        tmp_path,
        "block_exit.py",
        "import sys\n"
        "sys.stdin.read()\n"
        "sys.stderr.write('blocked by command policy')\n"
        "sys.exit(2)\n",
    )
    extension = CommandHooksExtension(pre_tool_use=(_hook(script),))

    result = extension.on_tool_call(
        ExtensionContext(thread_id="thread-1", run_id="run-1"),
        "lookup",
        {"name": "focus"},
    )

    assert result is not None
    assert result.block is True
    assert result.reason == "blocked by command policy"


def test_pre_hook_json_decision_blocks_and_receives_event_payload(tmp_path) -> None:
    script = _write_script(
        tmp_path,
        "block_json.py",
        "import json, sys\n"
        "event = json.load(sys.stdin)\n"
        "assert event['event'] == 'pre_tool_use'\n"
        "assert event['tool_name'] == 'lookup'\n"
        "assert event['tool_input'] == {'name': 'focus'}\n"
        "assert event['thread_id'] == 'thread-1'\n"
        "assert event['run_id'] == 'run-1'\n"
        "print(json.dumps({'decision': 'block', 'reason': 'JSON policy block'}))\n",
    )
    extension = CommandHooksExtension(pre_tool_use=(_hook(script, matcher="look*"),))

    result = extension.on_tool_call(
        ExtensionContext(thread_id="thread-1", run_id="run-1"),
        "lookup",
        {"name": "focus"},
    )

    assert result is not None
    assert result.block is True
    assert result.reason == "JSON policy block"


def test_pre_hook_timeout_does_not_block_or_log_tool_input(tmp_path, caplog) -> None:
    script = _write_script(tmp_path, "timeout.py", "import time\ntime.sleep(1)\n")
    extension = CommandHooksExtension(
        pre_tool_use=(_hook(script, timeout_seconds=0.05),),
    )

    with caplog.at_level(logging.WARNING):
        result = extension.on_tool_call(
            ExtensionContext(thread_id="thread-1", run_id="run-1"),
            "lookup",
            {"name": "secret-tool-argument"},
        )

    assert result is None
    assert "Command hook timed out" in caplog.text
    assert "secret-tool-argument" not in caplog.text


def test_post_hook_additional_context_reaches_tool_message(tmp_path) -> None:
    script = _write_script(
        tmp_path,
        "additional_context.py",
        "import json, sys\n"
        "event = json.load(sys.stdin)\n"
        "assert event['event'] == 'post_tool_use'\n"
        "assert event['tool_result'] == 'original result'\n"
        "assert event['status'] == 'success'\n"
        "context = 'observed %s on %s/%s' % (\n"
        "    event['tool_input']['name'], event['thread_id'], event['run_id'])\n"
        "print(json.dumps({'additional_context': context}))\n",
    )
    registry = ExtensionRegistry()
    registry.register(CommandHooksExtension(post_tool_use=(_hook(script),)))
    source = ToolExecutionResult(
        index=0,
        message=build_tool_message(
            content="original result",
            tool_call_id="call-1",
            tool_name="lookup",
            status="success",
        ),
    )

    patched = _apply_result_hooks(
        [source],
        services=SimpleNamespace(middleware_stack=None, extension_registry=registry),
        ext_ctx=ExtensionContext(thread_id="thread-1", run_id="run-1"),
        thread_id="thread-1",
        run_id="run-1",
        active_agent_name="focus_agent",
        execution_inputs_by_index={0: SimpleNamespace(args={"name": "focus"})},
    )

    assert patched[0].message.content == ("original result\n\nobserved focus on thread-1/run-1")
    assert source.message.content == "original result"
