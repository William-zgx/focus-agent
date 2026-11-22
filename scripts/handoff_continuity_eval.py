#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
from typing import Any

from _report_io import write_json_report

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.eval.handoff import (
    HANDOFF_ARMS,
    run_handoff_arm,
    summarize_handoff_results,
    synthetic_handoff_cases,
)
from focus_agent.eval.runner.harness import EvalRuntime
from focus_agent.providers.anthropic_channel import create_anthropic_chat_model


def main() -> int:
    parser = argparse.ArgumentParser(description="Run synthetic four-arm handoff continuity evals.")
    parser.add_argument("--model", required=True, help="Anthropic-compatible model name")
    parser.add_argument("--model-label", help="Report label; defaults to --model")
    parser.add_argument("--cases", help="Comma-separated synthetic case IDs")
    parser.add_argument("--arms", help="Comma-separated arms; default all four")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--report-json", required=True)
    args = parser.parse_args()

    selected_cases = set(_csv(args.cases))
    selected_arms = set(_csv(args.arms))
    unknown_arms = selected_arms - set(HANDOFF_ARMS)
    if unknown_arms:
        parser.error(f"unknown arms: {sorted(unknown_arms)}")
    all_cases = synthetic_handoff_cases()
    unknown_cases = selected_cases - {case.id for case in all_cases}
    if unknown_cases:
        parser.error(f"unknown cases: {sorted(unknown_cases)}")
    cases = [case for case in all_cases if not selected_cases or case.id in selected_cases]
    if not cases:
        parser.error("no synthetic cases selected")
    arms = [arm for arm in HANDOFF_ARMS if not selected_arms or arm in selected_arms]
    model_label = args.model_label or args.model
    settings = Settings(
        model=f"anthropic:{args.model}",
        model_request_timeout_seconds=args.timeout,
        agent_context_engineering_v2_enabled=False,
    )
    runtime = EvalRuntime(
        settings=settings,
        tool_registry=ToolRegistry(tools=()),
        model_factory=_anthropic_factory(args),
        runtime_kind="provider",
    )
    results = []
    for repeat in range(1, max(1, args.repeat) + 1):
        for case in cases:
            for arm in arms:
                result = run_handoff_arm(case, arm, runtime=runtime, timeout_s=args.timeout)
                _redact_provider_details(result)
                result.metrics["handoff_repeat"] = repeat
                result.metrics["model_label"] = model_label
                results.append(result)
                print(
                    f"[handoff] model={model_label} repeat={repeat} case={case.id} "
                    f"arm={arm} passed={result.passed} error={bool(result.error)}",
                    flush=True,
                )
    summary = summarize_handoff_results(results)
    summary.update(
        {
            "model": model_label,
            "repeat": max(1, args.repeat),
            "provider_error_count": sum(bool(result.error) for result in results),
        }
    )
    report = {
        "summary": summary,
        "results": [result.to_dict() for result in results],
        "privacy": "Synthetic fixtures only; no user records, endpoint, or credentials are exported.",
    }
    write_json_report(args.report_json, report)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["provider_error_count"]:
        return 2
    return 0 if summary["passed"] else 1


def _anthropic_factory(args: argparse.Namespace) -> Any:
    def factory(*_args: Any, **_kwargs: Any) -> Any:
        kwargs: dict[str, Any] = {
            "model": args.model,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "timeout": args.timeout,
            "max_retries": 1,
        }
        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        scope = os.environ.get("FOCUS_AGENT_EVAL_MODEL_SCOPE", "cli")
        if scope:
            kwargs["default_headers"] = {"x-claude-model-scope": scope}
        return create_anthropic_chat_model(**kwargs)

    return factory


def _redact_provider_details(result: Any) -> None:
    secrets = [
        os.environ.get("ANTHROPIC_API_KEY"),
        os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        os.environ.get("ANTHROPIC_BASE_URL"),
    ]

    def clean(value: str | None) -> str | None:
        if value is None:
            return None
        for secret in filter(None, secrets):
            value = value.replace(secret, "[redacted]")
        return value[:4000]

    result.error = clean(result.error)
    for verdict in result.verdicts:
        verdict.reasoning = clean(verdict.reasoning) or ""


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
