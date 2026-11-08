"""Per-call guards run by the tool executor node before a tool is executed."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any, NamedTuple

from langchain.messages import ToolMessage

from focus_agent.engine.graph.tool_call_repair import _tool_call_dedupe_key

from ...capabilities.default_tool_modules.memory import authorize_memory_tool_args
from ...capabilities.tool_runtime import build_tool_error_message
from .retrieval_ledger import RetrievalLedgerEntry, retrieval_key
from .tool_result_hooks import _blocked_tool_error, _denied_tool_result

logger = logging.getLogger(__name__)


_BASH_LIKE_TOOL_NAMES = frozenset(
    {
        "run_workspace_command",
        "bash",
        "shell",
        "execute_command",
        "run_command",
    }
)


class PreflightResult(NamedTuple):
    """Outcome of :func:`_preflight_tool_call`.

    ``error`` is set when the call must not run; otherwise ``args`` are the
    (possibly authorized) arguments and ``tool``/``runtime_meta`` are resolved.
    """

    error: ToolMessage | None
    args: dict[str, Any]
    tool: Any = None
    runtime_meta: Any = None


class InterceptionResult(NamedTuple):
    """Outcome of :func:`_intercept_tool_call`."""

    error: ToolMessage | None
    args: dict[str, Any]
    requires_approval: bool = False
    approval_reason: str | None = None


def _extract_command(tool_name: str, tool_args: Mapping[str, Any]) -> str | None:
    """Best-effort extraction of a shell command string from tool args for
    use in permission matching (e.g. ``bash:rm -rf *``)."""

    if not tool_args:
        return None
    if tool_name in _BASH_LIKE_TOOL_NAMES:
        for key in ("command", "cmd", "script", "shell", "input"):
            value = tool_args.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        parts = [str(v) for v in tool_args.values() if isinstance(v, str)]
        if parts:
            return " ".join(parts).strip()
    return None


def _repeated_retrieval_error(retrieved: RetrievalLedgerEntry) -> str:
    if retrieved.error:
        return (
            f"This URL already failed earlier in this turn ({retrieved.error}); "
            "retrying will fail the same way. Use another source."
        )
    return (
        "Already retrieved earlier in this turn "
        f"(tool call {retrieved.tool_call_id}); reuse that result. Read an "
        "unread source, search a different angle, or answer from the "
        "evidence collected."
    )


def _preflight_tool_call(
    *,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, Any],
    request_context: Any,
    tools_by_name: Mapping[str, Any],
    tool_runtime_by_name: Mapping[str, Any],
    retrieval_ledger: Mapping[str, RetrievalLedgerEntry],
    seen_signatures: set[str],
    tool_call_counts: dict[str, int],
) -> PreflightResult:
    """Run the static guards for one tool call, in order.

    Mutates ``seen_signatures`` and ``tool_call_counts`` exactly as the guards
    are passed, so later calls in the same batch see earlier ones.
    """

    def reject(
        error: str, runtime_info: dict[str, Any] | None = None, *, name: str = tool_name
    ) -> PreflightResult:
        return PreflightResult(
            build_tool_error_message(
                tool_call_id=tool_call_id,
                tool_name=name,
                args=tool_args,
                error=error,
                **({"runtime_info": runtime_info} if runtime_info is not None else {}),
            ),
            tool_args,
        )

    if not tool_name:
        return reject(
            "Malformed tool call: missing tool name",
            {"malformed_tool_call": True},
            name="unknown_tool",
        )
    signature = _tool_call_dedupe_key({"name": tool_name, "args": tool_args})
    if signature in seen_signatures:
        return reject(
            f"Duplicate tool call suppressed: {tool_name}",
            {"duplicate_tool_call_suppressed": True},
        )
    seen_signatures.add(signature)
    retrieved = retrieval_ledger.get(retrieval_key(tool_name, tool_args) or "")
    if retrieved is not None:
        return reject(
            _repeated_retrieval_error(retrieved),
            {
                "repeated_retrieval_suppressed": True,
                "previous_tool_call_id": retrieved.tool_call_id,
            },
        )
    authorized_args, authorization_error = authorize_memory_tool_args(
        tool_name,
        tool_args,
        request_context,
    )
    if authorization_error is not None:
        return reject(authorization_error, {"memory_context_authorization_failed": True})
    tool_args = authorized_args or tool_args
    tool = tools_by_name.get(tool_name)
    if tool is None:
        return reject(f"Unknown tool: {tool_name}")
    runtime_meta = tool_runtime_by_name.get(tool_name)
    if runtime_meta is None:
        return reject(
            f"Tool runtime metadata is missing: {tool_name}",
            {"missing_tool_runtime_metadata": True},
        )
    tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1
    max_calls = getattr(runtime_meta, "max_calls_per_turn", None)
    if max_calls is not None and tool_call_counts[tool_name] > int(max_calls):
        return reject(
            f"Tool call budget exceeded for {tool_name}: max {int(max_calls)} per turn",
            {"max_calls_per_turn_exceeded": True, "max_calls_per_turn": int(max_calls)},
        )
    validator = getattr(runtime_meta, "validator", None)
    if validator is not None:
        try:
            validator(tool_args)
        except Exception as exc:  # noqa: BLE001
            return reject(
                f"Invalid tool parameters for {tool_name}: {exc}",
                {"parameter_validation_error": True},
            )
    return PreflightResult(None, tool_args, tool, runtime_meta)


def _intercept_tool_call(
    *,
    services: Any | None,
    ext_ctx: Any | None,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, Any],
    runtime_meta: Any,
    thread_id: str | None,
    run_id: str | None,
    active_agent_name: str,
    state: Any,
) -> InterceptionResult:
    """Run the harness interception layers: extensions, middleware, permissions."""

    # Layer 1: Extension on_tool_call hook
    if services is not None and services.extension_registry is not None and ext_ctx is not None:
        try:
            from ...harness.extensions import ToolInterceptionResult

            hook_results = services.extension_registry.fire_hook(
                "on_tool_call",
                ext_ctx,
                tool_name=tool_name,
                args=tool_args,
            )
            for result in hook_results:
                if isinstance(result, ToolInterceptionResult):
                    if result.block:
                        return InterceptionResult(
                            _blocked_tool_error(
                                tool_call_id,
                                tool_name,
                                tool_args,
                                result.reason,
                                source="blocked_by_extension",
                            ),
                            tool_args,
                        )
                    if result.patched_args is not None:
                        tool_args = dict(result.patched_args)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Extension on_tool_call hook failed for tool=%s",
                tool_name,
                exc_info=True,
            )

    # Layer 2: Middleware intercept_tool_call
    if services is not None and services.middleware_stack is not None:
        try:
            mw_ctx = {
                "thread_id": thread_id,
                "run_id": run_id,
                "agent_name": active_agent_name,
                "state": state,
            }
            interception = services.middleware_stack.intercept_tool_call(
                tool_name,
                tool_args,
                ctx=mw_ctx,
            )
            if interception is not None and interception.block:
                return InterceptionResult(
                    _blocked_tool_error(
                        tool_call_id,
                        tool_name,
                        tool_args,
                        interception.reason,
                        source="blocked_by_middleware",
                    ),
                    tool_args,
                )
            if interception is not None and interception.patched_args is not None:
                tool_args = dict(interception.patched_args)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Middleware intercept_tool_call failed for tool=%s",
                tool_name,
                exc_info=True,
            )

    # Layer 3: Permission check. ALLOW only lets the tool run; it never waives the
    # human approval a tool declares with ``requires_approval``.
    if services is not None and services.permission_manager is not None:
        try:
            from ...harness.governance.permissions import (
                PermissionAction,
                PermissionRequest,
            )

            req = PermissionRequest(
                id=str(uuid.uuid4()),
                tool_name=tool_name,
                command=_extract_command(tool_name, tool_args),
                agent_name=active_agent_name or "*",
                session_id=thread_id,
                metadata={"args": dict(tool_args)},
            )
            action, reason = services.permission_manager.check_permission(req)
            if action == PermissionAction.DENY:
                return InterceptionResult(
                    _denied_tool_result(tool_call_id, tool_name, tool_args, reason), tool_args
                )
            if action == PermissionAction.ASK:
                return InterceptionResult(None, tool_args, True, reason)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Permission check failed for tool=%s",
                tool_name,
                exc_info=True,
            )
    return InterceptionResult(None, tool_args)
