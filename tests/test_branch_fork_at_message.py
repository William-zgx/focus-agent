from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.api.deps import get_current_principal
from focus_agent.api.main import create_app
from focus_agent.core.branch_messages import branch_context_messages
from focus_agent.core.branching import BranchActionKind
from focus_agent.core.context.policy import assemble_context
from focus_agent.core.types import PromptMode
from focus_agent.security.tokens import Principal

from .test_branch_fork_brief import _service


def _parent_state() -> dict:
    return {
        "messages": [
            HumanMessage(content="Pick a billing DB; must be Postgres-compatible", id="h1"),
            AIMessage(
                content="",
                id="a1-tool",
                tool_calls=[{"id": "call-1", "name": "web_search", "args": {"q": "pg"}}],
            ),
            ToolMessage(content="search results", tool_call_id="call-1", id="t1"),
            AIMessage(content="Shortlist: CockroachDB, YugabyteDB, Aurora.", id="a1"),
            HumanMessage(content="LATER: drop Aurora, it is too expensive", id="h2"),
            AIMessage(
                content="",
                id="a2-tool",
                tool_calls=[{"id": "call-2", "name": "web_search", "args": {"q": "cost"}}],
            ),
            ToolMessage(content="LATER pricing", tool_call_id="call-2", id="t2"),
            AIMessage(content="LATER: Aurora removed from the shortlist.", id="a2"),
        ],
        "rolling_summary": "LATER summary mentioning the Aurora removal.",
        "context_compaction": {"source_message_tail_id": "a2"},
        "task_outcome": {"status": "completed", "turn_id": "2"},
        "tool_outcomes": [
            {"tool_call_id": "call-1", "status": "succeeded"},
            {"tool_call_id": "call-2", "status": "failed"},
        ],
        "branch_actions": [
            {
                "action_id": "action-later",
                "kind": BranchActionKind.FORK_SIBLING_BRANCH.value,
                "status": "pending",
                "root_thread_id": "root-1",
                "source_thread_id": "root-1",
                "target_parent_thread_id": "root-1",
                "branch_role": "execute",
                "reason": "topic shift",
                "created_at": "2026-10-01T00:00:00+00:00",
                "handoff_message": "LATER handoff goal",
            }
        ],
    }


def _ids(messages: list) -> list[str]:
    return [message.id for message in messages]


def test_fork_at_message_hides_later_parent_turns_from_seed_brief_and_prompt():
    service = _service({"root-1": _parent_state()})

    record = service.fork_branch(
        parent_thread_id="root-1", user_id="user-1", fork_at_message_id="a1"
    )

    child = service.graph.states[record.child_thread_id]
    meta = child["branch_meta"]
    assert record.fork_strategy == "local_snapshot_seed"
    assert meta["fork_at_message_id"] == "a1"
    assert _ids(child["messages"]) == ["h1", "a1-tool", "t1", "a1"]
    assert meta["branch_fork_message_count"] == 4
    brief = meta["fork_brief"]
    assert brief["parent_message_count"] == 4
    assert brief["parent_recent_turns"] == [
        {"role": "user", "content": "Pick a billing DB; must be Postgres-compatible"},
        {"role": "assistant", "content": "Shortlist: CockroachDB, YugabyteDB, Aurora."},
    ]
    # The summary and the pending sibling proposal were written after the cut.
    assert brief["parent_summary"] == ""
    assert brief["goal"] == ""
    assert child["task_outcome"] is None
    assert child["tool_outcomes"] == [{"tool_call_id": "call-1", "status": "succeeded"}]

    child["messages"] = [*child["messages"], HumanMessage(content="Compare latency", id="c1")]
    context_messages = branch_context_messages(child["messages"], values=child)
    prompt = assemble_context(child, PromptMode.EXPLORE).render_prompt()
    assert "LATER" not in " ".join(str(message.content) for message in context_messages)
    assert "LATER" not in prompt
    assert "Shortlist: CockroachDB" in prompt


def test_fork_at_message_keeps_summary_written_before_the_cut():
    parent = _parent_state()
    parent["context_compaction"] = {"source_message_tail_id": "a1"}
    parent["rolling_summary"] = "Earlier: user rejected MySQL."
    service = _service({"root-1": parent})

    record = service.fork_branch(
        parent_thread_id="root-1", user_id="user-1", fork_at_message_id="h2"
    )

    child = service.graph.states[record.child_thread_id]
    assert _ids(child["messages"])[-1] == "h2"
    assert child["branch_meta"]["fork_brief"]["parent_summary"] == "Earlier: user rejected MySQL."


def test_fork_at_tool_call_message_keeps_its_tool_results():
    service = _service({"root-1": _parent_state()})

    record = service.fork_branch(
        parent_thread_id="root-1", user_id="user-1", fork_at_message_id="a1-tool"
    )

    assert _ids(service.graph.states[record.child_thread_id]["messages"]) == [
        "h1",
        "a1-tool",
        "t1",
    ]


def test_fork_at_message_skips_thread_copy():
    service = _service({"root-1": _parent_state()})
    copies: list[str] = []
    service.thread_client = SimpleNamespace(
        threads=SimpleNamespace(copy=lambda thread_id: copies.append(thread_id))
    )

    record = service.fork_branch(
        parent_thread_id="root-1", user_id="user-1", fork_at_message_id="a1"
    )

    assert copies == []
    assert record.fork_strategy == "local_snapshot_seed"


def test_fork_at_unknown_message_raises_value_error():
    service = _service({"root-1": _parent_state()})

    with pytest.raises(ValueError, match="missing"):
        service.fork_branch(
            parent_thread_id="root-1", user_id="user-1", fork_at_message_id="missing"
        )
    assert list(service.graph.states) == ["root-1"]


def test_fork_without_message_id_still_seeds_the_full_parent():
    service = _service({"root-1": _parent_state()})

    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")

    child = service.graph.states[record.child_thread_id]
    assert child["branch_meta"]["fork_at_message_id"] is None
    # The pending sibling handoff still applies, exactly as before this option.
    assert child["branch_meta"]["fork_brief"]["goal"] == "LATER handoff goal"
    assert child["branch_meta"]["fork_brief"]["parent_message_count"] == 8


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service) -> TestClient:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=SimpleNamespace(auth_enabled=False),
        branch_service=service,
    )
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id="user-1")
    return TestClient(app)


def test_fork_api_maps_unknown_message_to_400_and_forwards_known_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    service = _service({"root-1": _parent_state()})
    client = _client(monkeypatch, tmp_path, service)

    missing = client.post(
        "/v1/branches/fork",
        json={"parent_thread_id": "root-1", "fork_at_message_id": "missing"},
    )
    created = client.post(
        "/v1/branches/fork",
        json={"parent_thread_id": "root-1", "fork_at_message_id": "a1"},
    )

    assert missing.status_code == 400, missing.text
    assert created.status_code == 200, created.text
    child = service.graph.states[created.json()["child_thread_id"]]
    assert _ids(child["messages"]) == ["h1", "a1-tool", "t1", "a1"]
