from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from focus_agent.api.route_helpers import run_sync_route_call
from focus_agent.api.route_utils.branch_handoff_decisions import (
    ensure_branch_handoff_decision_from_journal,
)


def _wait_for_release(
    started: threading.Event,
    release: threading.Event,
    value: str,
) -> str:
    started.set()
    if not release.wait(timeout=2):
        raise TimeoutError("sync route call was not released")
    return value


async def _wait_until_started(started: threading.Event) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 1
    while not started.is_set():
        if loop.time() >= deadline:
            raise AssertionError("sync route call did not start")
        await asyncio.sleep(0.001)


def test_run_sync_route_call_does_not_block_event_loop() -> None:
    async def scenario() -> None:
        started = threading.Event()
        release = threading.Event()
        blocking = asyncio.create_task(
            run_sync_route_call(_wait_for_release, started, release, "done")
        )

        await _wait_until_started(started)
        assert await asyncio.sleep(0.01, result="tick") == "tick"
        assert not blocking.done()

        release.set()
        assert await blocking == "done"

    asyncio.run(scenario())


def test_branch_handoff_journal_helper_does_not_block_event_loop() -> None:
    class Service:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def list_decisions(self, **_kwargs):
            self.started.set()
            if not self.release.wait(timeout=2):
                raise TimeoutError("branch decision service was not released")
            return [SimpleNamespace(decision_id="decision-1")]

    async def scenario() -> None:
        service = Service()
        runtime = SimpleNamespace(branch_decision_service=service)
        blocking = asyncio.create_task(
            ensure_branch_handoff_decision_from_journal(
                runtime=runtime,
                thread_id="thread-1",
                user_id="user-1",
            )
        )

        await _wait_until_started(service.started)
        assert await asyncio.sleep(0.01, result="tick") == "tick"
        assert not blocking.done()

        service.release.set()
        assert (await blocking).decision_id == "decision-1"

    asyncio.run(scenario())


def test_thread_snapshot_route_does_not_block_event_loop() -> None:
    from focus_agent.api.routers.conversation_chat_context import get_thread_snapshot

    class Chat:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def get_thread_state(self, **_kwargs):
            _wait_for_release(self.started, self.release, "done")
            return {"thread_id": "thread-1"}

    async def scenario() -> None:
        chat = Chat()
        blocking = asyncio.create_task(
            get_thread_snapshot(
                thread_id="thread-1",
                request=SimpleNamespace(state=SimpleNamespace(request_id=None)),
                chat=chat,
                principal=SimpleNamespace(user_id="user-1"),
                runtime=SimpleNamespace(),
            )
        )

        await _wait_until_started(chat.started)
        assert await asyncio.sleep(0.01, result="tick") == "tick"
        assert not blocking.done()

        chat.release.set()
        try:
            await blocking
        except ValueError:  # Stub payload fails response validation; only the loop matters.
            pass

    asyncio.run(scenario())


def test_harness_run_routes_preflight_thread_access_off_event_loop() -> None:
    from fastapi import HTTPException

    from focus_agent.api.routers.harness_runs import detail, promote, replay_execution
    from focus_agent.api.routers.harness_runs import replay_streaming as streaming
    from focus_agent.api.routers.harness_runs.replay_models import (
        HarnessResumeRequest,
        HarnessRunCancelRequest,
        HarnessRunRequest,
    )

    class Chat:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()

        def _select_skills_for_message(self, *, message: str, explicit_skill_hints):
            return SimpleNamespace(skill_ids=(), stripped_message=message, prompt_mode=None)

        def _preflight_thread_access(self, **_kwargs):
            _wait_for_release(self.started, self.release, "done")
            raise PermissionError("denied")

    run_record = SimpleNamespace(to_dict=lambda: {"thread_id": "thread-1", "user_id": "user-1"})
    runtime = SimpleNamespace(
        run_manager=SimpleNamespace(get=lambda run_id: run_record),
        settings=SimpleNamespace(),
    )
    principal = SimpleNamespace(user_id="user-1")
    request = SimpleNamespace(state=SimpleNamespace(request_id=None), headers={})
    routes = {
        "create": lambda chat: replay_execution.create_harness_run(
            thread_id="thread-1",
            payload=HarnessRunRequest(message="hi"),
            request=request,
            runtime=runtime,
            chat=chat,
            principal=principal,
        ),
        "stream": lambda chat: streaming.stream_harness_run(
            thread_id="thread-1",
            payload=HarnessRunRequest(message="hi"),
            request=request,
            runtime=runtime,
            chat=chat,
            principal=principal,
        ),
        "resume": lambda chat: streaming.stream_harness_resume(
            thread_id="thread-1",
            payload=HarnessResumeRequest(resume="ok"),
            request=request,
            runtime=runtime,
            chat=chat,
            principal=principal,
        ),
        "cancel_thread": lambda chat: promote.cancel_thread_harness_runs(
            thread_id="thread-1",
            payload=HarnessRunCancelRequest(),
            runtime=runtime,
            chat=chat,
            principal=principal,
        ),
        "get_run": lambda chat: detail.get_harness_run(
            run_id="run-1", runtime=runtime, chat=chat, principal=principal
        ),
    }

    async def scenario(name: str) -> None:
        chat = Chat()
        blocking = asyncio.create_task(routes[name](chat))

        await _wait_until_started(chat.started)
        assert await asyncio.sleep(0.01, result="tick") == "tick"
        assert not blocking.done(), name

        chat.release.set()
        try:
            await blocking
        except HTTPException as exc:
            assert exc.status_code == 403, name
        else:
            raise AssertionError(f"{name} did not reject the denied thread")

    for name in routes:
        asyncio.run(scenario(name))
