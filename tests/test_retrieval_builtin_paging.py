import json

import pytest
from langchain.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from focus_agent.capabilities.default_tools import get_default_tools
from focus_agent.config import ReadFileToolConfig, Settings, ToolCatalogConfig
from focus_agent.engine.local_persistence import PersistentInMemorySaver


def _tool_map(settings: Settings, *, checkpointer=None):
    return {tool.name: tool for tool in get_default_tools(settings, checkpointer=checkpointer)}


def test_read_file_default_end_is_relative_and_char_continuation_is_exact(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    sample = project / "notes.txt"
    sample.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            tool_catalog=ToolCatalogConfig(
                read_file=ReadFileToolConfig(default_end_line=2, max_lines=10, max_chars=1000)
            ),
        )
    )

    payload = json.loads(tools["read_file"].invoke({"path": "notes.txt", "start_line": 3}))

    assert payload["start_line"] == 3
    assert payload["end_line"] == 4
    assert payload["truncated"] is False
    assert payload["continuation"] is None
    assert "3 | three" in payload["content"]
    assert "4 | four" in payload["content"]

    long_line = project / "long.txt"
    long_line.write_text("abcdefghijklmnopqrstuvwxyz", encoding="utf-8")
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            tool_catalog=ToolCatalogConfig(
                read_file=ReadFileToolConfig(default_end_line=1, max_lines=1, max_chars=12)
            ),
        )
    )
    first = json.loads(tools["read_file"].invoke({"path": "long.txt"}))

    assert len(first["content"]) == 12
    assert first["truncated"] is True
    assert first["end_line"] == 1
    assert first["next_start_line"] == 1
    assert first["next_char_offset"] == 7
    assert first["continuation"] == {
        "path": "long.txt",
        "start_line": 1,
        "end_line": 1,
        "char_offset": 7,
    }

    second = json.loads(tools["read_file"].invoke(first["continuation"]))
    assert second["content"].startswith(" 1 | hijkl")
    assert second["next_char_offset"] > first["next_char_offset"]

    offset_file = project / "offset.txt"
    offset_file.write_text("short\nsecond line\n", encoding="utf-8")
    offset_tools = _tool_map(
        Settings(
            workspace_root=str(project),
            tool_catalog=ToolCatalogConfig(
                read_file=ReadFileToolConfig(default_end_line=2, max_lines=2, max_chars=1000)
            ),
        )
    )
    offset_payload = json.loads(
        offset_tools["read_file"].invoke({"path": "offset.txt", "char_offset": 100})
    )
    assert "2 | second line" in offset_payload["content"]

    tiny_tools = _tool_map(
        Settings(
            workspace_root=str(project),
            tool_catalog=ToolCatalogConfig(
                read_file=ReadFileToolConfig(default_end_line=1, max_lines=1, max_chars=1)
            ),
        )
    )
    tiny = json.loads(tiny_tools["read_file"].invoke({"path": "long.txt"}))
    assert len(tiny["content"]) == 1
    assert tiny["next_char_offset"] == 1


def test_conversation_summary_paginates_source_messages_and_preserves_ids(tmp_path):
    checkpointer = PersistentInMemorySaver(tmp_path / "checkpoints.pkl")
    messages = [
        HumanMessage(content="historical request", id="human-old"),
        AIMessage(content="historical answer", id="assistant-old"),
        HumanMessage(content="current request", id="human-current"),
        AIMessage(content="current answer", id="assistant-current"),
    ]
    builder = StateGraph(dict)
    builder.add_node(
        "write_state",
        lambda _state: {
            "rolling_summary": "Rolling summary only.",
            "messages": messages,
        },
    )
    builder.add_edge(START, "write_state")
    builder.add_edge("write_state", END)
    builder.compile(checkpointer=checkpointer).invoke(
        {"messages": []}, config={"configurable": {"thread_id": "thread-1"}}
    )
    tools = _tool_map(Settings(), checkpointer=checkpointer)

    empty = json.loads(
        tools["conversation_summary"].invoke({"thread_id": "thread-1", "recent_messages": 0})
    )
    assert empty["message_count"] == 4
    assert empty["recent_messages"] == []

    latest = json.loads(
        tools["conversation_summary"].invoke({"thread_id": "thread-1", "recent_messages": 2})
    )
    assert latest["source_kind"] == "checkpoint_messages"
    assert [item["id"] for item in latest["recent_messages"]] == [
        "human-current",
        "assistant-current",
    ]
    assert latest["rolling_summary"] == "Rolling summary only."
    assert latest["rolling_summary_source"] == "checkpoint.rolling_summary"
    assert "source_messages" not in latest
    assert "original_messages" not in latest
    assert "source_message_count" not in latest

    historical = json.loads(
        tools["conversation_summary"].invoke(
            {
                "thread_id": "thread-1",
                "recent_messages": 1,
                "query": "historical",
            }
        )
    )
    assert [item["id"] for item in historical["recent_messages"]] == ["human-old"]
    assert historical["next_offset"] == 1

    continuation = json.loads(
        tools["conversation_summary"].invoke(
            {
                "thread_id": "thread-1",
                "recent_messages": 1,
                "query": "historical",
                "offset": historical["next_offset"],
            }
        )
    )
    assert [item["id"] for item in continuation["recent_messages"]] == ["assistant-old"]
    assert continuation["next_offset"] is None


def test_conversation_summary_continuation_covers_every_older_page(tmp_path):
    checkpointer = PersistentInMemorySaver(tmp_path / "checkpoints.pkl")
    messages = [
        HumanMessage(content=f"message-{index}", id=f"message-{index}") for index in range(10)
    ]
    builder = StateGraph(dict)
    builder.add_node("write_state", lambda _state: {"messages": messages})
    builder.add_edge(START, "write_state")
    builder.add_edge("write_state", END)
    builder.compile(checkpointer=checkpointer).invoke(
        {"messages": []}, config={"configurable": {"thread_id": "thread-older"}}
    )
    tools = _tool_map(Settings(), checkpointer=checkpointer)

    args = {"thread_id": "thread-older", "recent_messages": 2}
    seen: list[str] = []
    while True:
        payload = json.loads(tools["conversation_summary"].invoke(args))
        seen.extend(item["id"] for item in payload["recent_messages"])
        continuation = payload["continuation"]
        if continuation is None:
            break
        args = continuation

    assert sorted(seen, key=lambda item: int(item.rsplit("-", 1)[-1])) == [
        f"message-{index}" for index in range(10)
    ]


def test_conversation_summary_query_snippet_anchor_and_invalid_anchor(tmp_path):
    checkpointer = PersistentInMemorySaver(tmp_path / "checkpoints.pkl")
    long_content = "x" * 1500 + "needle" + " tail"
    messages = [
        HumanMessage(content="current", id="current"),
        AIMessage(content=long_content, id="historical-long"),
        HumanMessage(content="following anchor", id="after-anchor"),
    ]
    builder = StateGraph(dict)
    builder.add_node("write_state", lambda _state: {"messages": messages})
    builder.add_edge(START, "write_state")
    builder.add_edge("write_state", END)
    builder.compile(checkpointer=checkpointer).invoke(
        {"messages": []}, config={"configurable": {"thread_id": "thread-query"}}
    )
    tools = _tool_map(Settings(), checkpointer=checkpointer)

    queried = json.loads(
        tools["conversation_summary"].invoke(
            {"thread_id": "thread-query", "recent_messages": 1, "query": "needle"}
        )
    )
    hit = queried["recent_messages"][0]
    assert hit["id"] == "historical-long"
    assert "needle" in hit["content"]
    assert hit["content_offset"] > 0

    anchored = json.loads(
        tools["conversation_summary"].invoke(
            {
                "thread_id": "thread-query",
                "recent_messages": 1,
                "anchor": "historical-long",
                "char_offset": 1500,
            }
        )
    )
    assert anchored["recent_messages"][0]["id"] == "historical-long"
    assert anchored["recent_messages"][0]["content_offset"] == 1500
    assert anchored["recent_messages"][0]["content"].startswith("needle")
    assert anchored["continuation"]["anchor"] == "after-anchor"
    next_anchored = json.loads(tools["conversation_summary"].invoke(anchored["continuation"]))
    assert [item["id"] for item in next_anchored["recent_messages"]] == ["after-anchor"]
    assert hit["content_truncated"] is True

    with pytest.raises(ValueError, match="anchor .* was not found"):
        tools["conversation_summary"].invoke(
            {"thread_id": "thread-query", "anchor": "missing-message"}
        )


def test_read_file_end_line_matches_exact_character_boundary(tmp_path):
    (tmp_path / "lines.txt").write_text("one\ntwo\nthree", encoding="utf-8")
    for limit in (8, 9):  # End of first numbered line, or its trailing newline.
        tools = _tool_map(
            Settings(
                workspace_root=str(tmp_path),
                artifact_dir=str(tmp_path / "artifacts"),
                tool_catalog=ToolCatalogConfig(read_file=ReadFileToolConfig(max_chars=limit)),
            )
        )
        page = json.loads(tools["read_file"].invoke({"path": "lines.txt", "end_line": 3}))
        assert page["end_line"] == 1
        assert page["continuation"]["start_line"] == 2
