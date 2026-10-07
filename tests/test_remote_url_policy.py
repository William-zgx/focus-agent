from __future__ import annotations

import pytest

from focus_agent.engine.graph.policy import build_tool_intent_plan


@pytest.mark.parametrize(
    "prompt",
    [
        "请读取 https://docs.python.org/3/whatsnew/3.13.html，总结自由线程模式的限制，并引用官方原文。",
        "Fetch https://example.com/docs and summarize the page with a source quote.",
        "Read https://example.com/docs and provide the source for the summary.",
        "Read https://example.com/api_v2/source_code and summarize the page.",
        "请读取 https://example.com/runtime/runbook，总结运行时限制并引用页面原文。",
        "Read https://example.com/runtime/runbook and summarize how to execute it.",
    ],
)
def test_remote_url_read_and_summary_stays_in_web_policy(prompt: str) -> None:
    plan = build_tool_intent_plan(prompt)

    assert plan.policy == "live_web_research"
    assert plan.preferred_first_tool == "web_fetch"
    assert plan.allowed_toolsets == ["web"]
    assert "search_code" not in plan.preferred_first_args


@pytest.mark.parametrize(
    "prompt",
    [
        "请下载 https://example.com/report.pdf 到本地并保存。",
        "请对 https://example.com/data.csv 的内容执行本地脚本。",
        "Download https://example.com/report.pdf and save it locally.",
    ],
)
def test_remote_url_local_write_or_execution_keeps_execution_policy(prompt: str) -> None:
    plan = build_tool_intent_plan(prompt)

    assert plan.policy == "execution"
    assert "remote_url_local_mutation" in plan.reason_codes


def test_remote_url_with_explicit_local_source_context_keeps_workspace_signal() -> None:
    plan = build_tool_intent_plan(
        "Read https://example.com/docs and inspect the source file in the current repository."
    )

    assert plan.policy == "execution"
    assert plan.allowed_toolsets == ["web", "workspace"]
    assert "mixed_live_web_workspace" in plan.reason_codes
