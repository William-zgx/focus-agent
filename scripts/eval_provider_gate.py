#!/usr/bin/env python3
"""Run provider-backed eval commands with explicit missing-key policy."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence

DEFAULT_KEY_ENVS = ("OPENAI_API_KEY",)
DEFAULT_GATE_REPORT_JSON = Path("reports/eval-provider-gate.json")


def _annotation_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _emit_annotation(kind: str, *, title: str, message: str) -> None:
    print(f"::{kind} title={_annotation_escape(title)}::{_annotation_escape(message)}")


def _missing_key_names(key_envs: Sequence[str], env: Mapping[str, str]) -> list[str]:
    return [name for name in key_envs if not env.get(name)]


def _write_gate_report(
    path: str | Path,
    *,
    status: str,
    policy: str,
    key_envs: Sequence[str],
    missing_key_envs: Sequence[str],
    command: Sequence[str],
    exit_code: int | None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "policy": policy,
        "key_envs": list(key_envs),
        "missing_key_envs": list(missing_key_envs),
        "command": list(command),
        "exit_code": exit_code,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def run_provider_eval_gate(
    *,
    command: Sequence[str],
    key_envs: Sequence[str] = DEFAULT_KEY_ENVS,
    missing_policy: str = "skip",
    gate_report_json: str | Path = DEFAULT_GATE_REPORT_JSON,
    annotation_title: str = "Provider-backed eval skipped",
    env: Mapping[str, str] | None = None,
) -> int:
    env = env or os.environ
    key_envs = tuple(key_envs or DEFAULT_KEY_ENVS)
    policy = missing_policy.strip().lower()
    if policy not in {"skip", "fail"}:
        raise ValueError("missing policy must be one of: skip, fail")

    missing = _missing_key_names(key_envs, env)
    if missing:
        message = (
            f"Missing provider credential(s): {', '.join(missing)}. "
            f"Policy={policy}; provider-backed eval was not executed."
        )
        if policy == "skip":
            _emit_annotation("notice", title=annotation_title, message=message)
            _write_gate_report(
                gate_report_json,
                status="skipped",
                policy=policy,
                key_envs=key_envs,
                missing_key_envs=missing,
                command=command,
                exit_code=None,
            )
            return 0
        _emit_annotation("error", title="Provider-backed eval blocked", message=message)
        _write_gate_report(
            gate_report_json,
            status="failed",
            policy=policy,
            key_envs=key_envs,
            missing_key_envs=missing,
            command=command,
            exit_code=1,
        )
        return 1

    if not command:
        raise ValueError("provider eval command is required when credentials are present")

    completed = subprocess.run(tuple(command), check=False)
    status = "passed" if completed.returncode == 0 else "failed"
    _write_gate_report(
        gate_report_json,
        status=status,
        policy=policy,
        key_envs=key_envs,
        missing_key_envs=[],
        command=command,
        exit_code=int(completed.returncode),
    )
    return int(completed.returncode)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-env", action="append", default=[], help="Required provider key env var. May repeat.")
    parser.add_argument(
        "--missing-policy",
        choices=("skip", "fail"),
        default=os.environ.get("PROVIDER_EVAL_MISSING_KEY_POLICY", "skip"),
        help="Behavior when a required provider key is missing.",
    )
    parser.add_argument(
        "--missing-policy-env",
        help="Read missing-key policy from this env var, falling back to --missing-policy.",
    )
    parser.add_argument("--gate-report-json", default=str(DEFAULT_GATE_REPORT_JSON))
    parser.add_argument("--annotation-title", default="Provider-backed eval skipped")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after --")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    policy = args.missing_policy
    if args.missing_policy_env and os.environ.get(args.missing_policy_env):
        policy = os.environ[args.missing_policy_env]
    try:
        return run_provider_eval_gate(
            command=command,
            key_envs=args.key_env or DEFAULT_KEY_ENVS,
            missing_policy=policy,
            gate_report_json=args.gate_report_json,
            annotation_title=args.annotation_title,
        )
    except ValueError as exc:
        print(f"[provider-eval-gate] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
