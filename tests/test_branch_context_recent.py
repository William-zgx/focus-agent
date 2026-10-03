import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages import messages_from_dict, messages_to_dict

from focus_agent.engine.graph_tool_history_repair import _messages_for_model


@pytest.mark.parametrize("restored", [False, True])
def test_branch_recent_does_not_reintroduce_equal_parent_message(restored):
    parent = HumanMessage(content="Investigate locking")
    local = [
        HumanMessage(content="Investigate locking"),
        AIMessage(content="Local evidence"),
    ]
    assert parent == local[0] and parent is not local[0]
    messages = [parent, AIMessage(content="Parent hypothesis"), *local]
    recent = [parent, *local]
    if restored:
        recent = messages_from_dict(messages_to_dict(recent))

    selected = _messages_for_model(
        {
            "messages": messages,
            "recent_messages": recent,
            "branch_meta": {"branch_fork_message_count": 2},
        }
    )

    assert [message.content for message in selected] == [message.content for message in local]
    assert all(message is not parent for message in selected)


@pytest.mark.parametrize("human_id", [None, "local-human"])
def test_restored_branch_recent_preserves_human_and_tool_pair(human_id):
    local = [
        HumanMessage(content="Investigate locking", id=human_id),
        AIMessage(content="Local evidence", id="local-answer"),
        HumanMessage(content="Check the evidence", id="local-followup"),
    ]
    exchange = [
        AIMessage(
            content="",
            tool_calls=[{"id": "local-call", "name": "lookup", "args": {}}],
        ),
        ToolMessage(content="Confirmed", tool_call_id="local-call"),
    ]
    messages = [HumanMessage(content=local[0].content), AIMessage(content="Parent"), *local]
    selected = _messages_for_model(
        {
            "messages": [*messages, *exchange],
            "recent_messages": messages_from_dict(messages_to_dict(messages)),
            "branch_meta": {"branch_fork_message_count": 2},
        }
    )

    assert [message.content for message in selected] == [
        message.content for message in [*local, *exchange]
    ]
    assert selected[-1].tool_call_id == selected[-2].tool_calls[0]["id"]


def test_restored_recent_ids_preserve_selected_window_and_compacted_content():
    local = [
        HumanMessage(content="Older local request", id="old-request"),
        AIMessage(content="Older local answer", id="old-answer"),
        HumanMessage(content="Current request", id="current-request"),
        AIMessage(content="Original long answer", id="current-answer"),
    ]
    recent = messages_from_dict(messages_to_dict(local[2:]))
    recent[-1] = recent[-1].model_copy(update={"content": "Compacted answer"})

    selected = _messages_for_model(
        {
            "messages": [HumanMessage(content="Parent"), AIMessage(content="Parent"), *local],
            "recent_messages": recent,
            "branch_meta": {"branch_fork_message_count": 2},
        }
    )

    assert [message.content for message in selected] == ["Current request", "Compacted answer"]
