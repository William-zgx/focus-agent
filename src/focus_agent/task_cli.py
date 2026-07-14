"""Controlled command-line protocol for process-isolated subagent tasks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    """Build the stable process-subagent command parser."""
    parser = argparse.ArgumentParser(
        prog="focus-agent",
        description="Run controlled process-isolated Focus Agent tasks.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    task = commands.add_parser("task", help="Run a process-isolated task.")
    task_commands = task.add_subparsers(dest="task_command", required=True)
    run = task_commands.add_parser("run", help="Run one task and emit a JSON result envelope.")
    run.add_argument("--thread-id", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--system-prompt", default="")
    run.add_argument("--tools", default="")
    run.add_argument("--task", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the process-subagent CLI protocol without invoking a model."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "task" and args.task_command == "run":
            _print_envelope(
                {
                    "success": True,
                    "result": _controlled_task_result(args),
                    "error": None,
                    "token_usage": {},
                }
            )
            return 0
        parser.error("unsupported command")
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _print_envelope(
            {
                "success": False,
                "result": "",
                "error": str(exc),
                "token_usage": {},
            }
        )
        return 1
    return 2


def _controlled_task_result(args: argparse.Namespace) -> str:
    """Return the deterministic task result used by the isolated protocol."""
    task = str(args.task).strip()
    if not task:
        raise ValueError("task must not be empty")
    return task


def _print_envelope(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
