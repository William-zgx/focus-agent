from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.engine.graph_builder import _messages_for_model


def test_messages_for_model_keeps_current_tool_exchange():
    state = {
        "recent_messages": [
            HumanMessage(content="北京天气"),
        ],
        "messages": [
            HumanMessage(content="北京天气"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-1",
                        "name": "web_search",
                        "args": {"query": "beijing weather"},
                    }
                ],
            ),
            ToolMessage(content='{"forecast":"sunny"}', tool_call_id="tool-call-1"),
        ],
    }

    messages = _messages_for_model(state)

    assert len(messages) == 3
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage)
    assert isinstance(messages[2], ToolMessage)


def test_messages_for_model_uses_recent_messages_when_no_tool_exchange_is_active():
    state = {
        "recent_messages": [
            HumanMessage(content="今天北京天气怎么样"),
            AIMessage(content="今天北京晴。"),
        ],
        "messages": [
            HumanMessage(content="今天北京天气怎么样"),
            AIMessage(content="今天北京晴。"),
            HumanMessage(content="顺便说下上海"),
        ],
    }

    messages = _messages_for_model(state)

    assert [message.content for message in messages] == [
      "今天北京天气怎么样",
      "今天北京晴。",
    ]
