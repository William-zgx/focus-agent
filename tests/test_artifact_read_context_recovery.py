from __future__ import annotations

import json

from langchain.tools import tool

from focus_agent.capabilities.tool_execution_types import ToolExecutionInput
from focus_agent.capabilities.tool_registry import ToolRuntimeMeta
from focus_agent.capabilities.tool_runtime import execute_tool_calls
from focus_agent.core.context_policy import apply_prompt_budget_guard
from focus_agent.core.types import ContextBudget


def test_artifact_read_trim_keeps_existing_ref_content_and_cursor():
    artifact_ref = "tool-observation://web_fetch/call-1"
    raw_content = "evidence " * 1200

    @tool
    def artifact_read() -> str:
        """Return an existing observation artifact page."""
        return json.dumps(
            {
                "artifact_id": artifact_ref,
                "offset": 0,
                "content": raw_content,
                "total_chars": len(raw_content),
                "next_offset": None,
                "truncated": False,
            }
        )

    artifact_read.metadata = {"max_observation_chars": 8000}
    saved_calls: list[dict[str, object]] = []
    result = execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="read-1",
                tool_name=artifact_read.name,
                args={},
                tool=artifact_read,
                runtime=ToolRuntimeMeta.from_tool(artifact_read),
            )
        ],
        context_budget=ContextBudget(
            tool_observation_token_limit=900,
            chars_per_token=4,
            tool_reference_token_limit=16,
        ),
        observation_saver=lambda **kwargs: saved_calls.append(kwargs),
    )[0]

    payload = json.loads(str(result.message.content))
    assert payload["artifact_id"] == artifact_ref
    assert payload["content"]
    assert raw_content.startswith(payload["content"])
    assert payload["offset"] == 0
    assert payload["total_chars"] == len(raw_content)
    assert payload["next_offset"] == len(payload["content"])
    assert payload["truncated"] is True
    assert len(str(result.message.content)) <= 8000
    assert len(str(result.message.content)) <= 900 * 4
    assert saved_calls == []
    runtime = result.message.artifact["runtime"]
    assert runtime["observation_existing_artifact"] is True

    guarded = apply_prompt_budget_guard(
        [result.message],
        budget=ContextBudget(
            prompt_token_limit=4000,
            tool_observation_token_limit=900,
            chars_per_token=4,
            tool_reference_token_limit=16,
        ),
    )
    prompt_payload = json.loads(str(guarded[0].content))
    assert prompt_payload["artifact_id"] == artifact_ref
    assert not str(prompt_payload.get("artifact_ref") or "").endswith("/read-1")
    assert prompt_payload["content"] == payload["content"]
    assert prompt_payload["next_offset"] == len(prompt_payload["content"])


def test_web_body_uses_observation_budget_instead_of_tiny_reference_budget():
    from focus_agent.capabilities.tool_execution import trim_success

    body = "Source paragraph about accessible images. " * 400
    _trimmed, _runtime, prompt = trim_success(
        json.dumps({"url": "https://example.com/images", "content": body}),
        tool_name="web_fetch",
        tool_call_id="fetch-images",
        context_budget=ContextBudget(
            tool_observation_token_limit=3000, tool_reference_token_limit=16
        ),
        max_chars=8000,
        observation_saver=lambda **kwargs: "saved-source",
        observation_thread_id="test",
    )
    assert prompt is not None
    payload = json.loads(prompt)
    assert len(payload["content"]) > 1000
    assert payload["artifact_ref"] == "tool-observation://web_fetch/fetch-images"
    assert len(prompt) <= 12000


def test_artifact_read_rejects_unknown_paging_arguments_before_reading(tmp_path):
    from focus_agent.capabilities.default_tools import get_default_tools
    from focus_agent.config import Settings

    read = next(
        tool
        for tool in get_default_tools(
            Settings(
                workspace_root=str(tmp_path),
                artifact_dir=str(tmp_path / "artifacts"),
            )
        )
        if tool.name == "artifact_read"
    )
    result = execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="invalid-page",
                tool_name=read.name,
                args={"artifact_id": "missing.txt", "offsets": [100]},
                tool=read,
                runtime=ToolRuntimeMeta.from_tool(read),
            ),
        ],
        context_budget=ContextBudget(),
    )[0]
    assert result.message.status == "error"
    assert "Unknown arguments: offsets" in result.message.content
    assert "one integer offset" in result.message.content
    assert "FileNotFoundError" not in result.message.content
