from types import SimpleNamespace

from focus_agent.engine.graph.retrieval_ledger import RetrievalLedgerEntry, retrieval_key
from focus_agent.engine.graph.tool_call_guards import _intercept_tool_call, _preflight_tool_call
from focus_agent.engine.graph.tool_execution import HarnessToolServices
from focus_agent.harness.extensions import ToolInterceptionResult
from focus_agent.harness.governance.permissions import PermissionAction


def _preflight(tool_name: str, args: dict, **overrides):
    kwargs = {
        "tool_name": tool_name,
        "tool_call_id": "call-1",
        "tool_args": args,
        "request_context": SimpleNamespace(),
        "tools_by_name": {"echo": object()},
        "tool_runtime_by_name": {"echo": SimpleNamespace(max_calls_per_turn=1)},
        "route_plan": None,
        "retrieval_ledger": {},
        "seen_signatures": set(),
        "tool_call_counts": {},
    }
    kwargs.update(overrides)
    return _preflight_tool_call(**kwargs)


def _runtime_info(message) -> dict:
    return message.artifact["runtime"]


def test_preflight_passes_and_counts_known_tool() -> None:
    counts: dict[str, int] = {}
    result = _preflight("echo", {"x": 1}, tool_call_counts=counts)

    assert result.error is None
    assert result.args == {"x": 1}
    assert counts == {"echo": 1}


def test_preflight_rejects_in_guard_order() -> None:
    missing = _preflight("", {})
    assert missing.error.artifact["tool_name"] == "unknown_tool"
    assert _runtime_info(missing.error)["malformed_tool_call"] is True

    seen: set[str] = set()
    assert _preflight("echo", {"x": 1}, seen_signatures=seen).error is None
    duplicate = _preflight("echo", {"x": 1}, seen_signatures=seen)
    assert _runtime_info(duplicate.error)["duplicate_tool_call_suppressed"] is True

    ledger = {
        retrieval_key("web_fetch", {"url": "https://e.x"}): RetrievalLedgerEntry(
            tool_name="web_fetch", tool_call_id="old", label="web_fetch", error=""
        )
    }
    repeated = _preflight("web_fetch", {"url": "https://e.x"}, retrieval_ledger=ledger)
    assert _runtime_info(repeated.error)["previous_tool_call_id"] == "old"

    assert "Unknown tool" in str(_preflight("nope", {}).error.content)

    forbidden = _preflight("echo", {}, route_plan={"allowed_tools": ["other"]})
    assert _runtime_info(forbidden.error)["forbidden_by_tool_router"] is True

    budget = _preflight("echo", {}, tool_call_counts={"echo": 1})
    assert _runtime_info(budget.error)["max_calls_per_turn_exceeded"] is True


def _intercept(services: HarnessToolServices, *, requires_approval: bool = False):
    return _intercept_tool_call(
        services=services,
        ext_ctx=object(),
        tool_name="echo",
        tool_call_id="call-1",
        tool_args={"x": 1},
        runtime_meta=SimpleNamespace(requires_approval=requires_approval),
        thread_id="thread",
        run_id=None,
        active_agent_name="focus_agent",
        state={},
    )


def test_intercept_extension_block_and_middleware_patch() -> None:
    blocking = SimpleNamespace(
        fire_hook=lambda *a, **k: [ToolInterceptionResult(block=True, reason="no")]
    )
    blocked = _intercept(HarnessToolServices(extension_registry=blocking))
    assert _runtime_info(blocked.error)["blocked_by_extension"] is True

    middleware = SimpleNamespace(
        intercept_tool_call=lambda *a, **k: SimpleNamespace(block=False, patched_args={"x": 2})
    )
    patched = _intercept(HarnessToolServices(middleware_stack=middleware))
    assert patched.error is None
    assert patched.args == {"x": 2}


def test_intercept_permission_actions() -> None:
    def manager(action):
        return SimpleNamespace(check_permission=lambda request: (action, "why"))

    denied = _intercept(HarnessToolServices(permission_manager=manager(PermissionAction.DENY)))
    assert _runtime_info(denied.error)["permission_denied"] is True

    allowed = _intercept(HarnessToolServices(permission_manager=manager(PermissionAction.ALLOW)))
    assert allowed.error is None

    ask = _intercept(HarnessToolServices(permission_manager=manager(PermissionAction.ASK)))
    assert ask.error is None
    assert ask.requires_approval is True
    assert ask.approval_reason == "why"

    ask_with_approval = _intercept(
        HarnessToolServices(permission_manager=manager(PermissionAction.ASK)),
        requires_approval=True,
    )
    assert ask_with_approval.error is None
    assert ask_with_approval.requires_approval is True
