from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PermissionAction(str, Enum):
    """Possible outcomes for a permission evaluation."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PermissionRule:
    """A single permission rule that matches tools/agents via glob patterns.

    Rules are evaluated in order; the last matching rule wins (opencode-style).
    """

    action: PermissionAction
    tool_pattern: str = "*"
    agent_pattern: str = "*"
    priority: int = 0
    reason: str | None = None


@dataclass(slots=True)
class PermissionRequest:
    """A request to invoke a tool, evaluated by the permission system."""

    id: str
    tool_name: str
    command: str | None = None
    agent_name: str = "*"
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


_DEFAULT_ASK_RULE = PermissionRule(
    action=PermissionAction.ASK,
    tool_pattern="*",
    agent_pattern="*",
    reason="default: no matching rule; prompting for approval",
)


class PermissionEvaluator:
    """Evaluate permission requests against an ordered list of rules.

    Matching uses ``fnmatch`` glob patterns on both tool and agent names.
    For bash-like tools the full ``tool:command`` string is also matched so
    that rules like ``"bash:rm -rf *"`` work as expected.

    The *last* matching rule wins. If no rule matches, a default ASK rule
    is returned.
    """

    def __init__(self, rules: list[PermissionRule] | None = None) -> None:
        self._rules: list[PermissionRule] = list(rules or [])

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------
    def add_rule(self, rule: PermissionRule) -> None:
        self._rules.append(rule)

    @property
    def rules(self) -> list[PermissionRule]:
        return list(self._rules)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------
    def evaluate(self, request: PermissionRequest) -> PermissionRule:
        """Return the winning rule for *request*.

        We first sort rules by priority (ascending) then insertion order,
        then scan; the final match wins. When a ``command`` is present we
        try matching against ``f"{tool}:{command}"`` as well, so that
        command-specific patterns (e.g. ``bash:rm -rf *``) take precedence
        over bare tool patterns (e.g. ``bash:*``).
        """
        ordered = sorted(
            enumerate(self._rules), key=lambda item: (item[1].priority, item[0])
        )

        matched: PermissionRule | None = None
        tool_candidates = [request.tool_name]
        if request.command:
            tool_candidates.insert(0, f"{request.tool_name}:{request.command}")

        for _idx, rule in ordered:
            tool_match = any(
                fnmatch.fnmatch(candidate, rule.tool_pattern)
                for candidate in tool_candidates
            )
            if not tool_match:
                # Also allow the bare pattern to match the tool name when
                # command is present (e.g. pattern "bash" matches any bash call).
                tool_match = fnmatch.fnmatch(request.tool_name, rule.tool_pattern)
            agent_match = fnmatch.fnmatch(request.agent_name, rule.agent_pattern)
            if tool_match and agent_match:
                matched = rule

        if matched is None:
            return _DEFAULT_ASK_RULE
        return matched

    def evaluate_simple(
        self,
        tool_name: str,
        command: str | None = None,
        agent: str = "*",
    ) -> PermissionAction:
        """Convenience wrapper that returns just the action."""
        request = PermissionRequest(
            id="simple",
            tool_name=tool_name,
            command=command,
            agent_name=agent,
        )
        return self.evaluate(request).action


class DoomLoopDetector:
    """Detect repetitive tool-call patterns that indicate an agent is stuck.

    For each session we keep a bounded history of ``(tool_name, args_hash)``
    tuples. When ``max_repetitions`` identical entries appear at the tail
    of the history the detector signals a loop.
    """

    def __init__(self, history_size: int = 50) -> None:
        self._history: dict[str, deque[tuple[str, str]]] = {}
        self._history_size = history_size

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def hash_args(args: Any) -> str:
        """Return a stable hash for arbitrary argument values."""
        try:
            serialized = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = repr(args)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def _queue(self, session_id: str) -> deque[tuple[str, str]]:
        q = self._history.get(session_id)
        if q is None:
            q = deque(maxlen=self._history_size)
            self._history[session_id] = q
        return q

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def record_call(
        self,
        session_id: str,
        tool_name: str,
        args_hash: str,
    ) -> None:
        self._queue(session_id).append((tool_name, args_hash))

    def detect_loop(
        self,
        session_id: str,
        tool_name: str,
        args_hash: str,
        max_repetitions: int = 3,
    ) -> bool:
        q = self._queue(session_id)
        if len(q) + 1 < max_repetitions:
            return False
        key = (tool_name, args_hash)
        count = 0
        # Walk the tail looking for consecutive repeats.
        for entry in reversed(q):
            if entry == key:
                count += 1
                if count >= max_repetitions:
                    logger.warning(
                        "Doom-loop detected for session=%s tool=%s (count>=%d)",
                        session_id,
                        tool_name,
                        max_repetitions,
                    )
                    return True
            else:
                break
        return False

    def clear_session(self, session_id: str) -> None:
        self._history.pop(session_id, None)


class PermissionManager:
    """Combine :class:`PermissionEvaluator` and :class:`DoomLoopDetector`."""

    def __init__(
        self,
        rules: list[PermissionRule] | None = None,
        doom_loop_threshold: int = 3,
    ) -> None:
        self.evaluator = PermissionEvaluator(rules=rules)
        self.doom_loop = DoomLoopDetector()
        self.doom_loop_threshold = doom_loop_threshold

    def check_permission(
        self,
        request: PermissionRequest,
    ) -> tuple[PermissionAction, str | None]:
        """Evaluate *request*, returning ``(action, reason)``.

        If a doom-loop is detected the action is forced to ``ASK`` with a
        descriptive reason so the user can intervene.
        """
        session_id = request.session_id or "<anonymous>"
        args_hash = DoomLoopDetector.hash_args(request.metadata.get("args"))
        if self.doom_loop.detect_loop(
            session_id,
            request.tool_name,
            args_hash,
            max_repetitions=self.doom_loop_threshold,
        ):
            self.doom_loop.record_call(session_id, request.tool_name, args_hash)
            return PermissionAction.ASK, "doom loop detected"

        rule = self.evaluator.evaluate(request)
        self.doom_loop.record_call(session_id, request.tool_name, args_hash)
        return rule.action, rule.reason


# ----------------------------------------------------------------------
# Config parsing
# ----------------------------------------------------------------------
def parse_rules_from_config(config: dict[str, Any]) -> list[PermissionRule]:
    """Parse a list of :class:`PermissionRule` objects from a config dict.

    Expected shape::

        {
            "permissions": [
                {"tool": "bash:rm -rf *", "action": "deny"},
                {"tool": "*", "action": "allow", "agent": "trusted-*"},
                {"tool": "*", "action": "ask", "priority": -1},
            ]
        }
    """
    raw_rules = config.get("permissions", [])
    if not isinstance(raw_rules, list):
        raise ValueError("permissions config must be a list")

    rules: list[PermissionRule] = []
    for entry in raw_rules:
        if not isinstance(entry, dict):
            logger.warning("Skipping non-dict permission entry: %r", entry)
            continue
        action_raw = entry.get("action")
        if action_raw is None:
            logger.warning("Skipping permission entry without 'action': %r", entry)
            continue
        try:
            action = PermissionAction(str(action_raw).lower())
        except ValueError:
            logger.warning("Unknown permission action %r; skipping", action_raw)
            continue
        rules.append(
            PermissionRule(
                action=action,
                tool_pattern=str(entry.get("tool", "*")),
                agent_pattern=str(entry.get("agent", "*")),
                priority=int(entry.get("priority", 0)),
                reason=entry.get("reason"),
            )
        )
    return rules


__all__ = [
    "DoomLoopDetector",
    "PermissionAction",
    "PermissionEvaluator",
    "PermissionManager",
    "PermissionRequest",
    "PermissionRule",
    "parse_rules_from_config",
]
