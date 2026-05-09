"""Composable middleware for Focus Agent harness execution."""

from .base import (
    AgentMiddleware,
    BaseAgentMiddleware,
    MiddlewareHandler,
    MiddlewareStack,
)
from .errors import CircuitBreakerOpenError, LoopDetectedError, MiddlewareError
from .llm_error_handling import (
    CircuitBreaker,
    CircuitBreakerSnapshot,
    LLMErrorHandlingMiddleware,
)
from .loop_detection import LoopDetectionMiddleware, LoopDetectionResult
from .tool_calls import DanglingToolCallMiddleware

__all__ = [
    "AgentMiddleware",
    "BaseAgentMiddleware",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitBreakerSnapshot",
    "DanglingToolCallMiddleware",
    "LLMErrorHandlingMiddleware",
    "LoopDetectedError",
    "LoopDetectionMiddleware",
    "LoopDetectionResult",
    "MiddlewareError",
    "MiddlewareHandler",
    "MiddlewareStack",
]
