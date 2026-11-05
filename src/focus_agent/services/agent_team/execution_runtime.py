"""Stable public facade for the independent Agent Team task runtime.

The data-model/protocol layer and execution-loop layer live in dedicated
modules, while this path remains stable for existing runtime consumers.
"""

from focus_agent.services.agent_team import task_runtime_protocol as _protocol
from focus_agent.services.agent_team.task_runtime_protocol import (
    CancellationToken,
    TaskAgentMessage,
    TaskAgentModel,
    TaskApprovalDecider,
    TaskApprovalRequest,
    TaskExecutionCancelled,
    TaskExecutionCheckpoint,
    TaskExecutionEventType,
    TaskExecutionEvidence,
    TaskExecutionScope,
    TaskModelResponse,
    TaskRunResult,
    TaskRunStatus,
    TaskScopedTool,
    TaskToolCall,
    TaskToolDefinition,
    TaskToolResult,
)
from focus_agent.services.agent_team.task_runtime_runner import TaskAgentRunner, TaskRunCoordinator

CheckpointSink = _protocol.CheckpointSink
EvidenceSink = _protocol.EvidenceSink
TaskExecutionCancelledError = _protocol.TaskExecutionCancelledError
TaskToolHandler = _protocol.TaskToolHandler

__all__ = [
    "CancellationToken",
    "TaskAgentMessage",
    "TaskAgentModel",
    "TaskAgentRunner",
    "TaskApprovalDecider",
    "TaskApprovalRequest",
    "TaskExecutionCancelled",
    "TaskExecutionCheckpoint",
    "TaskExecutionEventType",
    "TaskExecutionEvidence",
    "TaskExecutionScope",
    "TaskModelResponse",
    "TaskRunCoordinator",
    "TaskRunResult",
    "TaskRunStatus",
    "TaskScopedTool",
    "TaskToolCall",
    "TaskToolDefinition",
    "TaskToolResult",
]
