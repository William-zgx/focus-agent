import asyncio
from types import SimpleNamespace

import pytest
from langgraph.types import Command

from focus_agent.api.routers.harness_runs import replay_helpers, replay_models
from focus_agent.api.routers.harness_runs.replay_execution import (
    _execute_harness_run,
    execute_harness_run_job,
)
from focus_agent.core.request_context import RequestContext
from focus_agent.harness.observability.postgres_run_journal import PostgresRunJournal
from focus_agent.harness.runtime import RunConflictError, RunManager, RunStatus


class _Harness:
    def __init__(self):
        self.calls = []

    def invoke(self, payload, **kwargs):
        self.calls.append((payload, kwargs))
        return {"messages": []}


class _RecoveryChat:
    def __init__(self, recommendation=None):
        self.recommendation = recommendation
        self.recommendation_calls = []
        self.recorded = []
        self.compaction = []
        self.refresh = []

    def _safe_get_values(self, thread_id):
        return {"messages": [], "llm_calls": 0}

    def _context_for_thread(self, thread_id, user_id):
        return None

    def _response_payload(self, **kwargs):
        return {"assistant_message": "recovered"}

    def _safe_get_interrupts(self, thread_id):
        return []

    def _handle_branch_recommendation_turn_with_lease(self, **kwargs):
        self.recommendation_calls.append(kwargs)
        return self.recommendation

    def _record_turn_trajectory_best_effort(self, **kwargs):
        self.recorded.append(kwargs)

    def _schedule_post_turn_context_compaction(self, **kwargs):
        self.compaction.append(kwargs)

    def _schedule_branch_name_refresh_after_first_turn(self, **kwargs):
        self.refresh.append(kwargs)


def _runtime(harness):
    manager = RunManager()
    return SimpleNamespace(settings=SimpleNamespace(), run_manager=manager, harness=harness)


def _create(runtime, thread_id, *, user_id, kwargs):
    return asyncio.run(runtime.run_manager.create(thread_id, user_id=user_id, kwargs=kwargs))


def test_create_run_record_persists_server_built_recovery_context():
    class Manager:
        async def create_or_reject(self, *args, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(run_id="run-1")

    async def scenario():
        manager = Manager()
        payload = replay_models.HarnessRunRequest(
            message="hello",
            config={"configurable": {"thread_id": "client-thread"}},
            context={"user_id": "client-user"},
            metadata={"external_outcome": "replay_safe"},
        )

        await replay_helpers._create_run_record(
            runtime=SimpleNamespace(run_manager=manager),
            payload=payload,
            thread_id="thread-1",
            user_id="user-1",
            graph_payload={"messages": []},
            context=RequestContext(user_id="user-1", root_thread_id="root-1"),
            request_id="request-1",
        )

        metadata = manager.kwargs["metadata"]
        persisted = manager.kwargs["kwargs"]
        assert metadata["external_outcome"] == "unknown"
        assert persisted["config"]["configurable"] == {
            "thread_id": "thread-1",
            "user_id": "user-1",
            "root_thread_id": "root-1",
        }
        assert persisted["config"]["metadata"]["request_id"] == "request-1"
        assert persisted["context"]["user_id"] == "user-1"
        assert persisted["context"]["root_thread_id"] == "root-1"

    asyncio.run(scenario())


def test_pending_hydrated_run_executes_original_graph_payload():
    harness = _Harness()
    runtime = _runtime(harness)
    record = _create(
        runtime, "thread-1", user_id="user-1", kwargs={"input": {"messages": ["hello"]}}
    )

    execute_harness_run_job(runtime=runtime, chat=None, payload={"run_id": record.run_id})

    assert len(harness.calls) == 1
    payload, kwargs = harness.calls[0]
    assert payload == {"messages": ["hello"]}
    assert kwargs["context"].root_thread_id == "thread-1"
    assert kwargs["context"].user_id == "user-1"
    assert kwargs["version"] == "v2"
    assert runtime.run_manager.get(record.run_id).status is RunStatus.SUCCESS


def test_post_invoke_response_failure_is_terminal_error_not_stuck_running():
    class Chat:
        def _safe_get_values(self, thread_id):
            return {"messages": [], "llm_calls": 0}

        def _context_for_thread(self, thread_id, user_id):
            return None

        def _response_payload(self, **kwargs):
            raise RuntimeError("response construction failed")

        def _safe_get_interrupts(self, thread_id):
            return []

        def _record_turn_trajectory_best_effort(self, **kwargs):
            self.recorded = kwargs

    harness = _Harness()
    chat = Chat()
    runtime = _runtime(harness)
    record = _create(runtime, "thread-1", user_id="user-1", kwargs={"input": {"messages": []}})

    async def scenario():
        with pytest.raises(RuntimeError, match="response construction failed"):
            await _execute_harness_run(
                runtime=runtime,
                chat=chat,
                run_record=record,
                thread_id="thread-1",
                user_id="user-1",
                message="hello",
                payload={"messages": []},
                request_id=None,
                context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
                branch_meta=None,
                initial_values={"messages": []},
                skip_branch_recommendation=True,
            )

        assert runtime.run_manager.get(record.run_id).status is RunStatus.ERROR
        assert chat.recorded["status"] == "failed"
        assert len(harness.calls) == 1

    asyncio.run(scenario())


def test_pending_command_resume_reconstructs_command_and_records_resume_kind():
    harness = _Harness()
    chat = _RecoveryChat()
    runtime = _runtime(harness)
    resume = {"approved": True, "comment": {"nested": [1, 2]}}

    record = asyncio.run(
        replay_helpers._create_run_record(
            runtime=runtime,
            payload=replay_models.HarnessResumeRequest(resume=resume),
            thread_id="thread-1",
            user_id="user-1",
            graph_payload=Command(resume=resume),
            context=RequestContext(user_id="user-1", root_thread_id="root-1"),
            kind="chat.resume",
            skip_branch_recommendation=True,
        )
    )

    assert record.kwargs["input"] == {"resume": resume}
    assert record.kwargs["input_kind"] == "langgraph.command.resume"
    assert record.kwargs["kind"] == "chat.resume"

    execute_harness_run_job(runtime=runtime, chat=chat, payload={"run_id": record.run_id})

    assert len(harness.calls) == 1
    graph_payload, kwargs = harness.calls[0]
    assert isinstance(graph_payload, Command)
    assert graph_payload.resume == resume
    assert kwargs["config"] == record.kwargs["config"]
    assert kwargs["context"].root_thread_id == "root-1"
    assert chat.recommendation_calls == []
    assert len(chat.recorded) == 1
    assert chat.recorded[0]["kind"] == "chat.resume"
    assert chat.recorded[0]["status"] == "succeeded"
    assert len(chat.compaction) == 1
    assert len(chat.refresh) == 1
    assert runtime.run_manager.get(record.run_id).status is RunStatus.SUCCESS


def test_pending_run_uses_pre_turn_recommendation_without_graph_invocation():
    harness = _Harness()
    chat = _RecoveryChat(
        recommendation={
            "message": "recommend a branch",
            "thread_state": {
                "assistant_message": "recommend a branch",
                "branch_actions": [],
            },
        }
    )
    runtime = _runtime(harness)
    record = _create(
        runtime,
        "thread-1",
        user_id="user-1",
        kwargs={
            "input": {"messages": [{"content": "should I branch?"}]},
            "context": {"user_id": "user-1", "root_thread_id": "root-1"},
            "kind": "chat.turn",
        },
    )

    execute_harness_run_job(runtime=runtime, chat=chat, payload={"run_id": record.run_id})

    assert harness.calls == []
    assert len(chat.recommendation_calls) == 1
    assert chat.recommendation_calls[0]["message"] == "should I branch?"
    assert len(chat.recorded) == 1
    assert chat.recorded[0]["kind"] == "chat.turn"
    assert chat.recorded[0]["status"] == "succeeded"
    assert chat.recorded[0]["answer"] == "recommend a branch"
    assert chat.compaction == []
    assert chat.refresh == []
    assert runtime.run_manager.get(record.run_id).status is RunStatus.SUCCESS


def test_recovered_failure_records_one_trajectory_without_success_side_effects():
    class FailingHarness(_Harness):
        def invoke(self, payload, **kwargs):
            self.calls.append((payload, kwargs))
            raise RuntimeError("recovered graph failed")

    harness = FailingHarness()
    chat = _RecoveryChat()
    runtime = _runtime(harness)
    record = _create(
        runtime,
        "thread-1",
        user_id="user-1",
        kwargs={
            "input": {"messages": [{"content": "hello"}]},
            "context": {"user_id": "user-1", "root_thread_id": "root-1"},
        },
    )

    with pytest.raises(RuntimeError, match="recovered graph failed"):
        execute_harness_run_job(
            runtime=runtime,
            chat=chat,
            payload={"run_id": record.run_id},
        )

    assert len(harness.calls) == 1
    assert len(chat.recorded) == 1
    assert chat.recorded[0]["kind"] == "chat.turn"
    assert chat.recorded[0]["status"] == "failed"
    assert chat.recorded[0]["error"] == "recovered graph failed"
    assert chat.compaction == []
    assert chat.refresh == []
    assert runtime.run_manager.get(record.run_id).status is RunStatus.ERROR


def test_closed_run_is_acknowledged_without_replay():
    harness = _Harness()
    runtime = _runtime(harness)
    record = _create(runtime, "thread-1", user_id="user-1", kwargs={"input": {"messages": []}})
    asyncio.run(runtime.run_manager.set_status(record.run_id, RunStatus.SUCCESS))

    execute_harness_run_job(runtime=runtime, chat=None, payload={"run_id": record.run_id})

    assert harness.calls == []
    assert runtime.run_manager.get(record.run_id).status is RunStatus.SUCCESS


def test_recovered_stream_publishes_terminal_events_and_end():
    class Chat:
        def _safe_get_values(self, thread_id):
            return {"messages": [], "llm_calls": 0, "task_outcome": {"status": "succeeded"}}

        def _context_for_thread(self, thread_id, user_id):
            return None

        def _response_payload(self, **kwargs):
            return {"assistant_message": "done"}

        def _safe_get_interrupts(self, thread_id):
            return []

        def _record_turn_trajectory_best_effort(self, **kwargs):
            return None

        def _schedule_post_turn_context_compaction(self, **kwargs):
            return None

        def _schedule_branch_name_refresh_after_first_turn(self, **kwargs):
            return None

    class Bridge:
        def __init__(self):
            self.events = []

        async def publish(self, run_id, event, data):
            self.events.append((event, data))

        async def publish_end(self, run_id):
            self.events.append(("__end__", {"run_id": run_id}))

    harness = _Harness()
    runtime = _runtime(harness)
    bridge = Bridge()
    runtime.stream_bridge = bridge
    record = _create(
        runtime,
        "thread-1",
        user_id="user-1",
        kwargs={
            "input": {"messages": ["hello"]},
            "stream": True,
            "skip_branch_recommendation": True,
        },
    )

    execute_harness_run_job(runtime=runtime, chat=Chat(), payload={"run_id": record.run_id})

    assert [event for event, _ in bridge.events] == ["run.completed", "run.closed", "__end__"]
    assert bridge.events[0][1]["thread_state"]["assistant_message"] == "done"
    assert runtime.run_manager.get(record.run_id).status is RunStatus.SUCCESS


def test_terminal_journal_run_is_acknowledged_when_manager_has_no_record():
    class EventStore:
        async def get_run(self, run_id):
            assert run_id == "run-terminal"
            return {"run_id": run_id, "status": "success"}

    harness = _Harness()
    runtime = _runtime(harness)
    runtime.event_store = EventStore()

    execute_harness_run_job(
        runtime=runtime,
        chat=None,
        payload={"run_id": "run-terminal"},
    )

    assert harness.calls == []


def test_pending_branch_action_run_uses_branch_action_executor():
    class Chat:
        def __init__(self):
            self.branch_calls = []
            self.recorded = None

        def _handle_branch_action_turn(self, **kwargs):
            self.branch_calls.append(kwargs)
            return {
                "message": "branch updated",
                "thread_state": {"assistant_message": "branch updated"},
            }

        def _safe_get_values(self, thread_id):
            return {"messages": [], "llm_calls": 0}

        def _context_for_thread(self, thread_id, user_id):
            return None

        def _record_turn_trajectory_best_effort(self, **kwargs):
            self.recorded = kwargs

    harness = _Harness()
    chat = Chat()
    runtime = _runtime(harness)
    record = _create(
        runtime,
        "thread-1",
        user_id="user-1",
        kwargs={
            "input": {"messages": [{"content": "merge this branch"}]},
            "branch_action": True,
            "context": {"user_id": "user-1", "root_thread_id": "thread-1"},
        },
    )

    execute_harness_run_job(runtime=runtime, chat=chat, payload={"run_id": record.run_id})

    assert harness.calls == []
    assert len(chat.branch_calls) == 1
    assert chat.branch_calls[0]["message"] == "merge this branch"
    assert chat.recorded["status"] == "succeeded"
    assert chat.recorded["answer"] == "branch updated"
    assert runtime.run_manager.get(record.run_id).status is RunStatus.SUCCESS


def test_reconciliation_required_run_does_not_execute():
    harness = _Harness()
    runtime = _runtime(harness)
    record = _create(runtime, "thread-1", user_id="user-1", kwargs={"input": {"messages": []}})
    asyncio.run(runtime.run_manager.set_status(record.run_id, RunStatus.RECONCILIATION_REQUIRED))

    with pytest.raises(RuntimeError, match="requires reconciliation"):
        execute_harness_run_job(runtime=runtime, chat=None, payload={"run_id": record.run_id})
    assert harness.calls == []


def test_running_unknown_outcome_is_not_replayed_after_lease_expiry():
    harness = _Harness()
    runtime = _runtime(harness)
    record = _create(runtime, "thread-1", user_id="user-1", kwargs={"input": {"messages": []}})
    record.metadata["external_outcome"] = "unknown"
    asyncio.run(runtime.run_manager.set_status(record.run_id, RunStatus.RUNNING))

    with pytest.raises(RuntimeError, match="outcome requires reconciliation"):
        execute_harness_run_job(runtime=runtime, chat=None, payload={"run_id": record.run_id})

    assert harness.calls == []


@pytest.mark.parametrize("outcome", ["replay_safe", "reconciled"])
def test_running_replay_safe_outcomes_can_execute(outcome):
    harness = _Harness()
    runtime = _runtime(harness)
    record = _create(runtime, "thread-1", user_id="user-1", kwargs={"input": {"messages": []}})
    record.metadata["external_outcome"] = outcome
    asyncio.run(runtime.run_manager.set_status(record.run_id, RunStatus.RUNNING))

    execute_harness_run_job(runtime=runtime, chat=None, payload={"run_id": record.run_id})

    assert len(harness.calls) == 1
    assert runtime.run_manager.get(record.run_id).status is RunStatus.SUCCESS


def test_active_run_does_not_execute_twice():
    harness = _Harness()
    runtime = _runtime(harness)
    record = _create(runtime, "thread-1", user_id="user-1", kwargs={"input": {"messages": []}})

    async def scenario():
        task = asyncio.create_task(asyncio.sleep(30))
        await runtime.run_manager.attach_task(record.run_id, task)
        with pytest.raises(RunConflictError, match="already active"):
            execute_harness_run_job(runtime=runtime, chat=None, payload={"run_id": record.run_id})
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert harness.calls == []


def test_recovery_preserves_original_config_and_turn_bookkeeping():
    class Chat:
        def __init__(self):
            self.values = {"messages": [], "llm_calls": 0}
            self.recorded = None
            self.compaction = None
            self.refresh = None

        def _safe_get_values(self, thread_id):
            return dict(self.values)

        def _context_for_thread(self, thread_id, user_id):
            return None

        def _response_payload(self, **kwargs):
            return {"assistant_message": "done"}

        def _safe_get_interrupts(self, thread_id):
            return []

        def _record_turn_trajectory_best_effort(self, **kwargs):
            self.recorded = kwargs

        def _schedule_post_turn_context_compaction(self, **kwargs):
            self.compaction = kwargs

        def _schedule_branch_name_refresh_after_first_turn(self, **kwargs):
            self.refresh = kwargs

    harness = _Harness()
    chat = Chat()
    runtime = _runtime(harness)
    original_config = {
        "configurable": {"thread_id": "parent-root", "checkpoint_id": "parent-checkpoint"}
    }
    original_context = {
        "root_thread_id": "parent-root",
        "user_id": "user-1",
        "branch_id": "child-1",
        "parent_thread_id": "parent-root",
        "branch_role": "deep_dive",
    }
    record = _create(
        runtime,
        "thread-1",
        user_id="user-1",
        kwargs={
            "input": {"messages": ["hello"]},
            "config": original_config,
            "context": original_context,
            "branch_meta": {"branch_id": "child-1", "branch_role": "deep_dive"},
        },
    )

    execute_harness_run_job(runtime=runtime, chat=chat, payload={"run_id": record.run_id})

    _, kwargs = harness.calls[0]
    assert kwargs["config"] is original_config
    assert kwargs["context"].root_thread_id == "parent-root"
    assert kwargs["context"].branch_id == "child-1"
    assert kwargs["context"].parent_thread_id == "parent-root"
    assert kwargs["context"].branch_role == "deep_dive"
    assert chat.recorded["status"] == "succeeded"
    assert chat.recorded["root_thread_id"] == "parent-root"
    assert chat.recorded["answer"] == "done"
    assert chat.compaction["thread_id"] == "thread-1"
    assert chat.refresh["thread_id"] == "thread-1"


def test_status_updates_use_the_run_manager_home_loop():
    async def scenario():
        harness = _Harness()
        runtime = _runtime(harness)
        record = await runtime.run_manager.create(
            "thread-1", user_id="user-1", kwargs={"input": {"messages": []}}
        )

        await asyncio.to_thread(
            execute_harness_run_job,
            runtime=runtime,
            chat=None,
            payload={"run_id": record.run_id},
        )

        assert runtime.run_manager.get(record.run_id).status is RunStatus.SUCCESS
        assert runtime.run_manager._loop is asyncio.get_running_loop()

    asyncio.run(scenario())


def test_completed_task_with_running_status_requires_reconciliation():
    harness = _Harness()
    runtime = _runtime(harness)
    record = _create(runtime, "thread-1", user_id="user-1", kwargs={"input": {"messages": []}})

    async def scenario():
        task = asyncio.create_task(asyncio.sleep(0))
        await runtime.run_manager.attach_task(record.run_id, task)
        await task
        await runtime.run_manager.set_status(record.run_id, RunStatus.RUNNING)
        with pytest.raises(RuntimeError, match="requires reconciliation"):
            execute_harness_run_job(runtime=runtime, chat=None, payload={"run_id": record.run_id})

    asyncio.run(scenario())
    assert harness.calls == []


def test_unknown_hydrated_run_fails_closed():
    with pytest.raises(KeyError, match="unknown hydrated harness run"):
        execute_harness_run_job(
            runtime=_runtime(_Harness()), chat=None, payload={"run_id": "missing"}
        )


def test_postgres_put_enqueues_harness_run_with_stable_idempotency_key():
    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, args=()):
            self.calls.append((sql, args))

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def cursor(self):
            return self.cursor_instance

    connection = Connection()
    journal = PostgresRunJournal("postgresql://test")

    async def run_db(operation):
        return operation(connection)

    journal._run_db = run_db

    asyncio.run(
        journal.put(
            "run-1",
            thread_id="thread-1",
            user_id="user-1",
            kwargs={"input": {"messages": []}, "checkpoint_id": "checkpoint-1"},
        )
    )

    assert len(connection.cursor_instance.calls) == 2
    sql, args = connection.cursor_instance.calls[1]
    assert "INSERT INTO focus_background_jobs" in sql
    assert args[0] == "harness_run:run-1"
    assert args[1] == "harness_run"
    payload = getattr(args[2], "obj", {})
    assert payload["run_id"] == "run-1"
    assert payload["external_outcome"] == "unknown"
    assert payload["checkpoint_id"] == "checkpoint-1"
    normalized_sql = " ".join(sql.split())
    assert "claimed_by, claimed_until, claim_token" in normalized_sql
    assert args[3] == "api"
    assert args[4] is not None
    assert isinstance(args[5], str) and args[5]
    assert args[5] != args[0]
    assert "idempotency_key" in normalized_sql
    assert args[-1] == args[0]
