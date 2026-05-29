from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from langchain.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from ...core.branching import BranchMeta
from ...core.repo_call import has_repo_method
from ...observability.tracing import TraceCorrelation
from ...observability.trajectory import utc_now
from ..coordination import background_job_key
from .context_compaction import ChatContextCompactionMixin
from .streaming import (
    _STREAM_END,
    _STREAM_SHUTDOWN_TIMEOUT_SECONDS,
    _await_with_timeout,
    _call_in_daemon_thread,
    _cancel_task_with_timeout,
    _close_stream_iter,
    _consume_graph_stream,
    _consume_task_result,
    _next_graph_chunk,
    checkpointer_lacks_async_support,
    logger,
    stream_graph_chunks,
    stream_graph_chunks_via_sync_stream,
)
from .threads import record_turn_trajectory_best_effort
from .turn_recording import ChatTurnRecordingMixin

__all__ = [
    "annotations",
    "asyncio",
    "logging",
    "threading",
    "AsyncIterator",
    "suppress",
    "Any",
    "HumanMessage",
    "BaseCheckpointSaver",
    "BranchMeta",
    "has_repo_method",
    "TraceCorrelation",
    "utc_now",
    "background_job_key",
    "record_turn_trajectory_best_effort",
    "logger",
    "stream_graph_chunks",
    "stream_graph_chunks_via_sync_stream",
    "checkpointer_lacks_async_support",
    "ChatTurnRecordingMixin",
    "ChatContextCompactionMixin",
    "_STREAM_END",
    "_STREAM_SHUTDOWN_TIMEOUT_SECONDS",
    "_consume_graph_stream",
    "_next_graph_chunk",
    "_close_stream_iter",
    "_consume_task_result",
    "_cancel_task_with_timeout",
    "_await_with_timeout",
    "_call_in_daemon_thread",
]
