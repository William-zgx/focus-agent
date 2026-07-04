"""Doom-loop detection middleware.

Where :class:`LoopDetectionMiddleware` watches for *output* loops
(repeated assistant messages or tool-call signatures in the message
history), :class:`DoomLoopMiddleware` watches for *tool-call* loops:
the same tool being invoked with the same (or effectively identical)
arguments over and over within a single session turn.

When the threshold is exceeded the middleware blocks the tool call,
returning a :class:`ToolCallInterception` with ``block=True`` so the
driver loop can surface a clear error / fallback message instead of
spinning forever.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .base import (
    BaseAgentMiddleware,
    ToolCallInterception,
)


def _stable_args_hash(tool_name: str, args: dict[str, Any]) -> str:
    """Produce a stable hash of ``(tool_name, args)`` for repetition counting."""
    payload = json.dumps(
        {"tool": tool_name, "args": args},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class DoomLoopMiddleware(BaseAgentMiddleware):
    """Block repeated identical tool invocations (doom-loop protection).

    Tracks a per-session counter keyed by a stable hash of
    ``(tool_name, args)``.  When the same tool+args pair has been
    invoked ``max_repetitions`` times within the current turn,
    ``on_tool_call`` returns a blocking interception.

    This complements :class:`LoopDetectionMiddleware`, which reacts to
    repeated *outputs* in the message stream after they have already
    been produced.  ``DoomLoopMiddleware`` stops the loop earlier, at
    the tool-call boundary.

    Attributes:
        max_repetitions: Number of identical invocations allowed before
            blocking (inclusive).  Must be >= 1.
    """

    max_repetitions: int = 3
    _counts: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_repetitions < 1:
            raise ValueError("max_repetitions must be >= 1.")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_turn_start(self, ctx: Any) -> None:  # noqa: D401
        """Reset counters at the start of each turn."""
        self._counts.clear()

    def on_turn_end(self, ctx: Any) -> None:  # noqa: D401
        """Reset counters at the end of each turn."""
        self._counts.clear()

    # ------------------------------------------------------------------
    # Tool interception
    # ------------------------------------------------------------------
    def on_tool_call(
        self, ctx: Any, tool_name: str, args: dict
    ) -> ToolCallInterception | None:
        """Block the call if this tool+args has repeated too many times."""
        key = _stable_args_hash(tool_name, args)
        self._counts[key] = self._counts.get(key, 0) + 1
        count = self._counts[key]
        if count > self.max_repetitions:
            # The first ``max_repetitions`` identical calls are allowed
            # through; on the (max_repetitions+1)-th we block to break
            # the doom loop.
            return ToolCallInterception(
                block=True,
                reason=(
                    f"doom loop detected: tool '{tool_name}' invoked with the "
                    f"same arguments {self.max_repetitions} times in a row"
                ),
            )
        return None

    def reset(self) -> None:
        """Manually clear the repetition counters."""
        self._counts.clear()


__all__ = ["DoomLoopMiddleware"]
