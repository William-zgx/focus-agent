from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.types import Command

import focus_agent.api.routers.harness_runs as harness_runs
from focus_agent.api.route_utils.branch_handoff_decisions import (
    ensure_branch_handoff_decision_from_journal,
)
from focus_agent.harness.observability import InMemoryRunJournal, JournaledStreamBridge
from focus_agent.harness.runtime import RunStatus
from focus_agent.harness.runtime.rollback import (
    ROLLBACK_TARGET_METADATA_KEY,
    CheckpointRollbackTarget,
)
from focus_agent.harness.streaming import END_SENTINEL, InMemoryStreamBridge, StreamEvent


def test_prepare_resume_payload_uses_langgraph_command_resume():
    class _Chat:
        def _preflight_thread_access(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(root_thread_id="root-1"), {"branch": "main"}, {"messages": []}

    chat = _Chat()
    payload = harness_runs.HarnessResumeRequest(
        resume={"approved": True},
        metadata={"assistant_id": "focus-agent"},
    )

    command, context, branch_meta, initial_values = harness_runs._prepare_resume_payload(
        thread_id="thread-1",
        user_id="user-1",
        payload=payload,
        chat=chat,
    )

    assert isinstance(command, Command)
    assert command.resume == {"approved": True}
    assert context.root_thread_id == "root-1"
    assert branch_meta == {"branch": "main"}
    assert initial_values == {"messages": []}
    assert chat.kwargs == {
        "thread_id": "thread-1",
        "user_id": "user-1",
        "explicit_skill_hints": (),
        "require_writable": True,
    }


def test_stream_harness_resume_skips_pre_turn_branch_recommendation(monkeypatch):
    captured: dict[str, object] = {}

    class _RunManager:
        async def attach_task(self, run_id: str, task: asyncio.Task[None]):
            captured["attached_run_id"] = run_id
            await task

    async def fake_create_run_record(**kwargs):
        captured["create_kwargs"] = kwargs
        return SimpleNamespace(run_id="run-resume-1")

    def fake_produce_run_stream(**kwargs):
        captured["produce_kwargs"] = kwargs

        async def noop():
            return None

        return noop()

    def fake_run_event_streaming_response(**kwargs):
        captured["response_kwargs"] = kwargs
        return SimpleNamespace(kind="streaming-response")

    monkeypatch.setattr(
        harness_runs,
        "_prepare_resume_payload",
        lambda **kwargs: (
            Command(resume={"approved": True}),
            SimpleNamespace(root_thread_id="root-1"),
            {"branch": "main"},
            {"messages": []},
        ),
    )
    monkeypatch.setattr(harness_runs, "_capture_run_rollback_target", lambda **kwargs: None)
    monkeypatch.setattr(harness_runs, "_create_run_record", fake_create_run_record)
    monkeypatch.setattr(harness_runs, "_produce_run_stream", fake_produce_run_stream)
    monkeypatch.setattr(harness_runs, "_run_event_streaming_response", fake_run_event_streaming_response)

    async def scenario():
        response = await harness_runs.stream_harness_resume(
            thread_id="thread-1",
            payload=harness_runs.HarnessResumeRequest(resume={"approved": True}),
            request=SimpleNamespace(state=SimpleNamespace(request_id="request-1")),
            runtime=SimpleNamespace(run_manager=_RunManager()),
            chat=SimpleNamespace(),
            principal=SimpleNamespace(user_id="user-1"),
        )

        assert response.kind == "streaming-response"
        assert captured["attached_run_id"] == "run-resume-1"
        produce_kwargs = captured["produce_kwargs"]
        assert produce_kwargs["kind"] == "chat.resume"
        assert produce_kwargs["skip_branch_recommendation"] is True
        assert produce_kwargs["request_id"] == "request-1"
        assert produce_kwargs["thread_id"] == "thread-1"
        assert produce_kwargs["user_id"] == "user-1"

    asyncio.run(scenario())


def test_branch_recommendation_timeout_uses_configured_value():
    assert (
        harness_runs._branch_recommendation_timeout_seconds(
            SimpleNamespace(agent_branch_recommendation_timeout_seconds=12)
        )
        == 12.0
    )
    assert (
        harness_runs._branch_recommendation_timeout_seconds(
            SimpleNamespace(agent_branch_recommendation_timeout_seconds=120)
        )
        == 60.0
    )
    assert (
        harness_runs._branch_recommendation_timeout_seconds(
            SimpleNamespace(agent_branch_recommendation_timeout_seconds="bad")
        )
        == harness_runs._BRANCH_RECOMMENDATION_TIMEOUT_SECONDS
    )


def test_prepare_run_payload_keeps_explicit_message_when_input_has_messages():
    class _Selection:
        stripped_message = "carried question"
        skill_ids = ()
        prompt_mode = None

    class _Chat:
        runtime = SimpleNamespace(settings=SimpleNamespace(model="model-1"))

        def _select_skills_for_message(self, **kwargs):
            self.selection_kwargs = kwargs
            return _Selection()

        def _preflight_thread_access(self, **kwargs):
            self.preflight_kwargs = kwargs
            return SimpleNamespace(root_thread_id="root-1"), None, {"messages": []}

        def _effective_thinking_mode(self, **kwargs):
            del kwargs
            return "auto"

    chat = _Chat()
    payload = harness_runs.HarnessRunRequest(
        message="carried question",
        input={"messages": [], "custom": "value"},
    )

    graph_payload, context, branch_meta, initial_values = harness_runs._prepare_run_payload(
        thread_id="thread-1",
        user_id="user-1",
        payload=payload,
        chat=chat,
    )

    assert [message.content for message in graph_payload["messages"]] == ["carried question"]
    assert graph_payload["custom"] == "value"
    assert context.root_thread_id == "root-1"
    assert branch_meta is None
    assert initial_values == {"messages": []}


def test_prepare_run_payload_preserves_thread_active_skill_without_new_trigger():
    class _Selection:
        stripped_message = "601020.SS 近一周表现"
        skill_ids = ()
        prompt_mode = None

    class _Chat:
        runtime = SimpleNamespace(settings=SimpleNamespace(model="model-1"))

        def __init__(self):
            self.preflight_calls = []

        def _select_skills_for_message(self, **kwargs):
            self.selection_kwargs = kwargs
            return _Selection()

        def _preflight_thread_access(self, **kwargs):
            self.preflight_calls.append(kwargs)
            return (
                SimpleNamespace(
                    root_thread_id="root-1",
                    skill_hints=kwargs.get("explicit_skill_hints"),
                ),
                None,
                {"messages": [], "active_skill_ids": ["stocks"]},
            )

        def _effective_thinking_mode(self, **kwargs):
            del kwargs
            return "auto"

    chat = _Chat()
    payload = harness_runs.HarnessRunRequest(message="601020.SS 近一周表现")

    graph_payload, context, branch_meta, initial_values = harness_runs._prepare_run_payload(
        thread_id="thread-1",
        user_id="user-1",
        payload=payload,
        chat=chat,
    )

    assert graph_payload["active_skill_ids"] == ["stocks"]
    assert context.skill_hints == ("stocks",)
    assert branch_meta is None
    assert initial_values["active_skill_ids"] == ["stocks"]
    assert chat.preflight_calls[0].get("explicit_skill_hints") is None
    assert chat.preflight_calls[1]["explicit_skill_hints"] == ("stocks",)


def test_prepare_run_payload_skips_duplicate_branch_handoff_auto_run_input():
    class _Selection:
        stripped_message = "carried question"
        skill_ids = ()
        prompt_mode = None

    class _Chat:
        runtime = SimpleNamespace(settings=SimpleNamespace(model="model-1"))

        def _select_skills_for_message(self, **kwargs):
            self.selection_kwargs = kwargs
            return _Selection()

        def _preflight_thread_access(self, **kwargs):
            self.preflight_kwargs = kwargs
            return (
                SimpleNamespace(root_thread_id="root-1"),
                None,
                {"messages": [HumanMessage(content="carried question")]},
            )

        def _effective_thinking_mode(self, **kwargs):
            del kwargs
            return "auto"

    payload = harness_runs.HarnessRunRequest(
        message="carried question",
        metadata={"branch_handoff_auto_run": True},
    )

    graph_payload, _context, _branch_meta, _initial_values = harness_runs._prepare_run_payload(
        thread_id="thread-1",
        user_id="user-1",
        payload=payload,
        chat=_Chat(),
    )

    assert graph_payload["messages"] == []
    assert graph_payload["task_brief"] == "carried question"


def test_run_message_from_payload_cleans_branch_handoff_auto_run():
    payload = harness_runs.HarnessRunRequest(
        message="新建子分支，探索济州岛10月亲子住宿，20字以内。",
        metadata={"branch_handoff_auto_run": True},
    )

    assert harness_runs._run_message_from_payload(payload) == "探索济州岛10月亲子住宿，20字以内"


def test_create_harness_run_skips_branch_action_intent_for_branch_handoff(monkeypatch):
    class _Selection:
        stripped_message = "探索济州岛10月亲子住宿，20字以内"
        skill_ids = ()
        prompt_mode = None

    class _Chat:
        runtime = SimpleNamespace(settings=SimpleNamespace(model="model-1"))

        def _select_skills_for_message(self, **kwargs):
            self.selection_kwargs = kwargs
            return _Selection()

        def _preflight_thread_access(self, **kwargs):
            self.preflight_kwargs = kwargs
            return SimpleNamespace(root_thread_id="root-1"), {"branch": "child"}, {"messages": []}

        def _effective_thinking_mode(self, **kwargs):
            del kwargs
            return "auto"

    async def fake_create_run_record(**kwargs):
        fake_create_run_record.kwargs = kwargs
        return SimpleNamespace(run_id="run-1")

    async def fake_execute_harness_run(**kwargs):
        fake_execute_harness_run.kwargs = kwargs
        return SimpleNamespace(run=SimpleNamespace(run_id="run-1"), thread_state={"ok": True})

    def fail_branch_action_intent(**kwargs):
        raise AssertionError("branch handoff auto-run must not create another branch action")

    monkeypatch.setattr(harness_runs, "_create_run_record", fake_create_run_record)
    monkeypatch.setattr(harness_runs, "_execute_harness_run", fake_execute_harness_run)
    monkeypatch.setattr(harness_runs, "_branch_action_intent_for_run", fail_branch_action_intent)
    monkeypatch.setattr(harness_runs, "_capture_run_rollback_target", lambda **kwargs: None)

    payload = harness_runs.HarnessRunRequest(
        message="新建子分支，探索济州岛10月亲子住宿，20字以内。",
        metadata={"branch_handoff_auto_run": True},
    )

    async def scenario():
        response = await harness_runs.create_harness_run(
            thread_id="thread-2",
            payload=payload,
            request=SimpleNamespace(state=SimpleNamespace(request_id="request-1")),
            runtime=SimpleNamespace(settings=SimpleNamespace(model="model-1")),
            chat=_Chat(),
            principal=SimpleNamespace(user_id="user-1"),
        )

        assert response.thread_state == {"ok": True}
        assert fake_create_run_record.kwargs["rollback_partial"] is False
        assert fake_execute_harness_run.kwargs["message"] == "探索济州岛10月亲子住宿，20字以内"
        assert fake_execute_harness_run.kwargs["skip_branch_recommendation"] is True

    asyncio.run(scenario())


def test_get_persisted_run_reads_runtime_event_store_when_manager_misses():
    class _Run:
        def to_dict(self):
            return {"run_id": "run-1", "thread_id": "thread-1", "status": "success"}

    class _EventStore:
        async def get_run(self, run_id: str):
            assert run_id == "run-1"
            return _Run()

    async def scenario():
        runtime = SimpleNamespace(event_store=_EventStore())
        assert await harness_runs._get_persisted_run(runtime, "run-1") == {
            "run_id": "run-1",
            "thread_id": "thread-1",
            "status": "success",
        }

    asyncio.run(scenario())


def test_create_run_record_persists_user_id():
    class _RunManager:
        async def create_or_reject(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            return SimpleNamespace(run_id="run-1")

    async def scenario():
        manager = _RunManager()
        payload = harness_runs.HarnessRunRequest(message="hello")

        await harness_runs._create_run_record(
            runtime=SimpleNamespace(run_manager=manager),
            payload=payload,
            thread_id="thread-1",
            user_id="user-1",
            graph_payload={"messages": []},
            rollback_target=CheckpointRollbackTarget(
                thread_id="thread-1",
                checkpoint_ns="",
                checkpoint_id="checkpoint-1",
                metadata={},
            ),
        )

        assert manager.args == ("thread-1",)
        assert manager.kwargs["user_id"] == "user-1"
        assert manager.kwargs["on_disconnect"].value == "rollback"
        assert manager.kwargs["rollback_target"].checkpoint_id == "checkpoint-1"
        assert manager.kwargs["metadata"][ROLLBACK_TARGET_METADATA_KEY] == {
            "thread_id": "thread-1",
            "checkpoint_ns": "",
            "checkpoint_id": "checkpoint-1",
        }

    asyncio.run(scenario())


def test_create_run_record_rejects_enqueue_with_422():
    class _RunManager:
        async def create_or_reject(self, *args, **kwargs):
            raise harness_runs.UnsupportedStrategyError(
                "Multitask strategy 'enqueue' is not supported yet."
            )

    async def scenario():
        payload = harness_runs.HarnessRunRequest(message="hello", multitask_strategy="enqueue")
        try:
            await harness_runs._create_run_record(
                runtime=SimpleNamespace(run_manager=_RunManager()),
                payload=payload,
                thread_id="thread-1",
                user_id="user-1",
                graph_payload={"messages": []},
            )
        except harness_runs.HTTPException as exc:
            assert exc.status_code == 422
            assert "enqueue" in str(exc.detail)
        else:  # pragma: no cover
            raise AssertionError("expected unsupported strategy to map to HTTP 422")

    asyncio.run(scenario())


def test_create_run_record_marks_branch_action_rollback_partial():
    class _RunManager:
        async def create_or_reject(self, *args, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(run_id="run-1")

    async def scenario():
        manager = _RunManager()
        payload = harness_runs.HarnessRunRequest(message="hello")

        await harness_runs._create_run_record(
            runtime=SimpleNamespace(run_manager=manager),
            payload=payload,
            thread_id="thread-1",
            user_id="user-1",
            graph_payload={"messages": []},
            rollback_partial=True,
            rollback_unreverted_scopes=("branch_action",),
        )

        assert manager.kwargs["metadata"]["harness.rollback_partial"] is True
        assert manager.kwargs["metadata"]["harness.rollback_unreverted_scopes"] == ["branch_action"]

    asyncio.run(scenario())


def test_create_harness_run_uses_harness_invoke_adapter(monkeypatch):
    class _Selection:
        stripped_message = "hello"
        skill_ids = ()
        prompt_mode = None

    class _Chat:
        runtime = SimpleNamespace(settings=SimpleNamespace(model="model-1"))

        def _select_skills_for_message(self, **kwargs):
            self.selection_kwargs = kwargs
            return _Selection()

        def _preflight_thread_access(self, **kwargs):
            self.preflight_kwargs = kwargs
            return SimpleNamespace(root_thread_id="root-1"), {"branch": "main"}, {"messages": []}

        def _effective_thinking_mode(self, **kwargs):
            return "auto"

        def _branch_action_intent(self, **kwargs):
            return None

        def _context_for_thread(self, **kwargs):
            return SimpleNamespace(root_thread_id="root-1"), {"branch": "main"}, {"messages": []}

        def _safe_get_interrupts(self, thread_id: str):
            return []

        def _response_payload(self, **kwargs):
            return {"thread_id": kwargs["thread_id"]}

    class _RunManager:
        def __init__(self):
            self.record = SimpleNamespace(
                run_id="run-1",
                to_dict=lambda: {"run_id": "run-1", "thread_id": "thread-1", "status": "success"},
            )
            self.statuses = []

        async def create_or_reject(self, *args, **kwargs):
            return self.record

        async def set_status(self, run_id, status, **kwargs):
            self.statuses.append((run_id, status, kwargs))

        def get(self, run_id):
            return self.record

    class _Harness:
        graph = object()

        def __init__(self):
            self.invocations = []

        def invoke(self, payload, **kwargs):
            self.invocations.append((payload, kwargs))
            return {"messages": [AIMessage(content="done")]}

    class _GraphShouldNotRun:
        def invoke(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("API must invoke through runtime.harness")

    async def scenario():
        harness = _Harness()
        manager = _RunManager()
        runtime = SimpleNamespace(
            settings=SimpleNamespace(model="model-1"),
            harness=harness,
            graph=_GraphShouldNotRun(),
            run_manager=manager,
        )
        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        response = await harness_runs.create_harness_run(
            thread_id="thread-1",
            payload=harness_runs.HarnessRunRequest(message="hello"),
            request=SimpleNamespace(state=SimpleNamespace(request_id="request-1")),
            runtime=runtime,
            chat=_Chat(),
            principal=SimpleNamespace(user_id="user-1"),
        )

        assert response.thread_state == {"thread_id": "thread-1"}
        assert harness.invocations
        assert harness.invocations[0][0]["task_brief"] == "hello"
        assert manager.statuses[-1][1] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_create_harness_run_branch_action_records_turn_trajectory(monkeypatch):
    class _Selection:
        stripped_message = "直接切过去"
        skill_ids = ()
        prompt_mode = None

    class _Chat:
        def __init__(self):
            self.selection_kwargs = None
            self.preflight_kwargs = None

        def _select_skills_for_message(self, **kwargs):
            self.selection_kwargs = kwargs
            return _Selection()

        def _preflight_thread_access(self, **kwargs):
            self.preflight_kwargs = kwargs
            return SimpleNamespace(root_thread_id="root-1"), {"branch": "main"}, {"messages": []}

        def _effective_thinking_mode(self, **kwargs):
            del kwargs
            return "auto"

        def _branch_action_intent(self, **kwargs):
            del kwargs
            return "execute"

        def _handle_branch_action_turn(self, **kwargs):
            return {
                "kind": "executed",
                "message": "已切换到新分支。",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
                "branch_action": {"action_id": "action-1", "status": "executed"},
                "branch_record": {"branch_id": "branch-2"},
                "navigation": {"root_thread_id": "root-1", "thread_id": "thread-2"},
            }

        def _context_for_thread(self, **kwargs):
            del kwargs
            return SimpleNamespace(root_thread_id="root-1"), {"branch": "main"}, {"messages": []}

    class _RunManager:
        def __init__(self):
            self.record = SimpleNamespace(
                run_id="run-1",
                to_dict=lambda: {"run_id": "run-1", "thread_id": "thread-1", "status": "success"},
            )
            self.statuses = []

        async def create_or_reject(self, *args, **kwargs):
            return self.record

        async def set_status(self, run_id, status, **kwargs):
            self.statuses.append((run_id, status, kwargs))

        def get(self, run_id):
            return self.record

    class _Harness:
        graph = object()

        def __init__(self):
            self.invocations = []

        def invoke(self, *args, **kwargs):  # pragma: no cover
            self.invocations.append((args, kwargs))
            return {"messages": []}

    async def scenario():
        recorded = []

        def _capture_record_harness_turn_and_schedule(**kwargs):
            recorded.append(kwargs)

        monkeypatch.setattr(
            harness_runs,
            "_record_harness_turn_and_schedule",
            _capture_record_harness_turn_and_schedule,
        )

        runtime = SimpleNamespace(
            settings=SimpleNamespace(model="model-1"),
            harness=_Harness(),
            graph=object(),
            run_manager=_RunManager(),
        )

        response = await harness_runs.create_harness_run(
            thread_id="thread-1",
            payload=harness_runs.HarnessRunRequest(message="hello"),
            request=SimpleNamespace(state=SimpleNamespace(request_id="request-1")),
            runtime=runtime,
            chat=_Chat(),
            principal=SimpleNamespace(user_id="user-1"),
        )

        assert response.thread_state["thread_id"] == "thread-1"
        assert recorded
        assert recorded[0]["status"] == "succeeded"
        assert recorded[0]["kind"] == "chat.turn"
        assert recorded[0]["schedule_side_effects"] is False

    asyncio.run(scenario())


def test_execute_harness_run_uses_pre_turn_branch_recommendation(monkeypatch):
    class _Chat:
        def __init__(self):
            self.recommendation_kwargs = None

        def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
            self.recommendation_kwargs = kwargs
            return {
                "kind": "recommended",
                "message": "建议新开分支继续。",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
                "branch_action": {"action_id": "action-1", "status": "pending"},
                "branch_decision": {"decision_id": "decision-1", "status": "promoted"},
            }

        def _context_for_thread(self, **kwargs):
            del kwargs
            return (
                SimpleNamespace(root_thread_id="root-1"),
                {"branch": "main"},
                {"messages": [AIMessage(content="建议新开分支继续。")]},
            )

    class _Harness:
        def __init__(self):
            self.called = False

        def invoke(self, *args, **kwargs):
            del args, kwargs
            self.called = True
            raise AssertionError("normal harness invoke should not run")

    class _Manager:
        def __init__(self):
            self.statuses = []
            self.record = SimpleNamespace(
                run_id="run-1",
                to_dict=lambda: {
                    "run_id": "run-1",
                    "thread_id": "thread-1",
                    "status": "success",
                },
            )

        def get(self, run_id: str):
            del run_id
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            self.statuses.append((run_id, status, kwargs))

    async def scenario():
        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        manager = _Manager()
        harness = _Harness()
        runtime = SimpleNamespace(
            settings=SimpleNamespace(model="model-1"),
            harness=harness,
            run_manager=manager,
        )
        chat = _Chat()

        response = await harness_runs._execute_harness_run(
            runtime=runtime,
            chat=chat,
            run_record=manager.record,
            thread_id="thread-1",
            user_id="user-1",
            message="请新开一个子分支深入研究方案 B。",
            payload={"messages": [HumanMessage(content="请新开一个子分支深入研究方案 B。")]},
            request_id="request-1",
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
        )

        assert response.thread_state == {"thread_id": "thread-1", "branch_actions": []}
        assert chat.recommendation_kwargs == {
            "thread_id": "thread-1",
            "user_id": "user-1",
            "message": "请新开一个子分支深入研究方案 B。",
            "request_id": "request-1",
        }
        assert harness.called is False
        assert manager.statuses[-1][1] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_execute_harness_run_continues_when_pre_turn_recommendation_is_not_visible(monkeypatch):
    class _Chat:
        def __init__(self):
            self.recommendation_kwargs = None

        def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
            self.recommendation_kwargs = kwargs
            return None

        def _context_for_thread(self, **kwargs):
            del kwargs
            return (
                SimpleNamespace(root_thread_id="root-1"),
                {"branch": "main"},
                {"messages": [AIMessage(content="normal answer")]},
            )

        def _response_payload(self, **kwargs):
            del kwargs
            return {"thread_id": "thread-1", "assistant_message": "normal answer"}

        def _safe_get_interrupts(self, thread_id: str):
            del thread_id
            return []

    class _Harness:
        def __init__(self):
            self.called = False

        def invoke(self, *args, **kwargs):
            del args, kwargs
            self.called = True

    class _Manager:
        def __init__(self):
            self.statuses = []
            self.record = SimpleNamespace(
                run_id="run-1",
                to_dict=lambda: {
                    "run_id": "run-1",
                    "thread_id": "thread-1",
                    "status": "success",
                },
            )

        def get(self, run_id: str):
            del run_id
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            self.statuses.append((run_id, status, kwargs))

    async def scenario():
        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})
        manager = _Manager()
        harness = _Harness()
        runtime = SimpleNamespace(
            settings=SimpleNamespace(model="model-1"),
            harness=harness,
            run_manager=manager,
        )
        chat = _Chat()

        response = await harness_runs._execute_harness_run(
            runtime=runtime,
            chat=chat,
            run_record=manager.record,
            thread_id="thread-1",
            user_id="user-1",
            message="换个主题，先看另一个问题。",
            payload={"messages": [HumanMessage(content="换个主题，先看另一个问题。")]},
            request_id="request-shadow",
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
        )

        assert response.thread_state == {
            "thread_id": "thread-1",
            "assistant_message": "normal answer",
        }
        assert chat.recommendation_kwargs["message"] == "换个主题，先看另一个问题。"
        assert harness.called is True
        assert manager.statuses[-1][1] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_execute_harness_run_skips_pre_turn_recommendation_for_branch_handoff(monkeypatch):
    class _BranchDecisionService:
        def __init__(self):
            self.records = []
            self.outcomes = []

        def record_branch_handoff_auto_run_decision(self, **kwargs):
            self.records.append(kwargs)
            return SimpleNamespace(decision_id="handoff-decision-1")

        def update_branch_handoff_auto_run_outcome(self, **kwargs):
            self.outcomes.append(kwargs)
            return SimpleNamespace(decision_id=kwargs["decision_id"])

    class _Chat:
        def __init__(self):
            self.recommendation_called = False

        def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
            del kwargs
            self.recommendation_called = True
            raise AssertionError("branch handoff auto-run must answer in the new branch")

        def _context_for_thread(self, **kwargs):
            del kwargs
            return (
                SimpleNamespace(root_thread_id="root-1"),
                {"branch": "child"},
                {"messages": [AIMessage(content="handoff answer")]},
            )

        def _response_payload(self, **kwargs):
            del kwargs
            return {"thread_id": "thread-2", "assistant_message": "handoff answer"}

        def _safe_get_interrupts(self, thread_id: str):
            del thread_id
            return []

    class _Harness:
        def __init__(self):
            self.payload = None

        def invoke(self, payload, **kwargs):
            del kwargs
            self.payload = payload

    class _Manager:
        def __init__(self):
            self.statuses = []
            self.record = SimpleNamespace(
                run_id="run-1",
                to_dict=lambda: {
                    "run_id": "run-1",
                    "thread_id": "thread-2",
                    "status": "success",
                },
            )

        def get(self, run_id: str):
            del run_id
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            self.statuses.append((run_id, status, kwargs))

    async def scenario():
        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})
        manager = _Manager()
        harness = _Harness()
        branch_decisions = _BranchDecisionService()
        runtime = SimpleNamespace(
            settings=SimpleNamespace(model="model-1"),
            harness=harness,
            run_manager=manager,
            branch_decision_service=branch_decisions,
        )
        chat = _Chat()
        payload = {"messages": [HumanMessage(content="换个主题，研究十月大阪环球影城预算。")]}

        response = await harness_runs._execute_harness_run(
            runtime=runtime,
            chat=chat,
            run_record=manager.record,
            thread_id="thread-2",
            user_id="user-1",
            message="换个主题，研究十月大阪环球影城预算。",
            payload=payload,
            request_id="request-handoff",
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "child"},
            initial_values={"messages": []},
            skip_branch_recommendation=True,
        )

        assert response.thread_state == {
            "thread_id": "thread-2",
            "assistant_message": "handoff answer",
        }
        assert harness.payload is payload
        assert chat.recommendation_called is False
        assert branch_decisions.records == [
            {
                "thread_id": "thread-2",
                "user_id": "user-1",
                "message": "换个主题，研究十月大阪环球影城预算。",
                "root_thread_id": "root-1",
                "handoff_run_id": "run-1",
                "handoff_run_status": "running",
                "request_id": "request-handoff",
                "trace_id": None,
            }
        ]
        assert branch_decisions.outcomes[-1] == {
            "decision_id": "handoff-decision-1",
            "handoff_run_id": "run-1",
            "handoff_run_status": "success",
            "message": "换个主题，研究十月大阪环球影城预算。",
            "error": None,
        }
        assert manager.statuses[-1][1] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_ensure_branch_handoff_decision_from_journal_backfills_missing_event():
    class _BranchDecisionService:
        def __init__(self):
            self.decisions = []
            self.records = []
            self.outcomes = []

        def list_decisions(self, **kwargs):
            self.list_kwargs = kwargs
            return list(self.decisions)

        def record_branch_handoff_auto_run_decision(self, **kwargs):
            self.records.append(kwargs)
            event = SimpleNamespace(decision_id="handoff-decision-1")
            self.decisions.append(event)
            return event

        def update_branch_handoff_auto_run_outcome(self, **kwargs):
            self.outcomes.append(kwargs)
            return SimpleNamespace(decision_id=kwargs["decision_id"])

    async def scenario():
        event_store = InMemoryRunJournal()
        await event_store.put(
            "run-1",
            thread_id="thread-2",
            user_id="user-1",
            status="interrupted",
            metadata={"branch_handoff_auto_run": True, "root_thread_id": "root-1"},
            kwargs={"input": {"task_brief": "探索十月大阪环球影城预算。"}},
            error="user stopped generation",
        )
        service = _BranchDecisionService()
        runtime = SimpleNamespace(event_store=event_store, branch_decision_service=service)

        event = await ensure_branch_handoff_decision_from_journal(
            runtime=runtime,
            thread_id="thread-2",
            user_id="user-1",
            request_id="request-1",
        )
        existing = await ensure_branch_handoff_decision_from_journal(
            runtime=runtime,
            thread_id="thread-2",
            user_id="user-1",
            request_id="request-2",
        )

        assert event.decision_id == "handoff-decision-1"
        assert existing.decision_id == "handoff-decision-1"
        assert service.list_kwargs == {"thread_id": "thread-2", "user_id": "user-1", "limit": 1}
        assert service.records == [
            {
                "thread_id": "thread-2",
                "user_id": "user-1",
                "message": "探索十月大阪环球影城预算。",
                "root_thread_id": "root-1",
                "handoff_run_id": "run-1",
                "handoff_run_status": "interrupted",
                "request_id": "request-1",
                "trace_id": None,
            }
        ]
        assert service.outcomes == [
            {
                "decision_id": "handoff-decision-1",
                "handoff_run_id": "run-1",
                "handoff_run_status": "interrupted",
                "message": "探索十月大阪环球影城预算。",
                "error": "user stopped generation",
            }
        ]

    asyncio.run(scenario())


def test_execute_harness_run_continues_when_pre_turn_recommendation_is_busy(monkeypatch):
    class _Chat:
        def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
            del kwargs
            raise harness_runs.ConcurrentTurnError("busy")

        def _context_for_thread(self, **kwargs):
            del kwargs
            return (
                SimpleNamespace(root_thread_id="root-1"),
                {"branch": "child"},
                {"messages": [AIMessage(content="normal answer")]},
            )

        def _response_payload(self, **kwargs):
            del kwargs
            return {"thread_id": "thread-1", "assistant_message": "normal answer"}

        def _safe_get_interrupts(self, thread_id: str):
            del thread_id
            return []

    class _Harness:
        def __init__(self):
            self.called = False

        def invoke(self, *args, **kwargs):
            del args, kwargs
            self.called = True

    class _Manager:
        def __init__(self):
            self.statuses = []
            self.record = SimpleNamespace(
                run_id="run-1",
                to_dict=lambda: {
                    "run_id": "run-1",
                    "thread_id": "thread-1",
                    "status": "success",
                },
            )

        def get(self, run_id: str):
            del run_id
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            self.statuses.append((run_id, status, kwargs))

    async def scenario():
        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})
        manager = _Manager()
        harness = _Harness()
        runtime = SimpleNamespace(
            settings=SimpleNamespace(model="model-1"),
            harness=harness,
            run_manager=manager,
        )

        response = await harness_runs._execute_harness_run(
            runtime=runtime,
            chat=_Chat(),
            run_record=manager.record,
            thread_id="thread-1",
            user_id="user-1",
            message="大阪环球影城十月亲子预算怎么安排？",
            payload={"messages": [HumanMessage(content="大阪环球影城十月亲子预算怎么安排？")]},
            request_id="request-busy",
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "child"},
            initial_values={"messages": []},
        )

        assert response.thread_state == {
            "thread_id": "thread-1",
            "assistant_message": "normal answer",
        }
        assert harness.called is True
        assert manager.statuses[-1][1] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_record_harness_turn_and_schedule_can_skip_side_effect_hooks(monkeypatch):
    calls = []

    def _capture_chat_hook(chat, method, *args, **kwargs):
        del chat, args, kwargs
        calls.append(method)

    monkeypatch.setattr(harness_runs, "_call_chat_hook", _capture_chat_hook)

    harness_runs._record_harness_turn_and_schedule(
        chat=object(),
        thread_id="thread-1",
        user_id="user-1",
        root_thread_id="root-1",
        kind="chat.turn",
        status="succeeded",
        final_values={"messages": []},
        initial_message_count=0,
        initial_llm_calls=0,
        started_at=object(),
        branch_meta={"branch": "main"},
        trace_correlation=None,
        payload={"messages": [HumanMessage(content="hello")]},
        answer="done",
        schedule_side_effects=False,
    )

    assert calls == ["_record_turn_trajectory_best_effort"]


def test_authorize_run_access_rejects_mismatched_user():
    class _Chat:
        def _preflight_thread_access(self, **kwargs):
            raise AssertionError("thread access should not run after user mismatch")

    principal = SimpleNamespace(user_id="user-2")

    try:
        harness_runs._authorize_run_access(
            chat=_Chat(),
            principal=principal,
            run_payload={"run_id": "run-1", "thread_id": "thread-1", "user_id": "user-1"},
        )
    except harness_runs.HTTPException as exc:
        assert exc.status_code == 403
    else:  # pragma: no cover
        raise AssertionError("expected authorization failure")


def test_stream_existing_harness_run_replays_with_last_event_id_without_cancelling():
    class _Run:
        def to_dict(self):
            return {
                "run_id": "run-1",
                "thread_id": "thread-1",
                "user_id": "user-1",
                "status": "running",
            }

    class _RunManager:
        def __init__(self):
            self.cancelled = False

        def get(self, run_id: str):
            assert run_id == "run-1"
            return _Run()

        async def cancel(self, *args, **kwargs):
            self.cancelled = True
            return True

    class _Bridge:
        def __init__(self):
            self.subscription = None

        async def subscribe(
            self, run_id: str, *, last_event_id: str | None, heartbeat_interval: float
        ):
            self.subscription = {
                "run_id": run_id,
                "last_event_id": last_event_id,
                "heartbeat_interval": heartbeat_interval,
            }
            yield StreamEvent(
                id="evt-2",
                event="message.delta",
                data={
                    "run_id": "run-1",
                    "thread_id": "thread-1",
                    "turn_id": "run-1",
                    "sequence": 2,
                    "source_node": "agent",
                    "delta": "continued",
                },
            )
            yield END_SENTINEL

    class _Chat:
        def _preflight_thread_access(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(), None, {}

    async def scenario():
        manager = _RunManager()
        bridge = _Bridge()
        chat = _Chat()
        request = SimpleNamespace(headers={"last-event-id": "evt-1"})
        runtime = SimpleNamespace(
            run_manager=manager,
            event_store=None,
            stream_bridge=bridge,
            settings=SimpleNamespace(sse_heartbeat_seconds=7),
        )

        response = await harness_runs.stream_existing_harness_run(
            run_id="run-1",
            request=request,
            runtime=runtime,
            chat=chat,
            principal=SimpleNamespace(user_id="user-1"),
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        assert bridge.subscription == {
            "run_id": "run-1",
            "last_event_id": "evt-1",
            "heartbeat_interval": 7,
        }
        assert chat.kwargs["thread_id"] == "thread-1"
        assert "event: message.delta" in "".join(chunks)
        assert "continued" in "".join(chunks)
        assert manager.cancelled is False

    asyncio.run(scenario())


def test_harness_observability_endpoints_read_authorized_journal():
    class _Run:
        def to_dict(self):
            return {
                "run_id": "run-1",
                "thread_id": "thread-1",
                "user_id": "user-1",
                "status": "success",
            }

    class _RunManager:
        def get(self, run_id: str):
            assert run_id == "run-1"
            return _Run()

    class _Event:
        def to_dict(self):
            return {"event_id": "event-1", "run_id": "run-1", "event": "run.completed"}

    class _EventStore:
        async def list_events(self, run_id: str, *, event=None, limit=None):
            assert (run_id, event, limit) == ("run-1", "run.completed", 10)
            return [_Event()]

        async def snapshot(self, run_id: str):
            assert run_id == "run-1"
            return {"run": {"run_id": "run-1"}, "events": [{"event": "run.completed"}]}

        async def trajectory_summary(self, run_id: str):
            assert run_id == "run-1"
            return {"id": "run-1", "kind": "harness_run"}

    class _Chat:
        def _preflight_thread_access(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(), None, {}

    async def scenario():
        runtime = SimpleNamespace(run_manager=_RunManager(), event_store=_EventStore())
        chat = _Chat()
        principal = SimpleNamespace(user_id="user-1")

        events = await harness_runs.list_harness_run_events(
            "run-1",
            runtime=runtime,
            chat=chat,
            principal=principal,
            event="run.completed",
            limit=10,
        )
        snapshot = await harness_runs.get_harness_run_snapshot(
            "run-1",
            runtime=runtime,
            chat=chat,
            principal=principal,
        )
        trajectory = await harness_runs.get_harness_run_trajectory(
            "run-1",
            runtime=runtime,
            chat=chat,
            principal=principal,
        )

        assert events["events"] == [
            {"event_id": "event-1", "run_id": "run-1", "event": "run.completed"}
        ]
        assert snapshot["run"]["run_id"] == "run-1"
        assert trajectory == {"id": "run-1", "kind": "harness_run"}
        assert chat.kwargs["thread_id"] == "thread-1"

    asyncio.run(scenario())


class _CollectingBridge:
    def __init__(self):
        self.events = []
        self.ended = False

    async def publish(self, run_id: str, event: str, data: dict):
        self.events.append((event, data))
        return SimpleNamespace(id=f"evt-{len(self.events)}", event=event, data=data)

    async def publish_end(self, run_id: str):
        self.ended = True


class _CollectingRunManager:
    def __init__(self):
        self.statuses = []
        self.record = SimpleNamespace(abort_event=asyncio.Event())

    def get(self, run_id: str):
        return self.record

    async def set_status(self, run_id: str, status: RunStatus, **kwargs):
        self.statuses.append((status, kwargs))


class _ProducerChat:
    def __init__(self, final_messages):
        self.final_messages = list(final_messages)

    def _context_for_thread(self, **kwargs):
        del kwargs
        return (
            SimpleNamespace(root_thread_id="root-1"),
            {"branch": "main"},
            {"messages": self.final_messages},
        )

    def _latest_final_ai_text(self, messages):
        for message in reversed(messages):
            content = getattr(message, "content", "")
            if content:
                return str(content)
        return ""

    def _safe_get_interrupts(self, thread_id: str):
        return []

    def _response_payload(self, **kwargs):
        return {"thread_id": kwargs["thread_id"], "messages": [{"type": "ai", "content": "done"}]}


_DEGRADED_DSML_FIXTURE = (
    "您说得对，让我把时间校准到当下，搜一下 2026 年的最新动态。好，拿到了几篇关键文章。\n\n"
    'invoke name">\n'
    'parameter name="" string="true">direct</ | | DSML | | parameter>\n'
    'parameter name="" string="true">https://mem0.ai/blog/state-of-ai-agent-memory-2026'
    "</ | | DSML | | parameter>\n"
    'parameter name="" string="false">2</ | | DSML | | parameter>\n'
    "</ | | DSML | | invoke>"
)


async def _collect_produced_events(
    monkeypatch,
    chunks,
    *,
    final_messages=None,
    error: Exception | None = None,
    abort_requested: bool = False,
    chat=None,
):
    async def fake_stream_chunks(**kwargs):
        del kwargs
        if error is not None:
            raise error
        for chunk in chunks:
            yield chunk

    class _Harness:
        graph = object()

        def __init__(self):
            self.called = False

        async def stream_chunks(self, **kwargs):
            self.called = True
            assert kwargs["payload"] == {"messages": []}
            async for chunk in fake_stream_chunks(**kwargs):
                yield chunk

    bridge = _CollectingBridge()
    manager = _CollectingRunManager()
    if abort_requested:
        manager.record.abort_event.set()
    runtime = SimpleNamespace(
        harness=_Harness(),
        checkpointer=None,
        settings=SimpleNamespace(sse_heartbeat_seconds=0),
        run_manager=manager,
        stream_bridge=bridge,
    )

    monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
    monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

    producer_final_messages = (
        [AIMessage(content="done")] if final_messages is None else final_messages
    )
    producer_chat = chat or _ProducerChat(producer_final_messages)

    await harness_runs._produce_run_stream(
        runtime=runtime,
        chat=producer_chat,
        run_id="run-1",
        thread_id="thread-1",
        user_id="user-1",
        payload={"messages": []},
        context=SimpleNamespace(root_thread_id="root-1"),
        branch_meta={"branch": "main"},
        initial_values={"messages": []},
        request_id="request-1",
    )
    return bridge.events, manager.statuses, bridge.ended


def _ai_stream_chunk(
    content, *, node: str = "agent", stream_phase: str | None = None, tags: list[str] | None = None
):
    metadata = {"langgraph_node": node}
    if stream_phase is not None:
        metadata["stream_phase"] = stream_phase
    if tags is not None:
        metadata["tags"] = tags
    return {
        "type": "messages",
        "data": (SimpleNamespace(content=content, type="ai"), metadata),
        "ns": [],
    }


def _visible_ai_chunk(content):
    return _ai_stream_chunk(content, stream_phase="visible")


def _quarantine_ai_chunk(content):
    return _ai_stream_chunk(content, stream_phase="quarantine")


def _reasoning_delta_chunk(text: str):
    return _ai_stream_chunk([{"type": "reasoning_delta", "text": text}])


def _tool_call_chunk(
    *,
    call_id: str = "call-1",
    name: str = "web_search",
    args: str = '{"q":"agent"}',
    stream_phase: str | None = None,
):
    metadata = {"langgraph_node": "agent"}
    if stream_phase is not None:
        metadata["stream_phase"] = stream_phase
    return {
        "type": "messages",
        "data": (
            AIMessageChunk(
                content=[{"type": "tool_call_chunk", "id": call_id, "name": name, "args": args}]
            ),
            metadata,
        ),
        "ns": [],
    }


def _event_names(events):
    return [event for event, _data in events]


def _message_deltas(events):
    return [data["delta"] for event, data in events if event == "message.delta"]


def _completed_messages(events):
    return [data["content"] for event, data in events if event == "message.completed"]


def _reasoning_deltas(events):
    return [data["delta"] for event, data in events if event == "reasoning.delta"]


def _assert_no_message_output(events):
    event_names = _event_names(events)
    assert "message.delta" not in event_names
    assert "message.completed" not in event_names


def test_produce_run_stream_emits_canonical_v2_events(monkeypatch):
    async def fake_stream_chunks(**kwargs):
        del kwargs
        yield {
            "type": "messages",
            "data": (
                SimpleNamespace(content="hello", type="ai", id="msg-1"),
                {"langgraph_node": "agent", "stream_phase": "visible"},
            ),
            "ns": [],
        }

    class _Harness:
        graph = object()

        def __init__(self):
            self.called = False

        async def stream_chunks(self, **kwargs):
            self.called = True
            assert kwargs["payload"] == {"messages": []}
            async for chunk in fake_stream_chunks(**kwargs):
                yield chunk

    class _Bridge:
        def __init__(self):
            self.events = []
            self.ended = False

        async def publish(self, run_id: str, event: str, data: dict):
            self.events.append((event, data))
            return SimpleNamespace(id=f"evt-{len(self.events)}", event=event, data=data)

        async def publish_end(self, run_id: str):
            self.ended = True

    class _Manager:
        def __init__(self):
            self.statuses = []
            self.record = SimpleNamespace(abort_event=asyncio.Event())

        def get(self, run_id: str):
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            self.statuses.append((status, kwargs))

    class _Chat:
        def _context_for_thread(self, **kwargs):
            del kwargs
            return (
                SimpleNamespace(root_thread_id="root-1"),
                {"branch": "main"},
                {"messages": [AIMessage(content="done")]},
            )

        def _latest_final_ai_text(self, messages):
            for message in reversed(messages):
                content = getattr(message, "content", "")
                if content:
                    return str(content)
            return ""

        def _safe_get_interrupts(self, thread_id: str):
            return []

        def _response_payload(self, **kwargs):
            return {
                "thread_id": kwargs["thread_id"],
                "messages": [{"type": "ai", "content": "done"}],
            }

    async def scenario():
        bridge = _Bridge()
        manager = _Manager()
        harness = _Harness()
        runtime = SimpleNamespace(
            harness=harness,
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=manager,
            stream_bridge=bridge,
        )

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        await harness_runs._produce_run_stream(
            runtime=runtime,
            chat=_Chat(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            payload={"messages": []},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
            request_id="request-1",
        )

        event_names = [event for event, _data in bridge.events]
        assert "visible_text.delta" not in event_names
        assert event_names == [
            "run.metadata",
            "run.status",
            "message.delta",
            "message.completed",
            "run.completed",
            "run.closed",
        ]
        assert bridge.events[2][1]["delta"] == "hello"
        assert bridge.events[2][1]["message_id"] == "msg-1"
        assert "stream_phase" not in bridge.events[2][1]["metadata"]
        assert bridge.events[3][1]["content"] == "done"
        assert bridge.events[4][1]["thread_state"]["thread_id"] == "thread-1"
        assert bridge.events[-1][1]["source_node"] == "harness"
        assert bridge.ended is True
        assert harness.called is True
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_run_stream_uses_pre_turn_branch_recommendation(monkeypatch):
    class _Harness:
        graph = object()

        def __init__(self):
            self.called = False

        async def stream_chunks(self, **kwargs):
            del kwargs
            self.called = True
            raise AssertionError("normal harness stream should not run")
            yield  # pragma: no cover

    class _Chat(_ProducerChat):
        def __init__(self):
            super().__init__([AIMessage(content="建议新开分支继续。")])
            self.recommendation_kwargs = None

        def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
            self.recommendation_kwargs = kwargs
            return {
                "kind": "recommended",
                "message": "建议新开分支继续。",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
                "branch_action": {"action_id": "action-1", "status": "pending"},
                "branch_decision": {"decision_id": "decision-1", "status": "promoted"},
            }

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        harness = _Harness()
        runtime = SimpleNamespace(
            harness=harness,
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=manager,
            stream_bridge=bridge,
        )
        chat = _Chat()

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        await harness_runs._produce_run_stream(
            runtime=runtime,
            chat=chat,
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            payload={"messages": [HumanMessage(content="请新开一个子分支深入研究方案 B。")]},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
            request_id="request-1",
        )

        assert _event_names(bridge.events) == [
            "run.metadata",
            "run.status",
            "message.completed",
            "run.completed",
            "run.closed",
        ]
        assert bridge.events[2][1]["content"] == "建议新开分支继续。"
        assert bridge.events[3][1]["branch_action"] == {
            "action_id": "action-1",
            "status": "pending",
        }
        assert chat.recommendation_kwargs["message"] == "请新开一个子分支深入研究方案 B。"
        assert harness.called is False
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_run_stream_offloads_pre_turn_branch_recommendation(monkeypatch):
    class _Harness:
        graph = object()

        async def stream_chunks(self, **kwargs):
            del kwargs
            raise AssertionError("normal harness stream should not run")
            yield  # pragma: no cover

    class _Chat(_ProducerChat):
        def __init__(self):
            super().__init__([AIMessage(content="建议新开分支继续。")])
            self.started = threading.Event()
            self.finished = threading.Event()

        def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
            del kwargs
            self.started.set()
            time.sleep(0.2)
            self.finished.set()
            return {
                "kind": "recommended",
                "message": "建议新开分支继续。",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
            }

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        runtime = SimpleNamespace(
            harness=_Harness(),
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=manager,
            stream_bridge=bridge,
        )
        chat = _Chat()
        ticks: list[float] = []
        keep_ticking = True

        async def ticker():
            while keep_ticking:
                ticks.append(time.perf_counter())
                await asyncio.sleep(0.01)

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        ticker_task = asyncio.create_task(ticker())
        producer_task = asyncio.create_task(
            harness_runs._produce_run_stream(
                runtime=runtime,
                chat=chat,
                run_id="run-1",
                thread_id="thread-1",
                user_id="user-1",
                payload={"messages": [HumanMessage(content="请新开一个子分支深入研究方案 B。")]},
                context=SimpleNamespace(root_thread_id="root-1"),
                branch_meta={"branch": "main"},
                initial_values={"messages": []},
                request_id="request-1",
            )
        )

        while not chat.started.is_set():
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)
        assert chat.finished.is_set() is False
        assert len(ticks) >= 2

        await producer_task
        keep_ticking = False
        await ticker_task

        assert _event_names(bridge.events) == [
            "run.metadata",
            "run.status",
            "message.completed",
            "run.completed",
            "run.closed",
        ]
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_run_stream_times_out_pre_turn_branch_recommendation(monkeypatch):
    class _Harness:
        graph = object()

        def __init__(self):
            self.called = False

        async def stream_chunks(self, **kwargs):
            del kwargs
            self.called = True
            yield _visible_ai_chunk("hello")

    class _Chat(_ProducerChat):
        def __init__(self):
            super().__init__([AIMessage(content="done")])
            self.started = threading.Event()
            self.release = threading.Event()

        def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
            del kwargs
            self.started.set()
            self.release.wait(timeout=30)
            return {
                "kind": "recommended",
                "message": "late recommendation",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
            }

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        harness = _Harness()
        runtime = SimpleNamespace(
            harness=harness,
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=manager,
            stream_bridge=bridge,
        )
        chat = _Chat()

        monkeypatch.setattr(harness_runs, "_BRANCH_RECOMMENDATION_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        try:
            await asyncio.wait_for(
                harness_runs._produce_run_stream(
                    runtime=runtime,
                    chat=chat,
                    run_id="run-1",
                    thread_id="thread-1",
                    user_id="user-1",
                    payload={"messages": [HumanMessage(content="普通对话继续回答。")]},
                    context=SimpleNamespace(root_thread_id="root-1"),
                    branch_meta={"branch": "main"},
                    initial_values={"messages": []},
                    request_id="request-1",
                ),
                timeout=0.5,
            )
        finally:
            chat.release.set()
            await asyncio.sleep(0.05)

        assert chat.started.is_set()
        assert harness.called is True
        assert _event_names(bridge.events) == [
            "run.metadata",
            "run.status",
            "message.delta",
            "message.completed",
            "run.completed",
            "run.closed",
        ]
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_run_stream_skips_pre_turn_recommendation_for_branch_handoff(monkeypatch):
    class _BranchDecisionService:
        def __init__(self):
            self.records = []
            self.outcomes = []

        def record_branch_handoff_auto_run_decision(self, **kwargs):
            self.records.append(kwargs)
            return SimpleNamespace(decision_id="handoff-decision-1")

        def update_branch_handoff_auto_run_outcome(self, **kwargs):
            self.outcomes.append(kwargs)
            return SimpleNamespace(decision_id=kwargs["decision_id"])

    class _Harness:
        graph = object()

        def __init__(self):
            self.called = False

        async def stream_chunks(self, **kwargs):
            self.called = True
            assert kwargs["payload"] == {
                "messages": [HumanMessage(content="换个主题，研究十月大阪环球影城预算。")]
            }
            yield _visible_ai_chunk("handoff answer")

    class _Chat(_ProducerChat):
        def __init__(self):
            super().__init__([AIMessage(content="handoff final")])
            self.recommendation_called = False

        def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
            del kwargs
            self.recommendation_called = True
            raise AssertionError("branch handoff auto-run must stream the new branch answer")

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        harness = _Harness()
        branch_decisions = _BranchDecisionService()
        runtime = SimpleNamespace(
            harness=harness,
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=manager,
            stream_bridge=bridge,
            branch_decision_service=branch_decisions,
        )
        chat = _Chat()

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        await harness_runs._produce_run_stream(
            runtime=runtime,
            chat=chat,
            run_id="run-1",
            thread_id="thread-2",
            user_id="user-1",
            payload={"messages": [HumanMessage(content="换个主题，研究十月大阪环球影城预算。")]},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "child"},
            initial_values={"messages": []},
            request_id="request-handoff",
            message="换个主题，研究十月大阪环球影城预算。",
            skip_branch_recommendation=True,
        )

        assert _event_names(bridge.events) == [
            "run.metadata",
            "run.status",
            "message.delta",
            "message.completed",
            "run.completed",
            "run.closed",
        ]
        assert _completed_messages(bridge.events) == ["handoff final"]
        assert bridge.events[4][1].get("branch_action") is None
        assert bridge.events[4][1]["thread_state"] == {
            "thread_id": "thread-2",
            "messages": [{"type": "ai", "content": "done"}],
        }
        assert chat.recommendation_called is False
        assert harness.called is True
        assert branch_decisions.records == [
            {
                "thread_id": "thread-2",
                "user_id": "user-1",
                "message": "换个主题，研究十月大阪环球影城预算。",
                "root_thread_id": "root-1",
                "handoff_run_id": "run-1",
                "handoff_run_status": "running",
                "request_id": "request-handoff",
                "trace_id": None,
            }
        ]
        assert branch_decisions.outcomes[-1] == {
            "decision_id": "handoff-decision-1",
            "handoff_run_id": "run-1",
            "handoff_run_status": "success",
            "message": "换个主题，研究十月大阪环球影城预算。",
            "error": None,
        }
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_run_stream_continues_when_pre_turn_recommendation_is_busy(monkeypatch):
    class _Harness:
        graph = object()

        def __init__(self):
            self.called = False

        async def stream_chunks(self, **kwargs):
            del kwargs
            self.called = True
            yield _visible_ai_chunk("normal answer")

    class _Chat(_ProducerChat):
        def __init__(self):
            super().__init__([AIMessage(content="normal final")])

        def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
            del kwargs
            raise harness_runs.ConcurrentTurnError("busy")

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        harness = _Harness()
        runtime = SimpleNamespace(
            harness=harness,
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=manager,
            stream_bridge=bridge,
        )

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        await harness_runs._produce_run_stream(
            runtime=runtime,
            chat=_Chat(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            payload={"messages": [HumanMessage(content="大阪环球影城十月亲子预算怎么安排？")]},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "child"},
            initial_values={"messages": []},
            request_id="request-busy",
            message="大阪环球影城十月亲子预算怎么安排？",
        )

        assert _event_names(bridge.events) == [
            "run.metadata",
            "run.status",
            "message.delta",
            "message.completed",
            "run.completed",
            "run.closed",
        ]
        assert _completed_messages(bridge.events) == ["normal final"]
        assert harness.called is True
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_branch_action_run_stream_emits_canonical_completion():
    class _Chat:
        def __init__(self):
            self.kwargs = None

        def _handle_branch_action_turn(self, **kwargs):
            self.kwargs = kwargs
            return {
                "kind": "executed",
                "message": "已切换到新分支。",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
                "branch_action": {"action_id": "action-1", "status": "executed"},
                "branch_record": {"branch_id": "branch-2"},
                "navigation": {"root_thread_id": "root-1", "thread_id": "thread-2"},
            }

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        runtime = SimpleNamespace(run_manager=manager, stream_bridge=bridge)
        chat = _Chat()

        await harness_runs._produce_branch_action_run_stream(
            runtime=runtime,
            chat=chat,
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            message="直接切过去",
            request_id="request-1",
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
        )

        event_names = [event for event, _data in bridge.events]
        assert "visible_text.delta" not in event_names
        assert event_names == [
            "run.metadata",
            "run.status",
            "message.completed",
            "run.completed",
            "run.closed",
        ]
        assert chat.kwargs == {
            "thread_id": "thread-1",
            "user_id": "user-1",
            "message": "直接切过去",
            "request_id": "request-1",
        }
        assert bridge.events[2][1]["content"] == "已切换到新分支。"
        completed = bridge.events[3][1]
        assert completed["thread_state"]["thread_id"] == "thread-1"
        assert completed["branch_action"]["action_id"] == "action-1"
        assert completed["branch_record"]["branch_id"] == "branch-2"
        assert completed["navigation"] == {"root_thread_id": "root-1", "thread_id": "thread-2"}
        assert bridge.ended is True
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_branch_action_run_stream_completes_after_task_cancel():
    class _Chat:
        def __init__(self):
            self.started = threading.Event()

        def _handle_branch_action_turn(self, **kwargs):
            del kwargs
            self.started.set()
            time.sleep(0.03)
            return {
                "kind": "executed",
                "message": "已切换到新分支。",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
                "branch_action": {"action_id": "action-1", "status": "executed"},
                "branch_record": {"branch_id": "branch-2"},
                "navigation": {"root_thread_id": "root-1", "thread_id": "thread-2"},
            }

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        runtime = SimpleNamespace(run_manager=manager, stream_bridge=bridge)
        chat = _Chat()

        task = asyncio.create_task(
            harness_runs._produce_branch_action_run_stream(
                runtime=runtime,
                chat=chat,
                run_id="run-1",
                thread_id="thread-1",
                user_id="user-1",
                message="直接切过去",
                request_id="request-1",
                context=SimpleNamespace(root_thread_id="root-1"),
                branch_meta={"branch": "main"},
                initial_values={"messages": []},
            )
        )
        assert await asyncio.to_thread(chat.started.wait, 1.0)
        task.cancel()
        await task

        event_names = [event for event, _data in bridge.events]
        assert "run.completed" in event_names
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_produce_branch_action_run_stream_records_turn_trajectory(monkeypatch):
    class _Chat:
        def _handle_branch_action_turn(self, **kwargs):
            del kwargs
            return {
                "kind": "executed",
                "message": "已切换到新分支。",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
                "branch_action": {"action_id": "action-1", "status": "executed"},
                "branch_record": {"branch_id": "branch-2"},
                "navigation": {"root_thread_id": "root-1", "thread_id": "thread-2"},
            }

        def _context_for_thread(self, **kwargs):
            del kwargs
            return (
                SimpleNamespace(root_thread_id="root-1"),
                {"branch": "main"},
                {"messages": []},
            )

    async def scenario():
        recorded = []

        def _capture_record_harness_turn_and_schedule(**kwargs):
            recorded.append(kwargs)

        monkeypatch.setattr(
            harness_runs,
            "_record_harness_turn_and_schedule",
            _capture_record_harness_turn_and_schedule,
        )

        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        runtime = SimpleNamespace(run_manager=manager, stream_bridge=bridge)

        await harness_runs._produce_branch_action_run_stream(
            runtime=runtime,
            chat=_Chat(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            message="直接切过去",
            request_id="request-1",
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
            kind="chat.turn",
        )

        assert recorded
        assert recorded[0]["status"] == "succeeded"
        assert recorded[0]["kind"] == "chat.turn"
        assert recorded[0]["branch_meta"] == {"branch": "main"}
        assert recorded[0]["schedule_side_effects"] is False

    asyncio.run(scenario())


def test_produce_branch_action_run_stream_drops_tool_protocol_message():
    class _Chat:
        def _handle_branch_action_turn(self, **kwargs):
            del kwargs
            return {
                "kind": "executed",
                "message": "invoke name\nparameter name\n| | DSML | |",
                "thread_state": {"thread_id": "thread-1", "branch_actions": []},
            }

    async def scenario():
        bridge = _CollectingBridge()
        manager = _CollectingRunManager()
        runtime = SimpleNamespace(run_manager=manager, stream_bridge=bridge)

        await harness_runs._produce_branch_action_run_stream(
            runtime=runtime,
            chat=_Chat(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            message="直接切过去",
            request_id="request-1",
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
        )

        event_names = [event for event, _data in bridge.events]

        assert "message.completed" not in event_names
        assert "run.completed" in event_names
        assert manager.statuses[-1][0] is RunStatus.SUCCESS

    asyncio.run(scenario())


def test_branch_action_intent_for_run_delegates_to_chat_facade():
    class _Chat:
        def _branch_action_intent(self, **kwargs):
            self.kwargs = kwargs
            return "propose"

    chat = _Chat()

    assert harness_runs._branch_action_intent_for_run(
        chat=chat,
        initial_values={"branch_actions": []},
        branch_meta={"branch": "main"},
        message="开个分支",
    )
    assert chat.kwargs == {
        "values": {"branch_actions": []},
        "branch_meta": {"branch": "main"},
        "message": "开个分支",
    }


def test_produce_run_stream_filters_internal_and_tool_fallback_drafts(monkeypatch):
    chunks = [
        _ai_stream_chunk('{"expected_tools":["search"],"status":"replan"}', node="plan"),
        _ai_stream_chunk("我先根据已拿到的工具结果给出一个保守整理：\n- web_search: interim"),
        _visible_ai_chunk("真正回答"),
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks,
            final_messages=[AIMessage(content="真正回答最终。")],
        )
        assert _message_deltas(events) == ["真正回答"]
        assert _completed_messages(events) == ["真正回答最终。"]

    asyncio.run(scenario())


def test_produce_run_stream_quarantines_unmarked_and_quarantine_agent_text(monkeypatch):
    chunks = [
        _ai_stream_chunk("未标记的阶段文本"),
        _quarantine_ai_chunk(_DEGRADED_DSML_FIXTURE),
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks,
            final_messages=[AIMessage(content="最终安全回答。")],
        )
        assert _message_deltas(events) == []
        assert _completed_messages(events) == ["最终安全回答。"]

    asyncio.run(scenario())


def test_produce_run_stream_drops_visible_phase_english_process_narration(monkeypatch):
    chunks = [
        _visible_ai_chunk("Let me fetch the latest numbers before answering."),
        _visible_ai_chunk("最终安全回答"),
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks,
            final_messages=[AIMessage(content="最终安全回答。")],
        )
        assert _message_deltas(events) == ["最终安全回答"]
        assert _completed_messages(events) == ["最终安全回答。"]

    asyncio.run(scenario())


def test_produce_run_stream_drops_visible_phase_chinese_tool_deliberation(monkeypatch):
    chunks = [
        _visible_ai_chunk(
            "和 websearch。我因为不满意搜索结果而犹豫和重复调用，这是不对的。"
            "现在我直接执行：1. webfetch抓取 Threads帖子；"
            '2. web_search英文搜索 "OpenAI Codex latest news May2026"。'
        ),
        _visible_ai_chunk("最终安全回答"),
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks,
            final_messages=[AIMessage(content="最终安全回答。")],
        )
        assert _message_deltas(events) == ["最终安全回答"]
        assert _completed_messages(events) == ["最终安全回答。"]

    asyncio.run(scenario())


def test_produce_run_stream_drops_split_visible_phase_english_process_narration(monkeypatch):
    chunks = [
        _visible_ai_chunk("Let"),
        _visible_ai_chunk(" me fetch the latest source."),
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )
        _assert_no_message_output(events)

    asyncio.run(scenario())


def test_produce_run_stream_streams_final_suffix_from_mixed_visible_process_text(monkeypatch):
    chunks = [
        _visible_ai_chunk(
            "Let me produce the final answer. I must not call more tools. Let's go.最终答案。"
        ),
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[
                AIMessage(
                    content="Let me produce the final answer. I must not call more tools. Let's go.最终答案。"
                )
            ],
        )
        assert _message_deltas(events) == ["最终答案。"]
        assert _completed_messages(events) == ["最终答案。"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "content",
    [
        "I should look up one more source before answering.",
        _DEGRADED_DSML_FIXTURE,
        "invoke name\nparameter name\n| | DSML | |",
    ],
    ids=["english-process", "tool-protocol", "bare-dsml"],
)
def test_produce_run_stream_drops_protocol_or_process_completed_fallback(monkeypatch, content):
    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=[],
            final_messages=[AIMessage(content=content)],
        )

        assert "message.completed" not in _event_names(events)

    asyncio.run(scenario())


def test_produce_run_stream_visible_phase_allows_text_and_keeps_tool_events(monkeypatch):
    chunks = [
        _tool_call_chunk(stream_phase="quarantine"),
        _ai_stream_chunk("最终回答", tags=["stream_phase:visible", "demo"]),
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks,
            final_messages=[AIMessage(content="最终回答。")],
        )
        event_names = _event_names(events)
        tool_payload = next(data for event, data in events if event == "tool.call.delta")
        message_delta_payload = next(data for event, data in events if event == "message.delta")

        assert "tool.call.delta" in event_names
        assert _message_deltas(events) == ["最终回答"]
        assert tool_payload["tool_call_id"] == "call-1"
        assert message_delta_payload["metadata"]["tags"] == ["demo"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "chunk_contents",
    [
        ("tool", 'calls/invoke namewebfetch">\nparameter name=""'),
        (
            "invoke",
            " name 2025 trends predictions multi-agent collaboration future</ | | DSML | | parameter>\n"
            "parameter name6</ | | DSML | | parameter>",
        ),
        ("< | | ", "DSML | | invoke nameweb_search"),
        (
            "<tool",
            '_c>\n<invoke="web_fetch">\n'
            '<parameterurl" string="true">https://vectorize.io/articles/best-ai-agent-memory-systems</parameter>',
        ),
        (
            'alls>\n="web_search">\n'
            '="query" string="true">AI agent predictions 2026\n'
            '="query"true">AI agent frameworks comparison 2026 pros cons LangChain CrewAI AutoGen\n'
            '="url"true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026\n'
            '="web_fetch="url" string="true">https://www.gartner.com/en/articles\n'
            '="max_chars" stringfalse">8000\n'
            '="max_chars"false">6000\n'
            "https://www.shrutigupta01.com/ai-agent-frameworks-in-2026/parameter>\n"
            "12000parameter>\n"
            '="max_fetch_length" stringfalse8000parameter>\n'
            "invoke>\n"
            '="read="filepath" string="true">tool-observation://webfetch/'
            "call00ljJOwoeUmsjmBzMNhkx8505\n"
            "</ | | DSML | | tool_calls",
        ),
        (
            "=",
            '"read=',
            '"filepath" string="true">tool-observation://webfetch/call00ljJOwoeUmsjmBzMNhkx8505',
        ),
        (
            '="url"',
            'true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026',
            '</｜｜DSML｜｜parameter>\n="max_chars"false">6000',
        ),
    ],
    ids=[
        "split-tool-protocol",
        "split-degraded-invoke",
        "split-dsml-prefix",
        "xmlish-tool-c",
        "orphaned-protocol-tail",
        "assignment-tail",
        "compacted-assignment-tail",
    ],
)
def test_produce_run_stream_drops_or_holds_protocol_stream_buffer(monkeypatch, chunk_contents):
    chunks = [_visible_ai_chunk(content) for content in chunk_contents]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[],
        )

        _assert_no_message_output(events)

    asyncio.run(scenario())


def test_produce_run_stream_drops_textual_tool_protocol_reasoning(monkeypatch):
    chunks = [
        _reasoning_delta_chunk('invoke name">\nparameter name="" string="true">direct'),
        _reasoning_delta_chunk("safe reasoning"),
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[AIMessage(content="最终安全回答。")],
        )
        assert _reasoning_deltas(events) == ["safe reasoning", ""]

    asyncio.run(scenario())


def test_produce_run_stream_drops_split_tool_protocol_reasoning(monkeypatch):
    chunks = [
        _reasoning_delta_chunk("tool"),
        _reasoning_delta_chunk('calls/invoke namewebfetch">\nparameter name=""'),
    ]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(
            monkeypatch,
            chunks=chunks,
            final_messages=[AIMessage(content="最终安全回答。")],
        )
        assert _reasoning_deltas(events) == []

    asyncio.run(scenario())


def test_produce_run_stream_emits_tool_call_delta_without_legacy_alias(monkeypatch):
    chunks = [_tool_call_chunk(name="search_web")]

    async def scenario():
        events, _statuses, _ended = await _collect_produced_events(monkeypatch, chunks)
        event_names = _event_names(events)
        tool_payload = next(data for event, data in events if event == "tool.call.delta")

        assert "tool_call.delta" not in event_names
        assert "message.delta" not in event_names
        assert tool_payload["tool_call_id"] == "call-1"
        assert tool_payload["name"] == "search_web"

    asyncio.run(scenario())


def test_produce_run_stream_accepts_custom_tool_payload_event_key(monkeypatch):
    chunks = [
        {
            "type": "custom",
            "data": {
                "event": "tool",
                "stage": "start",
                "tool_call_id": "call-1",
                "tool_name": "web_search",
                "source_node": "payload-source-should-not-override-canonical",
            },
            "ns": ["agent"],
        }
    ]

    async def scenario():
        events, statuses, ended = await _collect_produced_events(monkeypatch, chunks)
        event_names = [event for event, _data in events]
        tool_payload = next(data for event, data in events if event == "tool.requested")

        assert "run.failed" not in event_names
        assert tool_payload["event"] == "tool"
        assert tool_payload["tool_call_id"] == "call-1"
        assert tool_payload["tool_name"] == "web_search"
        assert tool_payload["source_node"] == "agent"
        assert statuses[-1][0] is RunStatus.SUCCESS
        assert ended is True

    asyncio.run(scenario())


def test_produce_run_stream_demotes_custom_tool_payload_without_call_id(monkeypatch):
    chunks = [
        {
            "type": "custom",
            "data": {
                "event": "tool",
                "stage": "start",
                "tool_name": "web_search",
            },
            "ns": ["agent"],
        }
    ]

    async def scenario():
        events, statuses, ended = await _collect_produced_events(monkeypatch, chunks)
        event_names = [event for event, _data in events]
        state_payload = next(
            data
            for event, data in events
            if event == "state.update" and data.get("event") == "tool"
        )

        assert "tool.requested" not in event_names
        assert state_payload["tool_name"] == "web_search"
        assert statuses[-1][0] is RunStatus.SUCCESS
        assert ended is True

    asyncio.run(scenario())


class _RecordingFailureChat(_ProducerChat):
    def __init__(self, final_messages):
        super().__init__(final_messages)
        self.trajectory_calls = []
        self.compaction_scheduled = False
        self.branch_refresh_scheduled = False

    def _safe_get_values(self, thread_id: str):
        assert thread_id == "thread-1"
        return {"messages": self.final_messages, "llm_calls": 2}

    def _record_turn_trajectory_best_effort(self, **kwargs):
        self.trajectory_calls.append(kwargs)

    def _schedule_post_turn_context_compaction(self, **kwargs):
        del kwargs
        self.compaction_scheduled = True

    def _schedule_branch_name_refresh_after_first_turn(self, **kwargs):
        del kwargs
        self.branch_refresh_scheduled = True


def test_produce_run_stream_records_failed_turn_trajectory_and_reports_run_failed(monkeypatch):
    async def scenario():
        chat = _RecordingFailureChat([AIMessage(content="partial failure answer")])
        events, statuses, ended = await _collect_produced_events(
            monkeypatch,
            [],
            error=RuntimeError("stream failed for test"),
            chat=chat,
        )
        by_name = {event: data for event, data in events}

        assert by_name["run.failed"] == {
            "run_id": "run-1",
            "thread_id": "thread-1",
            "turn_id": "run-1",
            "sequence": 3,
            "source_node": "harness",
            "error": "RuntimeError",
            "message": "stream failed for test",
            "thread_state": {
                "thread_id": "thread-1",
                "messages": [{"type": "ai", "content": "done"}],
            },
        }
        assert events[-1][0] == "run.closed"
        assert statuses[-1][0] is RunStatus.ERROR
        assert statuses[-1][1]["error"] == "stream failed for test"
        assert len(chat.trajectory_calls) == 1
        call = chat.trajectory_calls[0]
        assert call["status"] == "failed"
        assert call["kind"] == "chat.turn"
        assert call["thread_id"] == "thread-1"
        assert call["user_id"] == "user-1"
        assert call["root_thread_id"] == "root-1"
        assert call["error"] == "stream failed for test"
        assert call["final_values"]["messages"][0].content == "partial failure answer"
        assert call["input_messages"] == []
        assert chat.compaction_scheduled is False
        assert chat.branch_refresh_scheduled is False
        assert ended is True

    asyncio.run(scenario())


def test_produce_run_stream_treats_generator_close_race_as_interrupt(monkeypatch):
    async def scenario():
        events, statuses, ended = await _collect_produced_events(
            monkeypatch,
            [],
            error=ValueError("generator already executing"),
            abort_requested=True,
        )
        event_names = [event for event, _data in events]

        assert "run.failed" not in event_names
        assert events[-1][0] == "run.closed"
        assert statuses[-1][0] is RunStatus.INTERRUPTED
        assert ended is True

    asyncio.run(scenario())


def test_produce_run_stream_does_not_duplicate_manager_interrupt(monkeypatch):
    async def fake_stream_chunks(**kwargs):
        del kwargs
        raise asyncio.CancelledError
        yield  # pragma: no cover

    class _Harness:
        graph = object()

        async def stream_chunks(self, **kwargs):
            async for chunk in fake_stream_chunks(**kwargs):
                yield chunk

    class _Bridge:
        def __init__(self):
            self.events = []

        async def publish(self, run_id: str, event: str, data: dict):
            self.events.append((event, data))
            return SimpleNamespace(id=f"evt-{len(self.events)}", event=event, data=data)

        async def publish_end(self, run_id: str):
            self.ended = True

    class _Manager:
        def __init__(self):
            abort_event = asyncio.Event()
            abort_event.set()
            self.record = SimpleNamespace(abort_event=abort_event, abort_action="interrupt")
            self.statuses = []

        def get(self, run_id: str):
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            self.statuses.append((status, kwargs))

    async def scenario():
        bridge = _Bridge()
        runtime = SimpleNamespace(
            harness=_Harness(),
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            run_manager=_Manager(),
            stream_bridge=bridge,
        )

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        await harness_runs._produce_run_stream(
            runtime=runtime,
            chat=SimpleNamespace(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            payload={"messages": []},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
            request_id="request-1",
        )

        event_names = [event for event, _data in bridge.events]
        assert "run.failed" not in event_names
        assert event_names[-1] == "run.closed"
        assert "run.interrupt" not in event_names

    asyncio.run(scenario())


def test_produce_run_stream_keeps_closed_sequence_after_lifecycle_event(monkeypatch):
    async def fake_stream_chunks(**kwargs):
        del kwargs
        raise asyncio.CancelledError
        yield  # pragma: no cover

    class _Harness:
        graph = object()

        async def stream_chunks(self, **kwargs):
            async for chunk in fake_stream_chunks(**kwargs):
                yield chunk

    class _Manager:
        def __init__(self, bridge, journal):
            abort_event = asyncio.Event()
            abort_event.set()
            self.record = SimpleNamespace(abort_event=abort_event, abort_action="interrupt")
            self.bridge = bridge
            self.journal = journal
            self.published_interrupt = False

        def get(self, run_id: str):
            return self.record

        async def set_status(self, run_id: str, status: RunStatus, **kwargs):
            del kwargs
            if status is RunStatus.INTERRUPTED and not self.published_interrupt:
                self.published_interrupt = True
                sequence = await self.journal.count_events(run_id) + 1
                await self.bridge.publish(
                    run_id,
                    "run.interrupt",
                    harness_runs.canonical_event_payload(
                        run_id=run_id,
                        thread_id="thread-1",
                        turn_id=run_id,
                        sequence=sequence,
                        action="interrupt",
                    ),
                )

    async def scenario():
        journal = InMemoryRunJournal()
        await journal.put("run-1", thread_id="thread-1", status="running")
        bridge = JournaledStreamBridge(
            journal=journal,
            bridge=InMemoryStreamBridge(max_buffer_size=10),
        )
        runtime = SimpleNamespace(
            event_store=journal,
            harness=_Harness(),
            checkpointer=None,
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            stream_bridge=bridge,
        )
        runtime.run_manager = _Manager(bridge, journal)

        monkeypatch.setattr(harness_runs, "build_trace_correlation", lambda **kwargs: {})
        monkeypatch.setattr(harness_runs, "build_invoke_config", lambda **kwargs: {})

        await harness_runs._produce_run_stream(
            runtime=runtime,
            chat=SimpleNamespace(),
            run_id="run-1",
            thread_id="thread-1",
            user_id="user-1",
            payload={"messages": []},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta={"branch": "main"},
            initial_values={"messages": []},
            request_id="request-1",
        )

        events = await journal.list_events("run-1")
        assert [event.event for event in events] == [
            "run.metadata",
            "run.status",
            "run.interrupt",
            "run.closed",
        ]
        assert [event.data["sequence"] for event in events] == [1, 2, 3, 4]

    asyncio.run(scenario())
