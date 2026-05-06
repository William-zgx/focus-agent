from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..agent_delegation import (
    build_agent_delegation_plan,
    build_model_route_decision,
)
from ..agent_execution import (
    SubagentRegistry,
    executor_for_mode,
    run_delegated_tasks,
)
from ..agent_roles import build_role_route_plan
from ..agent_task_ledger import (
    apply_critic_retry_tasks,
    build_agent_task_ledger,
    build_delegated_artifacts,
    evaluate_critic_gate,
    synthesize_delegated_artifacts,
)
from ..capabilities.tool_router import infer_tool_router_role
from ..config import Settings
from ..core.state import AgentState, append_agent_state_record
from .graph_turn_helpers import _latest_human_message_text
from .graph_tool_policy import _classify_turn_tool_policy


def make_role_route_dry_run_node(
    *,
    settings: Settings,
    tools: Sequence[Any],
) -> Any:
    def role_route_dry_run(state: AgentState) -> dict[str, Any]:
        if not settings.agent_role_routing_enabled:
            return {}
        latest_user = _latest_human_message_text(list(state.get("messages", []) or []))
        task_text = latest_user or str(state.get("task_brief") or "")
        tool_policy = _classify_turn_tool_policy(task_text)
        plan = build_role_route_plan(
            settings=settings,
            task_text=task_text,
            available_tool_names=[str(getattr(tool, "name", "")) for tool in tools],
            tool_policy=tool_policy,
        )
        updates: dict[str, Any] = {}
        append_agent_state_record(
            updates,
            "role_route_plan",
            plan.model_dump(mode="json"),
            source="role_route_dry_run",
        )
        return updates

    return role_route_dry_run


def make_delegation_governance_node(
    *,
    settings: Settings,
    tools: Sequence[Any],
    chat_model_factory: Callable[..., Any],
) -> Any:
    def delegation_governance(state: AgentState) -> dict[str, Any]:
        latest_user = _latest_human_message_text(list(state.get("messages", []) or []))
        task_text = latest_user or str(state.get("task_brief") or "")
        tool_policy = _classify_turn_tool_policy(task_text)
        available_tool_names = [str(getattr(tool, "name", "")) for tool in tools]
        updates: dict[str, Any] = {}
        meta = dict(state.get("plan_meta") or {})
        if settings.agent_delegation_enabled:
            delegation_plan = build_agent_delegation_plan(
                settings=settings,
                task_text=task_text,
                role_route_plan=state.get("role_route_plan"),
                available_tool_names=available_tool_names,
                tool_policy=tool_policy,
            )
            execution_mode = str(delegation_plan.execution_mode)
            executor = executor_for_mode(
                delegation_plan.execution_mode,
                model_factory=chat_model_factory,
                settings=settings,
            )
            run_results = run_delegated_tasks(
                tasks=list(delegation_plan.tasks),
                registry=SubagentRegistry.from_settings(
                    settings,
                    context_refs=list(state.get("context_artifact_refs") or []),
                ),
                executor=executor,
                max_parallel_runs=delegation_plan.max_parallel_runs,
            )
            if run_results:
                results_by_task = {result.task_id: result for result in run_results}
                merged_runs = [
                    results_by_task.get(run.task_id, None).to_agent_run()
                    if run.task_id in results_by_task
                    else run
                    for run in delegation_plan.runs
                ]
                delegation_plan = delegation_plan.model_copy(update={"runs": merged_runs})
            delegation_dump = delegation_plan.model_dump(mode="json")
            delegation_dump["run_results"] = [item.model_dump(mode="json") for item in run_results]
            append_agent_state_record(
                updates,
                "agent_delegation_plan",
                delegation_dump,
                source="delegation_governance",
            )
            append_agent_state_record(
                updates,
                "agent_runs",
                list(delegation_dump.get("runs") or []),
                source="delegation_governance",
            )
            meta["agent_delegation_plan"] = delegation_dump
            meta["agent_delegation_execution_mode"] = execution_mode
        if settings.agent_model_router_enabled:
            role = infer_tool_router_role(state.get("role_route_plan"))
            decision = build_model_route_decision(
                settings=settings,
                role=role,
                selected_model=str(state.get("selected_model") or settings.model),
                task_text=task_text,
                tool_risk="low",
                context_size=len(str(state.get("assembled_context") or "")),
            ).model_dump(mode="json")
            append_agent_state_record(
                updates,
                "model_route_decision",
                decision,
                source="delegation_governance",
            )
            meta["model_route_decision"] = decision
            if decision.get("enabled") and decision.get("mode") == "enforce":
                updates["selected_model"] = str(
                    decision.get("effective_model") or state.get("selected_model") or settings.model
                )
        if settings.agent_task_ledger_enabled:
            delegation_plan = (
                updates.get("agent_delegation_plan") or state.get("agent_delegation_plan") or {}
            )
            ledger = build_agent_task_ledger(
                settings=settings,
                delegation_plan=delegation_plan,
            ).model_dump(mode="json")
            artifacts = [
                item.model_dump(mode="json")
                for item in build_delegated_artifacts(
                    ledger=ledger,
                    delegation_plan=delegation_plan,
                    memory_curator_decision=state.get("memory_curator_decision"),
                    tool_route_plan=state.get("tool_route_plan"),
                    context_artifact_refs=state.get("context_artifact_refs") or [],
                )
            ]
            critic_result = None
            if settings.agent_critic_gate_enabled:
                critic_result = evaluate_critic_gate(
                    settings=settings,
                    ledger=ledger,
                    artifacts=artifacts,
                ).model_dump(mode="json")
                ledger = apply_critic_retry_tasks(
                    ledger=ledger,
                    critic_gate_result=critic_result,
                ).model_dump(mode="json")
            synthesis_result = None
            if settings.agent_artifact_synthesis_enabled:
                synthesis_result = synthesize_delegated_artifacts(
                    settings=settings,
                    artifacts=artifacts,
                    critic_gate_result=critic_result,
                ).model_dump(mode="json")
            append_agent_state_record(
                updates,
                "agent_task_ledger",
                ledger,
                source="delegation_governance",
            )
            append_agent_state_record(
                updates,
                "delegated_artifacts",
                artifacts,
                source="delegation_governance",
            )
            meta["agent_task_ledger"] = ledger
            meta["delegated_artifacts"] = artifacts
            if critic_result is not None:
                append_agent_state_record(
                    updates,
                    "critic_gate_result",
                    critic_result,
                    source="delegation_governance",
                )
                meta["critic_gate_result"] = critic_result
            if synthesis_result is not None:
                append_agent_state_record(
                    updates,
                    "artifact_synthesis_result",
                    synthesis_result,
                    source="delegation_governance",
                )
                meta["artifact_synthesis_result"] = synthesis_result
        if updates.get("governance_records"):
            meta["governance_records"] = [
                *list(meta.get("governance_records") or []),
                *list(updates.get("governance_records") or []),
            ]
        if meta != dict(state.get("plan_meta") or {}):
            updates["plan_meta"] = meta
        return updates

    return delegation_governance


__all__ = [
    "make_delegation_governance_node",
    "make_role_route_dry_run_node",
]
