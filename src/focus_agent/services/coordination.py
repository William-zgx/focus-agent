from __future__ import annotations

from uuid import uuid4

import psycopg as psycopg

from focus_agent.multi_agent.approval_queue import InMemoryApprovalQueue, PostgresApprovalQueue
from focus_agent.multi_agent.failure_handler import FailureHandler
from focus_agent.multi_agent.message_bus import InMemoryAgentMessageBus, PostgresAgentMessageBus
from focus_agent.multi_agent.resource_lock import (
    InMemoryResourceLockManager,
    PostgresResourceLockManager,
)

from .coordination_memory import (
    InMemoryBackgroundJobDeduperBackend,
    InMemoryRateLimitBackend,
    InMemoryThreadTurnLockBackend,
)
from .coordination_models import (
    BACKGROUND_JOB_DEDUPE_POLICIES,
    BackgroundJobClaim,
    BackgroundJobDeduperBackend,
    BackgroundJobSpec,
    CoordinationBackend,
    RateLimitBackend,
    ThreadTurnLease,
    ThreadTurnLockBackend,
)
from .coordination_postgres import (
    PostgresBackgroundJobDeduperBackend,
    PostgresRateLimitBackend,
    PostgresThreadTurnLockBackend,
)


def create_in_memory_coordination_backend() -> CoordinationBackend:
    return CoordinationBackend(
        thread_turns=InMemoryThreadTurnLockBackend(),
        job_deduper=InMemoryBackgroundJobDeduperBackend(),
        rate_limiter=InMemoryRateLimitBackend(),
        resource_locks=InMemoryResourceLockManager(),
        message_bus=InMemoryAgentMessageBus(),
        failure_handler=FailureHandler(),
        approval_queue=InMemoryApprovalQueue(),
    )


def create_coordination_backend(
    *,
    database_uri: str | None = None,
    background_job_backend: str = "memory",
    background_job_claim_ttl_seconds: float = 300.0,
    background_job_retry_base_delay_seconds: float = 5.0,
    background_job_retry_max_delay_seconds: float = 300.0,
    multi_agent_enabled: bool = False,
    multi_agent_message_ttl_seconds: float = 300.0,
) -> CoordinationBackend:
    in_memory = create_in_memory_coordination_backend()
    if not database_uri:
        return in_memory
    job_backend = in_memory.job_deduper
    if str(background_job_backend or "memory").strip().lower() == "postgres":
        job_backend = PostgresBackgroundJobDeduperBackend(
            database_uri,
            claim_ttl_seconds=background_job_claim_ttl_seconds,
            retry_base_delay_seconds=background_job_retry_base_delay_seconds,
            retry_max_delay_seconds=background_job_retry_max_delay_seconds,
        )
    return CoordinationBackend(
        thread_turns=PostgresThreadTurnLockBackend(database_uri),
        job_deduper=job_backend,
        rate_limiter=PostgresRateLimitBackend(database_uri),
        resource_locks=PostgresResourceLockManager(database_uri)
        if multi_agent_enabled
        else in_memory.resource_locks,
        message_bus=PostgresAgentMessageBus(
            database_uri,
            default_ttl_seconds=multi_agent_message_ttl_seconds,
        )
        if multi_agent_enabled
        else in_memory.message_bus,
        failure_handler=in_memory.failure_handler,
        approval_queue=PostgresApprovalQueue(database_uri)
        if multi_agent_enabled
        else in_memory.approval_queue,
    )


def new_thread_turn_owner() -> str:
    return uuid4().hex


def background_job_key(*, kind: str, thread_id: str) -> str:
    return f"chat:{kind}:{thread_id}"


__all__ = [
    "BACKGROUND_JOB_DEDUPE_POLICIES",
    "BackgroundJobDeduperBackend",
    "BackgroundJobClaim",
    "BackgroundJobSpec",
    "CoordinationBackend",
    "InMemoryBackgroundJobDeduperBackend",
    "InMemoryAgentMessageBus",
    "InMemoryApprovalQueue",
    "InMemoryRateLimitBackend",
    "InMemoryResourceLockManager",
    "InMemoryThreadTurnLockBackend",
    "PostgresAgentMessageBus",
    "PostgresApprovalQueue",
    "PostgresBackgroundJobDeduperBackend",
    "PostgresRateLimitBackend",
    "PostgresResourceLockManager",
    "PostgresThreadTurnLockBackend",
    "RateLimitBackend",
    "ThreadTurnLease",
    "ThreadTurnLockBackend",
    "background_job_key",
    "create_coordination_backend",
    "create_in_memory_coordination_backend",
    "new_thread_turn_owner",
]
