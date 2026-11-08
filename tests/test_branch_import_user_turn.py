from __future__ import annotations

from langchain.messages import AIMessage, HumanMessage, SystemMessage

from focus_agent.engine.graph.agent_loop_prompt import (
    _build_prompt_messages,
    _import_notices_as_user_turns,
)


def _notice(
    branch_name: str = "Aurora",
    body: str = "Provider: QuorumSync. Price: 42 USD.",
    *,
    with_metadata: bool = True,
    header_name: str | None = None,
) -> SystemMessage:
    header_name = branch_name if header_name is None else header_name
    metadata = (
        {"focus_agent": {"metadata": {"branch_import": {"branch_name": branch_name}}}}
        if with_metadata
        else None
    )
    return SystemMessage(
        content=f"Imported conclusion from branch '{header_name}':\n{body}",
        **({"response_metadata": metadata} if metadata else {}),
    )


def _messages(messages: list[object]) -> list[object]:
    return _build_prompt_messages(
        "system prompt",
        messages,
        steer_block="",
        policy_note="",
    )


def test_english_import_notice_becomes_user_turn_and_acknowledgement():
    notice = _notice()

    rewritten = _import_notices_as_user_turns([notice])

    assert len(rewritten) == 2
    human, ack = rewritten
    assert isinstance(human, HumanMessage)
    assert isinstance(ack, AIMessage)
    assert human.content == (
        "Decisions I settled while looking into the side question 'Aurora' (these are final):\n\n"
        "Provider: QuorumSync. Price: 42 USD."
    )
    assert ack.content == "Noted."


def test_chinese_import_notice_uses_chinese_framing_and_acknowledgement():
    notice = _notice(
        branch_name="定价核对",
        body="结论：QuorumSync，2 秒预警。",
    )

    rewritten = _import_notices_as_user_turns([notice])

    human, ack = rewritten
    assert human.content == (
        "我在旁支问题「定价核对」里已经定下的决定（这些是最终结论）：\n\n"
        "结论：QuorumSync，2 秒预警。"
    )
    assert ack.content == "收到。"


def test_import_notice_detected_by_metadata_without_matching_header():
    notice = SystemMessage(
        content="Branch outcome summary: QuorumSync wins.",
        response_metadata={
            "focus_agent": {"metadata": {"branch_import": {"branch_name": "Aurora"}}}
        },
    )

    rewritten = _import_notices_as_user_turns([notice])

    human, ack = rewritten
    assert human.content == (
        "Decisions I settled while looking into the side question 'Aurora' (these are final):\n\n"
        "Branch outcome summary: QuorumSync wins."
    )
    assert ack.content == "Noted."


def test_import_notice_detected_by_header_when_metadata_is_absent():
    notice = _notice(branch_name="Aurora", with_metadata=False)

    rewritten = _import_notices_as_user_turns([notice])

    human, _ack = rewritten
    assert human.content.startswith(
        "Decisions I settled while looking into the side question 'Aurora' (these are final):"
    )


def test_metadata_branch_name_wins_over_header_line():
    notice = _notice(branch_name="Metadata Name", header_name="Header Name")

    rewritten = _import_notices_as_user_turns([notice])

    assert rewritten[0].content.startswith(
        "Decisions I settled while looking into the side question 'Metadata Name' (these are final):"
    )


def test_branch_name_falls_back_to_header_line():
    notice = _notice(branch_name="Aurora", with_metadata=False)

    rewritten = _import_notices_as_user_turns([notice])

    assert "'Aurora'" in rewritten[0].content


def test_non_import_system_messages_are_untouched():
    notice = _notice()
    policy = SystemMessage(content="Policy note: answer concisely.")
    unrelated = SystemMessage(content="Imported conclusion from another source.")

    rewritten = _import_notices_as_user_turns([policy, notice, unrelated])

    assert rewritten[0] is policy
    assert rewritten[3] is unrelated
    assert len(rewritten) == 4


def test_ordering_is_preserved_around_the_rewritten_notice():
    before = HumanMessage(content="How should we roll out?")
    notice = _notice()
    after = HumanMessage(content="Go ahead with the rollout.")

    rewritten = _import_notices_as_user_turns([before, notice, after])

    assert rewritten[0] is before
    assert isinstance(rewritten[1], HumanMessage)
    assert isinstance(rewritten[2], AIMessage)
    assert rewritten[3] is after


def test_prompt_build_applies_the_rewrite_and_keeps_leading_system_prompt():
    notice = _notice()
    user = HumanMessage(content="Go ahead with the rollout.")

    prompt = _messages([notice, user])

    assert isinstance(prompt[0], SystemMessage)
    assert prompt[0].content == "system prompt"
    assert isinstance(prompt[1], HumanMessage)
    assert isinstance(prompt[2], AIMessage)
    assert prompt[3] is user


def test_rewrite_does_not_mutate_the_source_messages():
    notice = _notice()
    user = HumanMessage(content="Go ahead with the rollout.")
    source = [notice, user]

    rewritten = _import_notices_as_user_turns(source)

    assert len(source) == 2
    assert isinstance(source[0], SystemMessage)
    assert source[0].content.startswith("Imported conclusion from branch 'Aurora':")
    assert source[1] is user
    assert isinstance(rewritten[0], HumanMessage)
    assert rewritten[1].content == "Noted."


def test_body_keeps_key_findings_and_evidence_after_header_removal():
    body = (
        "QuorumSync wins on price.\n\nKey findings:\n- 2 second warning window\n\n"
        "Evidence refs: pricing, docs"
    )
    notice = _notice(body=body)

    rewritten = _import_notices_as_user_turns([notice])

    assert rewritten[0].content == (
        "Decisions I settled while looking into the side question 'Aurora' (these are final):\n\n"
        f"{body}"
    )


class _RecordingRunnable:
    def __init__(self) -> None:
        self.calls: list[list[object]] = []

    def with_config(self, _config):
        return self

    def invoke(self, prompt_messages):
        self.calls.append(list(prompt_messages))
        return AIMessage(content="Rollout confirmed.")

    def bind_tools(self, _tools, **_kwargs):
        return self


def test_agent_loop_sends_import_notice_to_the_model_as_a_user_turn():
    from types import SimpleNamespace

    from focus_agent.config import Settings
    from focus_agent.engine.loop.agent import make_loop_agent_node

    model = _RecordingRunnable()
    node = make_loop_agent_node(
        settings=Settings(),
        tools=(),
        model_for=lambda *_args: model,
        model_with_tools_for=lambda *_args: model,
    )
    notice = _notice()
    state = {
        "messages": [
            HumanMessage(content="Which provider should we use?"),
            AIMessage(content="Let me look into it."),
            notice,
            HumanMessage(content="Go ahead with the rollout."),
        ],
        "assembled_context": "",
        "llm_calls": 0,
    }

    node(state, SimpleNamespace(context=SimpleNamespace(root_thread_id="import-test")))

    assert model.calls, "the main answering call must reach the model"
    sent = model.calls[0]
    import_turns = [
        message
        for message in sent
        if "side question 'Aurora'" in str(getattr(message, "content", ""))
    ]
    assert len(import_turns) == 1
    assert isinstance(import_turns[0], HumanMessage)
    assert isinstance(sent[sent.index(import_turns[0]) + 1], AIMessage)
    assert sent[sent.index(import_turns[0]) + 1].content == "Noted."
    assert not any(
        isinstance(message, SystemMessage) and "Imported conclusion" in str(message.content)
        for message in sent
    )
    # The stored transcript still holds the original system notice.
    assert state["messages"][2] is notice
    assert isinstance(state["messages"][2], SystemMessage)
