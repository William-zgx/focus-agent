from __future__ import annotations

from types import SimpleNamespace

from langchain.messages import AIMessage, HumanMessage

from focus_agent.core.branch_brief import FORK_BRIEF_KEYS, fork_brief_goal_update
from focus_agent.core.branching import BranchActionKind, BranchMeta
from focus_agent.core.context.policy import assemble_context
from focus_agent.core.types import PromptMode
from focus_agent.services.branches import BranchService

from .test_branch_conclusion_policy import FakeGraph, FakeRepo


def _service(states: dict) -> BranchService:
    service = object.__new__(BranchService)
    service.repo = FakeRepo()
    service.graph = FakeGraph(states)
    service.thread_client = None
    service.proposal_model = None
    service.settings = SimpleNamespace(branch_max_depth=5)
    service.store = None
    service.memory_writer = None
    for thread_id in states:
        service.repo.ensure_thread_owner(
            thread_id=thread_id, root_thread_id="root-1", owner_user_id="user-1"
        )
    return service


def _parent_state() -> dict:
    return {
        "messages": [
            HumanMessage(content="We are choosing a DB for billing; must be Postgres-compatible"),
            AIMessage(content="Shortlist: CockroachDB, YugabyteDB, Aurora."),
            HumanMessage(content="Constraint: budget < $2k/mo"),
            AIMessage(content="Noted, budget < $2k/mo applies to every option."),
        ],
        "rolling_summary": "Earlier: user rejected MySQL due to licensing.",
    }


def test_fork_stores_brief_with_exact_shape_and_parent_context():
    service = _service({"root-1": _parent_state()})

    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")

    brief = service.graph.states[record.child_thread_id]["branch_meta"]["fork_brief"]
    assert tuple(brief) == FORK_BRIEF_KEYS
    assert brief["goal"] == ""
    assert brief["parent_summary"] == "Earlier: user rejected MySQL due to licensing."
    assert brief["parent_message_count"] == 4
    assert brief["parent_recent_turns"][-2:] == [
        {"role": "user", "content": "Constraint: budget < $2k/mo"},
        {"role": "assistant", "content": "Noted, budget < $2k/mo applies to every option."},
    ]
    assert all(set(turn) == {"role", "content"} for turn in brief["parent_recent_turns"])
    assert "T" in brief["forked_at"]
    assert (
        BranchMeta.model_validate(
            service.graph.states[record.child_thread_id]["branch_meta"]
        ).fork_brief
        == brief
    )


def test_fork_brief_prefers_compaction_summary_and_caps_turns():
    parent = _parent_state()
    parent["context_compaction"] = {"compaction_version": 2, "history_summary": "Compacted."}
    parent["messages"] = [
        message
        for index in range(5)
        for message in (
            HumanMessage(content=f"question {index} " + "x" * 1200),
            AIMessage(content=f"answer {index}"),
        )
    ]
    service = _service({"root-1": parent})

    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")

    brief = service.graph.states[record.child_thread_id]["branch_meta"]["fork_brief"]
    assert brief["parent_summary"] == "Compacted."
    assert len(brief["parent_recent_turns"]) == 6
    assert brief["parent_recent_turns"][0]["content"].startswith("question 2")
    assert all(len(turn["content"]) <= 800 for turn in brief["parent_recent_turns"])


def test_child_prompt_keeps_parent_constraints_after_first_local_turn():
    service = _service({"root-1": _parent_state()})
    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")
    child = service.graph.states[record.child_thread_id]
    child["messages"] = [*child["messages"], HumanMessage(content="How does its cost compare?")]

    prompt = assemble_context(child, PromptMode.EXPLORE).render_prompt()

    assert "## Branch brief" in prompt
    assert "budget < $2k/mo" in prompt
    assert "rejected MySQL" in prompt
    assert "Branch goal: How does its cost compare?" in prompt
    assert "Active goal: How does its cost compare?" in prompt
    # UI transcript is unchanged: the brief lives only in prompt context.
    assert [m.content for m in child["messages"]][-1] == "How does its cost compare?"


def test_goal_update_pins_first_local_user_message_once():
    service = _service({"root-1": _parent_state()})
    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")
    child = service.graph.states[record.child_thread_id]
    child["messages"] = [*child["messages"], HumanMessage(content="Compare Yugabyte cost")]

    update = fork_brief_goal_update(child)

    assert update["branch_meta"]["fork_brief"]["goal"] == "Compare Yugabyte cost"
    assert update["active_goal"] == "Compare Yugabyte cost"
    child.update(update)
    child["messages"] = [*child["messages"], HumanMessage(content="Now check latency")]
    assert fork_brief_goal_update(child) == {}


def test_sibling_fork_brief_uses_shared_parent_and_handoff_goal():
    service = _service(
        {
            "root-1": {
                "messages": [
                    HumanMessage(content="Only answer with OK from now on."),
                    AIMessage(content="OK"),
                    HumanMessage(content="今天北京的天气怎么样？"),
                ],
                "branch_actions": [
                    {
                        "action_id": "action-1",
                        "kind": BranchActionKind.FORK_SIBLING_BRANCH.value,
                        "status": "pending",
                        "root_thread_id": "root-1",
                        "source_thread_id": "root-1",
                        "target_parent_thread_id": "root-1",
                        "branch_role": "execute",
                        "reason": "topic shift",
                        "created_at": "2026-05-21T00:00:00+00:00",
                        "handoff_message": "今天北京的天气怎么样？",
                    }
                ],
            }
        }
    )

    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")

    child = service.graph.states[record.child_thread_id]
    brief = child["branch_meta"]["fork_brief"]
    assert child["messages"] == []
    assert brief["goal"] == "今天北京的天气怎么样？"
    assert child["active_goal"] == "今天北京的天气怎么样？"
    assert [turn["content"] for turn in brief["parent_recent_turns"]] == [
        "Only answer with OK from now on.",
        "OK",
    ]
    prompt = assemble_context(child, PromptMode.EXPLORE).render_prompt()
    assert "background" in prompt
    assert "not new requests" in prompt


def test_main_thread_prompt_has_no_branch_brief():
    prompt = assemble_context(_parent_state(), PromptMode.EXPLORE).render_prompt()

    assert "## Branch brief" not in prompt
