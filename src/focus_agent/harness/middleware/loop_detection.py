from __future__ import annotations

import functools
import inspect
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from langchain.messages import AIMessage, HumanMessage

from .base import (
    BaseAgentMiddleware,
    MiddlewareHandler,
    messages_from_result,
    messages_from_state,
    state_from_call,
)
from .errors import LoopDetectedError

LoopAction = Literal["raise", "return_fallback"]


@dataclass(frozen=True, slots=True)
class LoopDetectionResult:
    reason: str
    signature: str
    repetitions: int


@dataclass(slots=True)
class LoopDetectionMiddleware(BaseAgentMiddleware):
    """Detect repeated model outputs or tool-call rounds in harness execution."""

    max_repetitions: int = 3
    window: int = 12
    max_consecutive_tool_call_rounds: int | None = None
    on_detected: LoopAction = "raise"
    fallback_message: str = "I stopped because the agent repeated the same step."

    def __post_init__(self) -> None:
        if self.max_repetitions < 2:
            raise ValueError("max_repetitions must be >= 2.")
        if self.window < 1:
            raise ValueError("window must be >= 1.")
        if (
            self.max_consecutive_tool_call_rounds is not None
            and self.max_consecutive_tool_call_rounds < 1
        ):
            raise ValueError("max_consecutive_tool_call_rounds must be >= 1.")
        if self.on_detected not in {"raise", "return_fallback"}:
            raise ValueError("on_detected must be 'raise' or 'return_fallback'.")

    def wrap(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        if inspect.iscoroutinefunction(handler):

            @functools.wraps(handler)
            async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
                state_messages = messages_from_state(state_from_call(args, kwargs)) or []
                result = await handler(*args, **kwargs)
                return self._checked_result(state_messages, result)

            return async_wrapped

        @functools.wraps(handler)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            state_messages = messages_from_state(state_from_call(args, kwargs)) or []
            result = handler(*args, **kwargs)
            return self._checked_result(state_messages, result)

        return wrapped

    def _checked_result(self, state_messages: list[Any], result: Any) -> Any:
        combined = [
            *state_messages,
            *messages_from_result(result),
        ]
        detected = self.detect(combined)
        if detected is None:
            return result
        if self.on_detected == "return_fallback":
            return self._fallback_result(result)
        raise LoopDetectedError(
            f"{detected.reason}: signature repeated {detected.repetitions} times."
        )

    def detect(self, messages: list[Any]) -> LoopDetectionResult | None:
        recent = _messages_since_latest_human(messages)
        if not recent:
            return None

        tool_rounds_result = self._detect_tool_round_exhaustion(recent)
        if tool_rounds_result is not None:
            return tool_rounds_result

        signatures = [
            signature
            for signature in (_message_signature(message) for message in recent[-self.window :])
            if signature
        ]
        counts = Counter(signatures)
        for signature in reversed(signatures):
            count = counts[signature]
            if count >= self.max_repetitions:
                return LoopDetectionResult(
                    reason="repeated_message_signature",
                    signature=signature,
                    repetitions=count,
                )
        return None

    def _detect_tool_round_exhaustion(self, messages: list[Any]) -> LoopDetectionResult | None:
        if self.max_consecutive_tool_call_rounds is None:
            return None
        rounds = sum(
            1
            for message in messages
            if isinstance(message, AIMessage) and getattr(message, "tool_calls", None)
        )
        if rounds < self.max_consecutive_tool_call_rounds:
            return None
        return LoopDetectionResult(
            reason="too_many_consecutive_tool_call_rounds",
            signature="tool_call_round",
            repetitions=rounds,
        )

    def _fallback_result(self, result: Any) -> Any:
        fallback = AIMessage(content=self.fallback_message)
        if isinstance(result, dict):
            updated = dict(result)
            updated["messages"] = [fallback]
            return updated
        return fallback


def _messages_since_latest_human(messages: list[Any]) -> list[Any]:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index + 1 :]
    return messages


def _message_signature(message: Any) -> str | None:
    if not isinstance(message, AIMessage):
        return None
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return f"tool_calls:{_tool_call_signature_payload(tool_calls)}"
    text = _normalize_text(getattr(message, "content", ""))
    if not text:
        return None
    return f"assistant_text:{text}"


def _tool_call_signature_payload(tool_calls: list[Any]) -> str:
    payload: list[dict[str, Any]] = []
    for raw_call in tool_calls:
        if not isinstance(raw_call, dict):
            continue
        args = raw_call.get("args") if isinstance(raw_call.get("args"), dict) else {}
        payload.append(
            {
                "name": str(raw_call.get("name") or "").strip(),
                "args": args,
            }
        )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _normalize_text(content: Any) -> str:
    if isinstance(content, list):
        raw = " ".join(str(item) for item in content)
    else:
        raw = str(content or "")
    return re.sub(r"\s+", " ", raw).strip().lower()[:1000]


__all__ = [
    "LoopAction",
    "LoopDetectionMiddleware",
    "LoopDetectionResult",
]
