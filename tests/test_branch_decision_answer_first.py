"""Answer-first delivery of AI branch recommendations through ChatService."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from langchain.messages import AIMessage, HumanMessage

from focus_agent.config import Settings
from focus_agent.services.chat import ChatService
from tests.test_chat_service import (
    BranchActionBranchService,
    BranchRecommendationGraph,
    MultiThreadBranchActionGraph,
    _branch_recommendation_service,
    _repo_with_child_branch,
)

_SETTINGS = Settings(
    agent_branch_recommendation_enabled=True,
    agent_branch_recommendation_mode="suggest",
)


def _root_chat(tmp_path: Path, graph: object, **ports: object) -> ChatService:
    repo = _repo_with_child_branch(tmp_path)
    decision_service = _branch_recommendation_service(_SETTINGS, graph)
    # Production wires the branch service (and its repo) into the decision service.
    decision_service.branch_service = SimpleNamespace(repo=repo)
    return ChatService(
        SimpleNamespace(
            settings=_SETTINGS,
            graph=graph,
            repo=repo,
            branch_decision_service=decision_service,
            **ports,
        )
    )


def _history_graph() -> BranchRecommendationGraph:
    return BranchRecommendationGraph(
        {
            "messages": [
                HumanMessage(content="帮我把订单服务的重试逻辑改成指数退避"),
                AIMessage(content="好的，这里是修改方案……"),
            ]
        }
    )


def test_side_question_is_answered_and_card_is_attached(tmp_path: Path) -> None:
    graph = _history_graph()
    chat = _root_chat(tmp_path, graph)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="顺便问一下，Python 的 GIL 在 3.13 还存在吗？",
    )

    assert graph.invoke_calls == 1
    assert payload["assistant_message"] == "normal answer"
    human_texts = [m.content for m in graph.values["messages"] if isinstance(m, HumanMessage)]
    assert human_texts.count("顺便问一下，Python 的 GIL 在 3.13 还存在吗？") == 1
    action = payload["branch_actions"][-1]
    assert action["status"] == "pending"
    assert action["delivery"] == "after_answer"
    assert action["kind"] == "fork_child_branch"
    assert action["confidence"] < 0.86


def test_explicit_branch_command_keeps_blocking_proposal(tmp_path: Path) -> None:
    graph = _history_graph()
    chat = _root_chat(tmp_path, graph)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="New branch for the Temporal migration study",
    )

    assert graph.invoke_calls == 0
    assert payload["branch_actions"][-1]["delivery"] == "proposal"
    assert "branch switch confirmation" in payload["assistant_message"]


def test_acknowledgement_does_not_execute_after_answer_card(tmp_path: Path) -> None:
    graph = _history_graph()
    branch_service = BranchActionBranchService()
    chat = _root_chat(tmp_path, graph, branch_service=branch_service)
    chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="另一个问题：我们的前端打包为什么这么慢？",
    )

    payload = chat.send_message(thread_id="root-1", user_id="owner-1", message="好的")

    assert branch_service.fork_calls == []
    assert graph.invoke_calls == 2
    statuses = [action["status"] for action in payload["branch_actions"]]
    assert statuses == ["dismissed"]
    assert graph.values["branch_action_audit"][-1]["reason"] == "superseded_by_next_turn"


def test_move_to_branch_wording_executes_after_answer_card(tmp_path: Path) -> None:
    graph = _history_graph()
    branch_service = BranchActionBranchService()
    chat = _root_chat(tmp_path, graph, branch_service=branch_service)
    chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="另一个问题：我们的前端打包为什么这么慢？",
    )

    chat.send_message(thread_id="root-1", user_id="owner-1", message="移到分支继续吧")

    assert len(branch_service.fork_calls) == 1
    assert graph.invoke_calls == 1


def test_executing_after_answer_child_card_does_not_rerun_the_question(tmp_path: Path) -> None:
    graph = MultiThreadBranchActionGraph(
        {
            "root-1": {
                "messages": [
                    HumanMessage(content="帮我把订单服务的重试逻辑改成指数退避"),
                    AIMessage(content="好的，这里是修改方案……"),
                ]
            },
        }
    )
    branch_service = BranchActionBranchService()
    chat = _root_chat(tmp_path, graph, branch_service=branch_service)
    chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="另一个问题：我们的前端打包为什么这么慢？",
    )
    action = graph.values_by_thread["root-1"]["branch_actions"][-1]

    result = chat.execute_branch_action(
        thread_id="root-1", action_id=action["action_id"], user_id="owner-1"
    )

    assert branch_service.fork_calls[-1]["parent_thread_id"] == "root-1"
    assert result["handoff_message"] is None
    assert "messages" not in graph.values_by_thread.get("child-new", {})


def test_executing_after_answer_sibling_card_carries_the_question(tmp_path: Path) -> None:
    graph = MultiThreadBranchActionGraph(
        {
            "root-1": {"messages": [HumanMessage(content="根线程里的基础上下文。")]},
            "child-1": {
                "messages": [HumanMessage(content="当前分支在研究方案 A。")],
                "branch_meta": {
                    "branch_id": "branch-1",
                    "root_thread_id": "root-1",
                    "parent_thread_id": "root-1",
                    "return_thread_id": "root-1",
                    "branch_name": "方案 A",
                    "branch_role": "deep_dive",
                    "branch_depth": 1,
                    "branch_status": "active",
                },
            },
        }
    )
    branch_service = BranchActionBranchService()
    chat = _root_chat(tmp_path, graph, branch_service=branch_service)
    chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="另一个问题：Cadence 和 Temporal 授权有区别吗？",
    )
    action = graph.values_by_thread["child-1"]["branch_actions"][-1]

    result = chat.execute_branch_action(
        thread_id="child-1", action_id=action["action_id"], user_id="owner-1"
    )

    assert action["kind"] == "fork_sibling_branch"
    assert result["handoff_message"] == "Cadence 和 Temporal 授权有区别吗？"
    carried = graph.values_by_thread["child-new"]["messages"]
    assert [m.content for m in carried] == ["Cadence 和 Temporal 授权有区别吗？"]


def test_card_carries_readable_reason_parent_name_and_clean_name(tmp_path: Path) -> None:
    graph = BranchRecommendationGraph(
        {
            "messages": [
                HumanMessage(content="当前分支在研究南网能源。"),
                AIMessage(content="已经整理了财报要点。"),
            ]
        }
    )
    chat = _root_chat(tmp_path, graph)

    payload = chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="对比一下方案A（重试队列）和方案B（死信队列）的优缺点",
    )

    action = payload["branch_actions"][-1]
    assert action["kind"] == "fork_child_branch"
    assert action["target_parent_thread_id"] == "child-1"
    assert action["target_parent_branch_name"] == "Nanwang Energy Deep Dive"
    assert action["reason"] == "方案对比适合放到单独分支。"
    assert "route=comparison" in action["rationale"]
    assert action["suggested_branch_name"] == "方案A和方案B的优缺点"


def test_root_parent_has_no_branch_name_and_topic_name_avoids_fragments(tmp_path: Path) -> None:
    graph = _history_graph()
    chat = _root_chat(tmp_path, graph)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="New branch for the Temporal migration study",
    )

    action = payload["branch_actions"][-1]
    assert action["target_parent_branch_name"] is None
    assert action["suggested_branch_name"] == "Temporal migration study"
    assert action["reason"] == "You asked for a separate branch."


def test_execute_uses_edited_name_as_explicit_branch_name_and_runs_edited_goal(
    tmp_path: Path,
) -> None:
    graph = MultiThreadBranchActionGraph(
        {
            "root-1": {
                "messages": [
                    HumanMessage(content="帮我把订单服务的重试逻辑改成指数退避"),
                    AIMessage(content="好的，这里是修改方案……"),
                ]
            },
        }
    )
    branch_service = BranchActionBranchService()
    chat = _root_chat(tmp_path, graph, branch_service=branch_service)
    chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="另一个问题：我们的前端打包为什么这么慢？",
    )
    action = graph.values_by_thread["root-1"]["branch_actions"][-1]

    result = chat.execute_branch_action(
        thread_id="root-1",
        action_id=action["action_id"],
        user_id="owner-1",
        branch_name="  前端构建提速 ",
        handoff_message="排查 webpack 构建慢的原因并给出提速方案",
    )

    fork_call = branch_service.fork_calls[-1]
    assert fork_call["branch_name"] == "前端构建提速"
    assert result["branch_action"]["suggested_branch_name_source"] == "explicit"
    assert result["handoff_message"] == "排查 webpack 构建慢的原因并给出提速方案"
    carried = graph.values_by_thread["child-new"]["messages"]
    assert [m.content for m in carried] == ["排查 webpack 构建慢的原因并给出提速方案"]
