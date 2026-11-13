from .support import (
    AIMessage,
    ChatServicePorts,
    FakeGraph,
    HumanMessage,
    RequestContext,
    Settings,
    SimpleNamespace,
    ToolMessage,
)


def test_response_payload_repairs_trailing_tool_calls_without_interrupt(
    chat_service_factory,
):
    class _Graph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="查中国能建"),
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": "call-1",
                                    "name": "run_workspace_command",
                                    "args": {
                                        "command": [
                                            "python3",
                                            "scripts/stocks_client.py",
                                            "quote",
                                            "601868.SS",
                                        ]
                                    },
                                }
                            ],
                        ),
                    ]
                }
            )

    chat = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=_Graph(), repo=SimpleNamespace())
    )

    payload = chat._response_payload(
        thread_id="thread-1",
        user_id="owner-1",
        context=RequestContext(user_id="owner-1", root_thread_id="thread-1"),
        branch_meta=None,
        interrupts=[],
    )

    assert payload["assistant_message"] is None
    assert [message["type"] for message in payload["messages"]] == ["human", "ai", "tool"]
    assert payload["messages"][2]["tool_call_id"] == "call-1"
    assert payload["messages"][2]["status"] == "error"


def test_response_payload_keeps_completed_answer_with_internal_observation_warning(
    chat_service_factory,
):
    class _Graph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="请总结页面。"),
                        AIMessage(
                            content=(
                                "部分工具未能完成，以下根据已获取的来源整理：\n"
                                "页面说明了关键限制。\n"
                                "需要保留的不确定性：artifact_read: "
                                "tool-observation://artifact_read/call-1"
                            )
                        ),
                    ]
                }
            )

    chat = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=_Graph(), repo=SimpleNamespace())
    )

    payload = chat._response_payload(
        thread_id="thread-1",
        user_id="owner-1",
        context=RequestContext(user_id="owner-1", root_thread_id="thread-1"),
        branch_meta=None,
        interrupts=[],
    )

    assert "页面说明了关键限制" in payload["assistant_message"]
    assert "tool-observation://" not in payload["assistant_message"]
    assert payload["messages"][-1]["content"] == payload["assistant_message"]


def test_response_payload_preserves_trailing_tool_calls_with_interrupt(
    chat_service_factory,
):
    class _Graph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="查中国能建"),
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "id": "call-1",
                                    "name": "run_workspace_command",
                                    "args": {"command": ["python3", "scripts/stocks_client.py"]},
                                }
                            ],
                        ),
                    ]
                }
            )

    chat = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=_Graph(), repo=SimpleNamespace())
    )
    interrupt = {
        "kind": "tool_approval",
        "tool_call_id": "call-1",
        "tool_name": "run_workspace_command",
    }

    payload = chat._response_payload(
        thread_id="thread-1",
        user_id="owner-1",
        context=RequestContext(user_id="owner-1", root_thread_id="thread-1"),
        branch_meta=None,
        interrupts=[interrupt],
    )

    assert [message["type"] for message in payload["messages"]] == ["human", "ai"]
    assert payload["messages"][1]["tool_calls"][0]["id"] == "call-1"
    assert payload["interrupts"] == [interrupt]


def test_serialize_message_keeps_usage_metadata(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._serialize_message(
        AIMessage(
            content="done",
            usage_metadata={"input_tokens": 21, "output_tokens": 9, "total_tokens": 30},
        )
    )

    assert payload["content"] == "done"
    assert payload["usage_metadata"]["total_tokens"] == 30
    assert payload["usage_metadata"]["input_tokens"] == 21


def test_serialize_message_normalizes_response_metadata_token_usage(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._serialize_message(
        AIMessage(
            content="done",
            response_metadata={"token_usage": {"prompt_tokens": 13, "completion_tokens": 5}},
        )
    )

    assert payload["usage_metadata"] == {
        "input_tokens": 13,
        "output_tokens": 5,
        "total_tokens": 18,
    }


def test_serialize_message_exposes_focus_agent_metadata(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._serialize_message(
        HumanMessage(
            content="plan: map the rollout",
            response_metadata={
                "focus_agent": {
                    "active_skill_ids": ["plan"],
                    "active_skills": [{"skill_id": "plan", "name": "plan"}],
                }
            },
        )
    )

    assert payload["metadata"]["active_skill_ids"] == ["plan"]
    assert payload["metadata"]["active_skills"][0]["skill_id"] == "plan"


def test_serialize_ai_message_exposes_focus_agent_turn_metadata_from_response_metadata(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )
    skill_execution_plan = {
        "active_skill_ids": ["plan"],
        "required_tools": ["read_file"],
    }
    execution_contract = {
        "required_tools": ["read_file"],
        "deliverable": "skill plan",
    }
    answer_verification = {
        "checks": ["required tools rendered"],
    }

    payload = service._serialize_message(
        AIMessage(
            content="done",
            response_metadata={
                "focus_agent": {
                    "skill_execution_plan": skill_execution_plan,
                    "execution_contract": execution_contract,
                    "answer_verification": answer_verification,
                }
            },
        )
    )

    assert "turn_metadata" in payload
    assert payload["turn_metadata"]["skill_execution_plan"] == skill_execution_plan
    assert payload["turn_metadata"]["execution_contract"] == execution_contract
    assert payload["turn_metadata"]["answer_verification"] == answer_verification


def test_serialize_dict_ai_message_exposes_focus_agent_turn_metadata_from_response_metadata(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )
    skill_execution_plan = {
        "active_skill_ids": ["plan"],
        "required_tools": ["read_file"],
    }
    execution_contract = {
        "required_tools": ["read_file"],
        "deliverable": "skill plan",
    }

    payload = service._serialize_message(
        {
            "type": "ai",
            "content": "done",
            "response_metadata": {
                "focus_agent": {
                    "skill_execution_plan": skill_execution_plan,
                    "execution_contract": execution_contract,
                }
            },
        }
    )

    assert "turn_metadata" in payload
    assert payload["turn_metadata"]["skill_execution_plan"] == skill_execution_plan
    assert payload["turn_metadata"]["execution_contract"] == execution_contract


def test_latest_final_ai_text_hides_english_process_narration(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    assert (
        service._latest_final_ai_text(
            [
                AIMessage(content="确认可见的最终答案。"),
                AIMessage(
                    content="Let me fetch the data first. I should look for: filings and price action."
                ),
            ]
        )
        == "确认可见的最终答案。"
    )
    assert (
        service._latest_final_ai_text(
            [
                AIMessage(
                    content=(
                        "Wait, if the current date is 2026-05-10, "
                        "I should check one more source before answering."
                    )
                )
            ]
        )
        is None
    )
    assert (
        service._latest_final_ai_text(
            [
                AIMessage(
                    content="Let me produce the final answer. Final answer: 这才是最终答案。"
                ),
            ]
        )
        == "这才是最终答案。"
    )


def test_latest_final_ai_text_ignores_draft_before_later_tool_activity(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    assert (
        service._latest_final_ai_text(
            [
                HumanMessage(content="查证配置。"),
                AIMessage(content="初步答复，但还不完整。"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "search_code",
                            "args": {"query": "skill_install"},
                        }
                    ],
                ),
                ToolMessage(content='{"results":[]}', tool_call_id="call-1"),
            ]
        )
        is None
    )


def test_thread_state_messages_hide_textual_tool_protocol_ai_messages(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            HumanMessage(content="Search this."),
            AIMessage(
                content='="read="filepath" string="true">tool-observation://webfetch/call00ljJOwoeUmsjmBzMNhkx8505'
            ),
            AIMessage(
                content=(
                    '<tool_req name="run_shell_command">\n'
                    '<arg name="command" string="true">cd /home/focus/.focus_agent/skills/stocks '
                    "&& python3 scripts/stocks_client.py quote 601020.SS</arg>\n"
                    '<arg name="timeout" string="false">30</arg>\n'
                    "</tool_req>"
                )
            ),
            AIMessage(content="最终安全回答。"),
        ]
    )

    assert [message["type"] for message in payload] == ["human", "ai"]
    assert [message["content"] for message in payload] == ["Search this.", "最终安全回答。"]


def test_thread_state_messages_hide_draft_answer_before_later_tool_activity(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            HumanMessage(content="查证配置。"),
            AIMessage(content="初步答复，但还不完整。"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "search_code",
                        "args": {"query": "skill_install"},
                    }
                ],
            ),
            ToolMessage(content='{"results":[]}', tool_call_id="call-1"),
        ]
    )

    assert [message["type"] for message in payload] == ["human", "ai", "tool"]
    assert payload[1]["content"] == ""
    assert payload[1]["tool_calls"][0]["name"] == "search_code"
    assert payload[2]["tool_call_id"] == "call-1"


def test_thread_state_messages_hide_english_process_narration(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            HumanMessage(content="Search this."),
            AIMessage(
                content="Let me fetch the data first. I should look for: filings and price action."
            ),
            AIMessage(
                content=(
                    "Wait, if the current date is 2026-05-10, "
                    "I should check one more source before answering."
                )
            ),
            SimpleNamespace(
                type="ai",
                content="I should call a tool before answering.",
                tool_calls=[{"id": "call-1", "name": "web_search", "args": {"q": "focus agent"}}],
                name=None,
                id="ai-tool-call",
                usage_metadata=None,
            ),
            AIMessage(content="Let me produce the final answer. Final answer: 这才是最终答案。"),
        ]
    )

    assert [message["type"] for message in payload] == ["human", "ai", "ai"]
    assert [message["content"] for message in payload] == ["Search this.", "", "这才是最终答案。"]
    assert payload[1]["tool_calls"][0]["name"] == "web_search"


def test_thread_state_messages_extract_visible_list_content_only(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            AIMessage(
                content=[
                    {"type": "reasoning", "text": "hidden reasoning"},
                    {"type": "input_text", "text": "hidden prompt"},
                    {"type": "tool_call", "text": '{"name":"web_search"}'},
                    {"type": "output_text", "text": "可见最终答案。"},
                ]
            )
        ]
    )

    assert len(payload) == 1
    assert payload[0]["content"] == "可见最终答案。"
    assert "hidden" not in payload[0]["content"]
    assert "web_search" not in payload[0]["content"]


def test_thread_state_messages_clear_protocol_content_but_keep_tool_calls(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            SimpleNamespace(
                type="ai",
                content='="read="filepath" string="true">tool-observation://webfetch/call-1',
                tool_calls=[
                    {"id": "call-1", "name": "web_fetch", "args": {"url": "https://example.com"}}
                ],
                name=None,
                id="ai-tools",
                usage_metadata=None,
            )
        ]
    )

    assert len(payload) == 1
    assert payload[0]["content"] == ""
    assert payload[0]["tool_calls"][0]["name"] == "web_fetch"


def test_thread_state_messages_preserve_dict_system_messages(
    chat_service_factory,
):
    service = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            {
                "type": "system",
                "content": "Imported conclusion from branch 'explore-alternatives':\nDone.",
                "id": "merge-notice-1",
            }
        ]
    )

    assert payload == [
        {
            "type": "system",
            "content": "Imported conclusion from branch 'explore-alternatives':\nDone.",
            "tool_calls": None,
            "name": None,
            "id": "merge-notice-1",
            "usage_metadata": None,
        }
    ]
