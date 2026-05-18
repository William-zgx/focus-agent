from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from focus_agent.multi_agent.approval_queue import (
    InMemoryApprovalQueue,
    PostgresApprovalQueue,
)
from focus_agent.multi_agent.conflict_detector import MergeConflictDetector
from focus_agent.multi_agent.contracts import (
    AgentMessageType,
    ApprovalStatus,
    DAGTaskNode,
    LockMode,
    ResourceClaim,
)
from focus_agent.multi_agent.dag_scheduler import DAGScheduler
from focus_agent.multi_agent.errors import DAGValidationError, DeadlockDetected
from focus_agent.multi_agent.failure_handler import FailureHandler
from focus_agent.multi_agent.maintenance import (
    MultiAgentMaintenanceWorker,
    run_multi_agent_maintenance,
)
from focus_agent.multi_agent.message_bus import (
    InMemoryAgentMessageBus,
    PostgresAgentMessageBus,
    _channel_for_session,
)
from focus_agent.multi_agent.resource_lock import (
    InMemoryResourceLockManager,
    PostgresResourceLockManager,
)


class _FakeCursor:
    def __init__(self, responses: list[object] | None = None) -> None:
        self.responses = list(responses or [])
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[object]:
        if not self.responses:
            return []
        response = self.responses.pop(0)
        return list(response or [])

    def fetchone(self) -> object | None:
        if not self.responses:
            return None
        response = self.responses.pop(0)
        if isinstance(response, list):
            return response[0] if response else None
        return response


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


def test_dag_scheduler_allows_parallel_ready_tasks_without_resource_conflicts() -> None:
    nodes = [
        DAGTaskNode("design", "architect", (), (), 1, 0.0, 1),
        DAGTaskNode("backend", "backend", ("design",), ("file:src/api.py",), 2, 0.0, 1),
        DAGTaskNode("frontend", "frontend", ("design",), ("file:apps/app.tsx",), 3, 0.0, 1),
        DAGTaskNode("review", "reviewer", ("backend", "frontend"), (), 4, 0.0, 1),
    ]

    wave = DAGScheduler(nodes, max_parallel_runs=2).compute_next_wave(
        completed={"design"},
        failed=set(),
        in_progress=set(),
    )

    assert [task.task_id for task in wave] == ["backend", "frontend"]


def test_dag_scheduler_skips_resource_conflicts_in_same_wave() -> None:
    nodes = [
        DAGTaskNode("a", "backend", (), ("file:src/shared.py",), 1, 0.0, 1),
        DAGTaskNode("b", "backend", (), ("file:src/shared.py",), 2, 0.0, 1),
    ]

    wave = DAGScheduler(nodes, max_parallel_runs=2).compute_next_wave(
        completed=set(),
        failed=set(),
        in_progress=set(),
    )

    assert [task.task_id for task in wave] == ["a"]


def test_dag_scheduler_rejects_cycles() -> None:
    with pytest.raises(DAGValidationError):
        DAGScheduler(
            [
                DAGTaskNode("a", "backend", ("b",), (), 1, 0.0, 1),
                DAGTaskNode("b", "backend", ("a",), (), 2, 0.0, 1),
            ]
        )


@pytest.mark.parametrize(
    ("completed", "failed", "in_progress", "max_parallel", "expected"),
    [
        (set(), set(), set(), 1, ["design"]),
        (set(), set(), set(), 3, ["design", "docs"]),
        ({"design", "docs"}, set(), set(), 1, ["backend"]),
        ({"design", "docs"}, set(), set(), 2, ["backend", "frontend"]),
        ({"design", "docs"}, set(), {"backend"}, 2, ["frontend"]),
        ({"design", "docs"}, {"backend"}, set(), 3, ["frontend"]),
        ({"design", "docs", "backend"}, set(), set(), 3, ["frontend"]),
        ({"design", "docs", "frontend"}, set(), set(), 3, ["backend"]),
        ({"design", "docs", "backend", "frontend"}, set(), set(), 3, ["verify"]),
        ({"design", "docs", "backend", "frontend", "verify"}, set(), set(), 3, ["review"]),
        ({"design", "docs"}, set(), set(), 4, ["backend", "frontend"]),
        ({"docs"}, set(), set(), 2, ["design"]),
        ({"design", "docs"}, set(), set(), 2, ["backend", "frontend"]),
        ({"design", "docs", "backend", "frontend"}, {"verify"}, set(), 3, []),
        ({"design", "backend", "frontend", "verify", "review", "docs"}, set(), set(), 3, []),
    ],
)
def test_dag_scheduler_wave_matrix(
    completed: set[str],
    failed: set[str],
    in_progress: set[str],
    max_parallel: int,
    expected: list[str],
) -> None:
    nodes = [
        DAGTaskNode("design", "architect", (), (), 1, 0.0, 1),
        DAGTaskNode("docs", "writer", (), ("file:docs/plan.md",), 2, 0.0, 1),
        DAGTaskNode("backend", "backend", ("design",), ("file:src/api.py",), 3, 0.0, 1),
        DAGTaskNode("frontend", "frontend", ("design",), ("file:apps/app.tsx",), 4, 0.0, 1),
        DAGTaskNode("verify", "verifier", ("backend", "frontend"), ("tool:pytest",), 5, 0.0, 1),
        DAGTaskNode("review", "reviewer", ("verify",), (), 6, 0.0, 1),
    ]

    wave = DAGScheduler(nodes, max_parallel_runs=max_parallel).compute_next_wave(
        completed=completed,
        failed=failed,
        in_progress=in_progress,
    )

    assert [task.task_id for task in wave] == expected


@pytest.mark.parametrize(
    "nodes",
    [
        [DAGTaskNode("a", "backend", ("missing",), (), 1, 0.0, 1)],
        [
            DAGTaskNode("a", "backend", ("b",), (), 1, 0.0, 1),
            DAGTaskNode("b", "backend", ("c",), (), 2, 0.0, 1),
            DAGTaskNode("c", "backend", ("a",), (), 3, 0.0, 1),
        ],
        [
            DAGTaskNode("root", "planner", (), (), 1, 0.0, 1),
            DAGTaskNode("a", "backend", ("b",), (), 2, 0.0, 1),
            DAGTaskNode("b", "backend", ("a",), (), 3, 0.0, 1),
        ],
    ],
)
def test_dag_scheduler_rejects_invalid_graph_matrix(nodes: list[DAGTaskNode]) -> None:
    with pytest.raises(DAGValidationError):
        DAGScheduler(nodes)


def test_resource_lock_shared_and_exclusive_modes() -> None:
    manager = InMemoryResourceLockManager()
    first = manager.try_acquire(
        resource_id="file:src/a.py",
        agent_id="backend:1",
        session_id="s1",
        mode=LockMode.SHARED,
        ttl_seconds=30,
    )
    second = manager.try_acquire(
        resource_id="file:src/a.py",
        agent_id="reviewer:1",
        session_id="s1",
        mode=LockMode.SHARED,
        ttl_seconds=30,
    )
    blocked = manager.try_acquire(
        resource_id="file:src/a.py",
        agent_id="backend:2",
        session_id="s1",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=30,
    )

    assert first is not None
    assert second is not None
    assert blocked is None


def test_resource_lock_detects_simple_deadlock() -> None:
    manager = InMemoryResourceLockManager()
    claim_a = manager.try_acquire(
        resource_id="file:a",
        agent_id="a",
        session_id="s1",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=30,
    )
    claim_b = manager.try_acquire(
        resource_id="file:b",
        agent_id="b",
        session_id="s1",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=30,
    )
    assert claim_a is not None
    assert claim_b is not None
    assert manager.try_acquire(
        resource_id="file:b",
        agent_id="a",
        session_id="s1",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=30,
    ) is None
    with pytest.raises(DeadlockDetected):
        manager.try_acquire(
            resource_id="file:a",
            agent_id="b",
            session_id="s1",
            mode=LockMode.EXCLUSIVE,
            ttl_seconds=30,
        )


def test_resource_lock_cleanup_expired_releases_claims_and_wait_edges() -> None:
    manager = InMemoryResourceLockManager()
    claim = manager.try_acquire(
        resource_id="file:a",
        agent_id="a",
        session_id="s1",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=0.001,
    )
    assert claim is not None
    time.sleep(0.01)

    assert manager.cleanup_expired() == 1
    assert manager.list_active_claims() == []
    assert manager.detect_deadlocks() == []


@pytest.mark.parametrize(
    ("held_mode", "requested_mode", "same_agent", "same_session", "expected_acquired"),
    [
        (LockMode.SHARED, LockMode.SHARED, False, True, True),
        (LockMode.SHARED, LockMode.EXCLUSIVE, False, True, False),
        (LockMode.EXCLUSIVE, LockMode.SHARED, False, True, False),
        (LockMode.EXCLUSIVE, LockMode.EXCLUSIVE, False, True, False),
        (LockMode.SHARED, LockMode.EXCLUSIVE, True, True, True),
        (LockMode.EXCLUSIVE, LockMode.EXCLUSIVE, True, True, True),
        (LockMode.EXCLUSIVE, LockMode.EXCLUSIVE, False, False, True),
        (LockMode.SHARED, LockMode.EXCLUSIVE, False, False, True),
        (LockMode.EXCLUSIVE, LockMode.SHARED, False, False, True),
        (LockMode.SHARED, LockMode.SHARED, True, True, True),
    ],
)
def test_resource_lock_conflict_matrix(
    held_mode: LockMode,
    requested_mode: LockMode,
    same_agent: bool,
    same_session: bool,
    expected_acquired: bool,
) -> None:
    manager = InMemoryResourceLockManager()
    first = manager.try_acquire(
        resource_id="file:src/shared.py",
        agent_id="agent:a",
        session_id="session:a",
        mode=held_mode,
        ttl_seconds=30,
    )
    assert first is not None

    second = manager.try_acquire(
        resource_id="file:src/shared.py",
        agent_id="agent:a" if same_agent else "agent:b",
        session_id="session:a" if same_session else "session:b",
        mode=requested_mode,
        ttl_seconds=30,
    )

    assert (second is not None) is expected_acquired


@pytest.mark.parametrize("resource_id", ["", "src/file.py", "file", "   ", "tool"])
def test_resource_lock_rejects_invalid_resource_ids(resource_id: str) -> None:
    manager = InMemoryResourceLockManager()

    with pytest.raises(ValueError):
        manager.try_acquire(
            resource_id=resource_id,
            agent_id="agent:a",
            session_id="session:a",
            mode=LockMode.EXCLUSIVE,
            ttl_seconds=30,
        )


@pytest.mark.parametrize(
    ("agent_id", "session_id"),
    [("", "session:a"), ("agent:a", ""), ("   ", "session:a"), ("agent:a", "   ")],
)
def test_resource_lock_requires_agent_and_session(agent_id: str, session_id: str) -> None:
    manager = InMemoryResourceLockManager()

    with pytest.raises(ValueError):
        manager.try_acquire(
            resource_id="file:src/shared.py",
            agent_id=agent_id,
            session_id=session_id,
            mode=LockMode.EXCLUSIVE,
            ttl_seconds=30,
        )


@pytest.mark.parametrize("mode", [LockMode.SHARED, LockMode.EXCLUSIVE])
def test_resource_lock_release_allows_new_claim(mode: LockMode) -> None:
    manager = InMemoryResourceLockManager()
    first = manager.try_acquire(
        resource_id="file:src/shared.py",
        agent_id="agent:a",
        session_id="session:a",
        mode=mode,
        ttl_seconds=30,
    )
    assert first is not None

    manager.release(first)
    second = manager.try_acquire(
        resource_id="file:src/shared.py",
        agent_id="agent:b",
        session_id="session:a",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=30,
    )

    assert second is not None


@pytest.mark.parametrize("ttl_seconds", [0, -1, 0.001, 30])
def test_resource_lock_heartbeat_extends_only_live_claims(ttl_seconds: float) -> None:
    manager = InMemoryResourceLockManager()
    claim = manager.try_acquire(
        resource_id="file:src/shared.py",
        agent_id="agent:a",
        session_id="session:a",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=30,
    )
    assert claim is not None

    assert manager.heartbeat(claim, ttl_seconds=ttl_seconds) is True


def test_postgres_resource_lock_acquire_heartbeat_release_and_cleanup() -> None:
    cursor = _FakeCursor([[], [{"claim_id": "c1"}], [{"claim_id": "expired"}]])
    manager = PostgresResourceLockManager("postgresql://unit-test")
    manager._connect = lambda: _FakeConn(cursor)  # type: ignore[method-assign]

    claim = manager.try_acquire(
        resource_id="file:src/shared.py",
        agent_id="agent:a",
        session_id="session:a",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=30,
    )
    assert claim is not None
    live = manager.heartbeat(claim, ttl_seconds=30)
    manager.release(claim)
    expired = manager.cleanup_expired()

    assert claim.resource_id == "file:src/shared.py"
    assert live is True
    assert expired == 1
    assert "INSERT INTO agent_resource_claims" in cursor.executed[2][0]
    assert "UPDATE agent_resource_claims" in cursor.executed[4][0]


def test_postgres_resource_lock_returns_none_on_conflict() -> None:
    cursor = _FakeCursor([[{"claim_id": "held", "lock_mode": LockMode.EXCLUSIVE.value}]])
    manager = PostgresResourceLockManager("postgresql://unit-test")
    manager._connect = lambda: _FakeConn(cursor)  # type: ignore[method-assign]

    claim = manager.try_acquire(
        resource_id="file:src/shared.py",
        agent_id="agent:b",
        session_id="session:a",
        mode=LockMode.SHARED,
        ttl_seconds=30,
    )

    assert claim is None


def test_postgres_resource_lock_lists_claims_and_detects_no_database_deadlock() -> None:
    expires = datetime.now(UTC) + timedelta(seconds=30)
    cursor = _FakeCursor(
        [
            [
                {
                    "claim_id": "c1",
                    "resource_id": "file:src/shared.py",
                    "agent_id": "agent:a",
                    "session_id": "session:a",
                    "lock_mode": LockMode.SHARED.value,
                    "expires_at": expires,
                }
            ],
            [],
        ]
    )
    manager = PostgresResourceLockManager("postgresql://unit-test")
    manager._connect = lambda: _FakeConn(cursor)  # type: ignore[method-assign]

    claims = manager.list_active_claims()
    deadlocks = manager.detect_deadlocks()

    assert claims == [
        ResourceClaim(
            claim_id="c1",
            resource_id="file:src/shared.py",
            agent_id="agent:a",
            session_id="session:a",
            mode=LockMode.SHARED,
            expires_at=expires.timestamp(),
        )
    ]
    assert deadlocks == []


def test_message_bus_filters_acks_and_expired_messages() -> None:
    bus = InMemoryAgentMessageBus(default_ttl_seconds=0.01)
    delivered_id = bus.publish(
        session_id="s1",
        source_agent="planner:1",
        target_agent="executor:1",
        message_type=AgentMessageType.PROGRESS,
        payload={"step": "start"},
    )
    stream = bus.subscribe(session_id="s1", agent_id="executor:1")
    assert [message.message_id for message in stream.poll()] == [delivered_id]
    stream.ack(delivered_id)
    assert stream.poll() == []

    bus.publish(
        session_id="s1",
        source_agent="planner:1",
        target_agent="executor:1",
        message_type=AgentMessageType.PROGRESS,
        payload={},
    )
    time.sleep(0.02)
    assert stream.poll() == []


def test_message_bus_cleanup_expired_reports_removed_count() -> None:
    bus = InMemoryAgentMessageBus(default_ttl_seconds=0.001)
    bus.publish(
        session_id="s1",
        source_agent="planner:1",
        target_agent=None,
        message_type=AgentMessageType.PROGRESS,
        payload={},
    )
    time.sleep(0.01)

    assert bus.cleanup_expired() == 1
    assert bus.subscribe(session_id="s1", agent_id="any").poll() == []


@pytest.mark.parametrize(
    ("target_agent", "subscriber", "expected_count"),
    [
        (None, "agent:a", 1),
        (None, "agent:b", 1),
        ("agent:a", "agent:a", 1),
        ("agent:a", "agent:b", 0),
        ("agent:b", "agent:a", 0),
        ("agent:b", "agent:b", 1),
    ],
)
def test_message_bus_routing_matrix(
    target_agent: str | None,
    subscriber: str,
    expected_count: int,
) -> None:
    bus = InMemoryAgentMessageBus(default_ttl_seconds=30)
    bus.publish(
        session_id="session:a",
        source_agent="source:1",
        target_agent=target_agent,
        message_type=AgentMessageType.PROGRESS,
        payload={"ok": True},
    )

    messages = bus.subscribe(session_id="session:a", agent_id=subscriber).poll()

    assert len(messages) == expected_count


@pytest.mark.parametrize(
    ("message_type", "should_expire"),
    [
        (AgentMessageType.PROGRESS, True),
        (AgentMessageType.CHECKPOINT, True),
        (AgentMessageType.HELP_REQUEST, True),
        (AgentMessageType.CONFLICT_ALERT, True),
        (AgentMessageType.DIRECTIVE, False),
    ],
)
def test_message_bus_ttl_matrix(message_type: AgentMessageType, should_expire: bool) -> None:
    bus = InMemoryAgentMessageBus(default_ttl_seconds=0.001)
    bus.publish(
        session_id="session:a",
        source_agent="source:1",
        target_agent="agent:a",
        message_type=message_type,
        payload={},
    )
    time.sleep(0.01)

    assert bus.cleanup_expired() == (1 if should_expire else 0)


@pytest.mark.parametrize("message_type", list(AgentMessageType))
def test_message_bus_ack_hides_message_type(message_type: AgentMessageType) -> None:
    bus = InMemoryAgentMessageBus(default_ttl_seconds=30)
    message_id = bus.publish(
        session_id="session:a",
        source_agent="source:1",
        target_agent="agent:a",
        message_type=message_type,
        payload={},
    )
    stream = bus.subscribe(session_id="session:a", agent_id="agent:a")

    stream.ack(message_id)

    assert stream.poll() == []


def test_postgres_message_bus_publish_uses_session_notify_channel() -> None:
    cursor = _FakeCursor()
    bus = PostgresAgentMessageBus("postgresql://unit-test")
    bus._connect = lambda: _FakeConn(cursor)  # type: ignore[method-assign]

    message_id = bus.publish(
        session_id="session:a",
        source_agent="source:1",
        target_agent="agent:a",
        message_type=AgentMessageType.PROGRESS,
        payload={"ok": True},
    )

    assert message_id
    assert "INSERT INTO agent_messages" in cursor.executed[0][0]
    assert cursor.executed[1][0] == "SELECT pg_notify(%s, %s)"
    assert cursor.executed[1][1] == (_channel_for_session("session:a"), message_id)


def test_postgres_message_bus_poll_ack_and_cleanup() -> None:
    created = datetime.now(UTC)
    expires = created + timedelta(seconds=30)
    cursor = _FakeCursor(
        [
            [
                {
                    "message_id": "m1",
                    "session_id": "s1",
                    "source_agent": "planner:1",
                    "target_agent": None,
                    "message_type": AgentMessageType.DIRECTIVE.value,
                    "payload": {"step": "go"},
                    "created_at": created,
                    "expires_at": expires,
                    "acked_at": None,
                }
            ],
            [{"message_id": "expired"}],
        ]
    )
    bus = PostgresAgentMessageBus("postgresql://unit-test")
    bus._connect = lambda: _FakeConn(cursor)  # type: ignore[method-assign]
    stream = bus.subscribe(session_id="s1", agent_id="agent:a")

    messages = stream.poll()
    stream.ack("m1")
    removed = bus.cleanup_expired()

    assert messages[0].message_id == "m1"
    assert messages[0].message_type == AgentMessageType.DIRECTIVE
    assert messages[0].payload == {"step": "go"}
    assert "UPDATE agent_messages" in cursor.executed[2][0]
    assert removed == 1


@pytest.mark.parametrize(
    ("session_id", "expected_prefix"),
    [
        ("plain_session", "agent_msg_plain_session"),
        ("session:with/slashes", "agent_msg_session_with_slashes"),
        ("x" * 100, "agent_msg_"),
    ],
)
def test_postgres_message_channel_names_are_valid(session_id: str, expected_prefix: str) -> None:
    channel = _channel_for_session(session_id)

    assert channel.startswith(expected_prefix)
    assert len(channel) <= 63


def test_failure_handler_progresses_to_degrade() -> None:
    handler = FailureHandler(retry_attempts=1, reassign_attempts=2)

    assert handler.decide(task_id="t1", error_category="timeout", attempt=1).value == "retry"
    assert handler.decide(task_id="t1", error_category="timeout", attempt=2).value == "reassign"
    assert handler.decide(task_id="t1", error_category="timeout", attempt=3).value == "degrade"


@pytest.mark.parametrize(
    ("retry_attempts", "reassign_attempts", "error_category", "attempt", "expected"),
    [
        (0, 0, "timeout", 1, "degrade"),
        (1, 2, "timeout", 1, "retry"),
        (1, 2, "timeout", 2, "reassign"),
        (1, 2, "timeout", 3, "degrade"),
        (1, 2, "unknown", 3, "escalate"),
        (2, 4, "tool_error", 1, "retry"),
        (2, 4, "tool_error", 2, "retry"),
        (2, 4, "tool_error", 3, "reassign"),
        (2, 4, "tool_error", 4, "reassign"),
        (2, 4, "tool_error", 5, "degrade"),
        (2, 4, "model_error", 5, "degrade"),
        (2, 4, "execution_error", 5, "degrade"),
        (2, 4, "permission_denied", 5, "escalate"),
        (1, 1, "timeout", 2, "degrade"),
        (1, 1, "network", 2, "escalate"),
        (3, 2, "timeout", 1, "retry"),
        (3, 2, "timeout", 3, "retry"),
        (3, 2, "timeout", 4, "degrade"),
        (0, 2, "timeout", 1, "reassign"),
        (0, 2, "timeout", 3, "degrade"),
    ],
)
def test_failure_handler_strategy_matrix(
    retry_attempts: int,
    reassign_attempts: int,
    error_category: str,
    attempt: int,
    expected: str,
) -> None:
    handler = FailureHandler(retry_attempts=retry_attempts, reassign_attempts=reassign_attempts)

    assert handler.decide(task_id="task-1", error_category=error_category, attempt=attempt).value == expected


@pytest.mark.parametrize("task_id", ["", " ", "\t"])
def test_failure_handler_requires_task_id(task_id: str) -> None:
    with pytest.raises(ValueError):
        FailureHandler().decide(task_id=task_id, error_category="timeout", attempt=1)


def test_approval_queue_auto_approves_low_risk() -> None:
    queue = InMemoryApprovalQueue(auto_approve_low_risk=True)

    status = asyncio.run(
        queue.submit_and_wait(
            request_id="r1",
            session_id="s1",
            agent_id="a1",
            tool_name="read",
            tool_args={"path": "README.md"},
            risk_level="low",
            timeout_seconds=1,
        )
    )

    assert status == ApprovalStatus.AUTO_APPROVED
    assert queue.get("r1").status == ApprovalStatus.AUTO_APPROVED


def test_approval_queue_expire_pending_marks_timed_out() -> None:
    queue = InMemoryApprovalQueue()
    queue.submit_pending(
        request_id="r1",
        session_id="s1",
        agent_id="a1",
        tool_name="write",
        tool_args={"path": "src/a.py"},
        risk_level="high",
        timeout_seconds=0.001,
    )
    time.sleep(0.01)

    assert queue.expire_pending() == 1
    assert queue.get("r1").status == ApprovalStatus.TIMED_OUT
    assert queue.list_pending() == []


@pytest.mark.parametrize(
    ("approved", "expected_status"),
    [(True, ApprovalStatus.APPROVED), (False, ApprovalStatus.REJECTED)],
)
def test_approval_queue_decision_matrix(approved: bool, expected_status: ApprovalStatus) -> None:
    queue = InMemoryApprovalQueue()
    queue.submit_pending(
        request_id="r1",
        session_id="s1",
        agent_id="a1",
        tool_name="write",
        tool_args={},
        risk_level="high",
        timeout_seconds=30,
    )

    queue.decide(request_id="r1", approved=approved, decided_by="reviewer")

    request = queue.get("r1")
    assert request is not None
    assert request.status == expected_status
    assert request.decided_by == "reviewer"
    assert queue.list_pending() == []


@pytest.mark.parametrize(
    ("risk_level", "auto_approve", "expected_status"),
    [
        ("low", True, ApprovalStatus.AUTO_APPROVED),
        ("medium", True, ApprovalStatus.TIMED_OUT),
        ("high", True, ApprovalStatus.TIMED_OUT),
        ("critical", True, ApprovalStatus.TIMED_OUT),
        ("low", False, ApprovalStatus.TIMED_OUT),
        ("", True, ApprovalStatus.AUTO_APPROVED),
    ],
)
def test_approval_queue_auto_approve_matrix(
    risk_level: str,
    auto_approve: bool,
    expected_status: ApprovalStatus,
) -> None:
    queue = InMemoryApprovalQueue(auto_approve_low_risk=auto_approve)

    status = asyncio.run(
        queue.submit_and_wait(
            request_id="r1",
            session_id="s1",
            agent_id="a1",
            tool_name="read",
            tool_args={},
            risk_level=risk_level,
            timeout_seconds=0.001,
        )
    )

    assert status == expected_status


@pytest.mark.parametrize("timeout_seconds", [0, -1, 0.001])
def test_approval_queue_pending_timeout_floor(timeout_seconds: float) -> None:
    queue = InMemoryApprovalQueue()

    status = asyncio.run(
        queue.submit_and_wait(
            request_id="r1",
            session_id="s1",
            agent_id="a1",
            tool_name="write",
            tool_args={},
            risk_level="high",
            timeout_seconds=timeout_seconds,
        )
    )

    assert status == ApprovalStatus.TIMED_OUT


def test_postgres_approval_queue_reads_and_decides_pending_requests() -> None:
    created = datetime.now(UTC)
    timeout = created + timedelta(seconds=30)
    cursor = _FakeCursor(
        [
            {
                "request_id": "r1",
                "session_id": "s1",
                "agent_id": "agent:a",
                "tool_name": "write_file",
                "tool_args": {"path": "src/a.py"},
                "risk_level": "high",
                "status": ApprovalStatus.PENDING.value,
                "created_at": created,
                "timeout_at": timeout,
                "decided_by": None,
            },
            [{"request_id": "r1"}],
        ]
    )
    queue = PostgresApprovalQueue("postgresql://unit-test")
    queue._connect = lambda: _FakeConn(cursor)  # type: ignore[method-assign]

    request = queue.get("r1")
    queue.decide(request_id="r1", approved=True, decided_by="reviewer")
    expired = queue.expire_pending()

    assert request is not None
    assert request.tool_args == {"path": "src/a.py"}
    assert request.status == ApprovalStatus.PENDING
    assert "UPDATE tool_approval_requests" in cursor.executed[1][0]
    assert expired == 1


def test_postgres_approval_queue_submit_pending_returns_stored_request() -> None:
    created = datetime.now(UTC)
    timeout = created + timedelta(seconds=30)
    queue = PostgresApprovalQueue("postgresql://unit-test")
    request_row = {
        "request_id": "r2",
        "session_id": "s1",
        "agent_id": "agent:a",
        "tool_name": "shell",
        "tool_args": {"cmd": "pytest"},
        "risk_level": "medium",
        "status": ApprovalStatus.PENDING.value,
        "created_at": created,
        "timeout_at": timeout,
        "decided_by": None,
    }
    cursors = [_FakeCursor(), _FakeCursor([request_row])]
    queue._connect = lambda: _FakeConn(cursors.pop(0))  # type: ignore[method-assign]

    request = queue.submit_pending(
        request_id="r2",
        session_id="s1",
        agent_id="agent:a",
        tool_name="shell",
        tool_args={"cmd": "pytest"},
        risk_level="medium",
        timeout_seconds=30,
    )

    assert request.request_id == "r2"
    assert request.risk_level == "medium"


def test_postgres_approval_queue_list_pending_uses_timeout_filter() -> None:
    created = datetime.now(UTC)
    timeout = created + timedelta(seconds=30)
    queue = PostgresApprovalQueue("postgresql://unit-test")
    request_row = {
        "request_id": "r3",
        "session_id": "s1",
        "agent_id": "agent:a",
        "tool_name": "shell",
        "tool_args": {},
        "risk_level": "high",
        "status": ApprovalStatus.PENDING.value,
        "created_at": created,
        "timeout_at": timeout,
        "decided_by": None,
    }
    cursors = [_FakeCursor([[]]), _FakeCursor([[request_row]])]
    queue._connect = lambda: _FakeConn(cursors.pop(0))  # type: ignore[method-assign]

    pending = queue.list_pending()

    assert [request.request_id for request in pending] == ["r3"]


def test_multi_agent_maintenance_runs_optional_cleanup_hooks() -> None:
    locks = InMemoryResourceLockManager()
    bus = InMemoryAgentMessageBus(default_ttl_seconds=0.001)
    approvals = InMemoryApprovalQueue()
    locks.try_acquire(
        resource_id="file:a",
        agent_id="a",
        session_id="s1",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=0.001,
    )
    bus.publish(
        session_id="s1",
        source_agent="a",
        target_agent=None,
        message_type=AgentMessageType.PROGRESS,
        payload={},
    )
    approvals.submit_pending(
        request_id="r1",
        session_id="s1",
        agent_id="a",
        tool_name="write",
        tool_args={},
        risk_level="high",
        timeout_seconds=0.001,
    )
    time.sleep(0.01)

    report = run_multi_agent_maintenance(
        SimpleNamespace(resource_locks=locks, message_bus=bus, approval_queue=approvals)
    )

    assert report == {
        "expired_locks": 1,
        "expired_messages": 1,
        "timed_out_approvals": 1,
        "deadlocks": [],
    }


def test_multi_agent_maintenance_worker_respects_intervals_and_force() -> None:
    locks = InMemoryResourceLockManager()
    bus = InMemoryAgentMessageBus(default_ttl_seconds=0.001)
    approvals = InMemoryApprovalQueue()
    worker = MultiAgentMaintenanceWorker(
        SimpleNamespace(resource_locks=locks, message_bus=bus, approval_queue=approvals),
        lock_cleanup_interval_seconds=60,
        message_cleanup_interval_seconds=60,
        approval_timeout_interval_seconds=60,
        deadlock_detection_interval_seconds=60,
    )
    locks.try_acquire(
        resource_id="file:a",
        agent_id="a",
        session_id="s1",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=0.001,
    )
    bus.publish(
        session_id="s1",
        source_agent="a",
        target_agent=None,
        message_type=AgentMessageType.PROGRESS,
        payload={},
    )
    approvals.submit_pending(
        request_id="r1",
        session_id="s1",
        agent_id="a",
        tool_name="write",
        tool_args={},
        risk_level="high",
        timeout_seconds=0.001,
    )
    time.sleep(0.01)

    first = worker.run_once()
    second = worker.run_once()
    forced = worker.run_once(force=True)

    assert first["expired_locks"] == 1
    assert first["expired_messages"] == 1
    assert first["timed_out_approvals"] == 1
    assert second == {
        "expired_locks": 0,
        "expired_messages": 0,
        "timed_out_approvals": 0,
        "deadlocks": [],
    }
    assert forced == {
        "expired_locks": 0,
        "expired_messages": 0,
        "timed_out_approvals": 0,
        "deadlocks": [],
    }


def test_conflict_detector_reports_file_overlap_and_summary_warning() -> None:
    reports = MergeConflictDetector().detect(
        {
            "a": {"summary": "The API should use retries.", "changed_files": ["src/api.py"]},
            "b": {"summary": "The API should not use retries.", "changed_files": ["src/api.py"]},
        }
    )

    assert {report.conflict_type for report in reports} == {
        "changed_files_overlap",
        "conclusion_contradiction",
    }


@pytest.mark.parametrize(
    ("left", "right", "left_files", "right_files", "expected_types"),
    [
        ("Use retries.", "Use retries.", ["src/a.py"], ["src/b.py"], set()),
        (
            "The worker should use retries.",
            "The worker should not use retries.",
            ["src/a.py"],
            ["src/b.py"],
            {"conclusion_contradiction"},
        ),
        ("The API should cache.", "The API should not cache.", [], [], {"conclusion_contradiction"}),
        ("The API must validate.", "The API cannot validate.", [], [], {"conclusion_contradiction"}),
        ("The API can stream.", "The API can stream.", [], [], set()),
        ("No shared conclusion.", "No shared conclusion.", [], [], set()),
        ("Patch backend.", "Patch frontend.", ["src/shared.py"], ["src/shared.py"], {"changed_files_overlap"}),
        (
            "The worker should retry.",
            "The worker should not retry.",
            ["src/shared.py"],
            ["src/shared.py"],
            {"changed_files_overlap", "conclusion_contradiction"},
        ),
        ("The report is ready.", "The report is not ready.", [], [], {"conclusion_contradiction"}),
        ("Frontend uses tabs.", "Backend uses spaces.", [], [], set()),
        ("The API will call cache.", "The API won't call cache.", [], [], {"conclusion_contradiction"}),
        ("The task is scoped.", "The task is scoped.", ["a"], ["b"], set()),
    ],
)
def test_conflict_detector_matrix(
    left: str,
    right: str,
    left_files: list[str],
    right_files: list[str],
    expected_types: set[str],
) -> None:
    reports = MergeConflictDetector().detect(
        {
            "a": {"summary": left, "changed_files": left_files},
            "b": {"summary": right, "changed_files": right_files},
        }
    )

    assert {report.conflict_type for report in reports} == expected_types
