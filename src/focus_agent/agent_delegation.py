from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Literal
from uuid import uuid4

from pydantic import Field

from .agent_roles import AgentRole, RoleModelResolver, build_role_route_plan, normalize_agent_role
from .config import Settings
from .core.types import StateModel
from .model_registry import canonical_model_id


AgentRunStatus = Literal["planned", "running", "completed", "failed", "skipped", "needs_review"]
AgentDecisionKind = Literal["route", "delegate", "retry", "deny", "approve", "reject"]
AgentFailureType = Literal[
    "planning_gap",
    "tool_denied",
    "forbidden_tool_attempt",
    "memory_scope_violation",
    "critic_rejected",
    "model_protocol_error",
    "budget_exceeded",
]
ReviewItemStatus = Literal["pending", "approved", "rejected"]


class AgentBudget(StateModel):
    max_llm_calls: int = Field(default=1, ge=0)
    max_tool_calls: int = Field(default=3, ge=0)
    max_cost_usd: float = Field(default=0.0, ge=0.0)


class AgentTask(StateModel):
    task_id: str
    parent_task_id: str | None = None
    role: AgentRole
    goal: str
    constraints: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    memory_scope: str = "thread"
    budget: AgentBudget = Field(default_factory=AgentBudget)
    acceptance_criteria: list[str] = Field(default_factory=list)


class AgentArtifact(StateModel):
    artifact_id: str
    kind: str = "evidence"
    title: str
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRun(StateModel):
    run_id: str
    task_id: str
    role: AgentRole
    status: AgentRunStatus = "planned"
    model_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    tool_calls: int = 0
    cost: float = 0.0
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    error: str | None = None


class AgentDecision(StateModel):
    decision_id: str
    kind: AgentDecisionKind
    role: AgentRole
    task_id: str | None = None
    rationale: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentDelegationPlan(StateModel):
    enabled: bool = False
    enforce: bool = False
    source: str = "disabled"
    route_reason: str = ""
    max_parallel_runs: int = 1
    tasks: list[AgentTask] = Field(default_factory=list)
    runs: list[AgentRun] = Field(default_factory=list)
    decisions: list[AgentDecision] = Field(default_factory=list)
    legacy_execution_unchanged: bool = True


class ModelRouteDecision(StateModel):
    enabled: bool = False
    mode: Literal["observe", "enforce"] = "observe"
    role: AgentRole = AgentRole.EXECUTOR
    selected_model: str
    recommended_model: str
    effective_model: str
    route_reason: str = ""
    fallback_used: bool = False
    candidates: list[str] = Field(default_factory=list)


class AgentFailureRecord(StateModel):
    failure_id: str
    failure_type: AgentFailureType
    failed_role: AgentRole
    failed_task_id: str | None = None
    tool_route_plan: dict[str, Any] = Field(default_factory=dict)
    memory_scope: str = "thread"
    model_id: str | None = None
    trajectory_id: str | None = None
    message: str = ""


class AgentReviewItem(StateModel):
    item_id: str
    item_type: str
    status: ReviewItemStatus = "pending"
    role: AgentRole | None = None
    task_id: str | None = None
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentSelfRepairPreview(StateModel):
    enabled: bool = False
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    failures: list[AgentFailureRecord] = Field(default_factory=list)


def build_agent_delegation_plan(
    *,
    settings: Settings,
    task_text: str,
    role_route_plan: dict[str, Any] | None = None,
    available_tool_names: Iterable[str] = (),
    tool_policy: str = "",
) -> AgentDelegationPlan:
    if not bool(getattr(settings, "agent_delegation_enabled", False)):
        return AgentDelegationPlan(
            enabled=False,
            enforce=False,
            source="disabled",
            route_reason="AGENT_DELEGATION_ENABLED is off.",
            max_parallel_runs=max(1, int(getattr(settings, "agent_role_max_parallel_runs", 1))),
        )

    route_plan = role_route_plan or build_role_route_plan(
        settings=settings,
        task_text=task_text,
        available_tool_names=available_tool_names,
        tool_policy=tool_policy,
    ).model_dump(mode="json")
    route_decisions = _route_decisions(route_plan)
    resolver = RoleModelResolver(settings)
    now = _utc_now()
    tasks: list[AgentTask] = []
    runs: list[AgentRun] = []
    decisions: list[AgentDecision] = []
    enforce = bool(getattr(settings, "agent_delegation_enforce", False))

    for index, raw in enumerate(route_decisions):
        role = normalize_agent_role(str(raw.get("role") or AgentRole.EXECUTOR.value))
        task_id = f"task-{index + 1}-{role.value}"
        governance = raw.get("tool_governance") if isinstance(raw.get("tool_governance"), dict) else {}
        task = AgentTask(
            task_id=task_id,
            parent_task_id=None if role == AgentRole.ORCHESTRATOR else "task-1-orchestrator",
            role=role,
            goal=str(raw.get("task_slice") or task_text or f"{role.value} delegated task"),
            constraints=[
                "Respect Memory Curator scope.",
                "Respect Tool Router allow/deny plan.",
            ],
            allowed_tools=[str(item) for item in governance.get("allowed_tools") or []],
            memory_scope="branch_local" if role == AgentRole.MEMORY_CURATOR else "thread",
            budget=_budget_for_role(role),
            acceptance_criteria=[str(raw.get("rationale") or "Role output is traceable and reviewable.")],
        )
        tasks.append(task)
        status: AgentRunStatus = "completed" if enforce else "planned"
        runs.append(
            AgentRun(
                run_id=f"run-{task_id}",
                task_id=task_id,
                role=role,
                status=status,
                model_id=str(raw.get("model_id") or resolver.resolve(role)),
                started_at=now if enforce else None,
                finished_at=now if enforce else None,
                artifacts=[
                    AgentArtifact(
                        artifact_id=f"artifact-{task_id}",
                        kind="decision",
                        title=f"{role.value} delegation {'run' if enforce else 'plan'}",
                        summary=str(raw.get("rationale") or ""),
                    )
                ],
            )
        )
        decisions.append(
            AgentDecision(
                decision_id=f"decision-{task_id}",
                kind="delegate",
                role=role,
                task_id=task_id,
                rationale=str(raw.get("rationale") or "Delegated from role route plan."),
                payload={"run_isolation_key": raw.get("run_isolation_key"), "depends_on": raw.get("depends_on") or []},
            )
        )

    return AgentDelegationPlan(
        enabled=True,
        enforce=enforce,
        source="delegation_runtime",
        route_reason=str(route_plan.get("route_reason") or "Delegation runtime built role tasks."),
        max_parallel_runs=max(1, int(route_plan.get("max_parallel_runs") or getattr(settings, "agent_role_max_parallel_runs", 1))),
        tasks=tasks,
        runs=runs,
        decisions=decisions,
        legacy_execution_unchanged=not enforce,
    )


def build_model_route_decision(
    *,
    settings: Settings,
    role: AgentRole | str = AgentRole.EXECUTOR,
    selected_model: str | None = None,
    task_text: str = "",
    tool_risk: str = "low",
    context_size: int = 0,
) -> ModelRouteDecision:
    role_value = normalize_agent_role(role)
    current = canonical_model_id(selected_model or settings.model, settings=settings)
    enabled = bool(getattr(settings, "agent_model_router_enabled", False))
    mode = str(getattr(settings, "agent_model_router_mode", "observe") or "observe").lower()
    mode = "enforce" if mode == "enforce" else "observe"
    resolver = RoleModelResolver(settings)
    recommended = resolver.resolve(role_value, fallback_model=current)
    reason = _model_route_reason(role_value, task_text=task_text, tool_risk=tool_risk, context_size=context_size)
    effective = recommended if enabled and mode == "enforce" else current
    return ModelRouteDecision(
        enabled=enabled,
        mode=mode,  # type: ignore[arg-type]
        role=role_value,
        selected_model=current,
        recommended_model=recommended,
        effective_model=effective,
        route_reason=reason,
        fallback_used=enabled and mode == "enforce" and effective != recommended,
        candidates=_model_candidates(settings, role_value, current),
    )


def build_failure_records(
    *,
    delegation_plan: dict[str, Any] | None = None,
    tool_route_plan: dict[str, Any] | None = None,
    model_route_decision: dict[str, Any] | None = None,
    trajectory_id: str | None = None,
) -> list[AgentFailureRecord]:
    records: list[AgentFailureRecord] = []
    route_plan = tool_route_plan if isinstance(tool_route_plan, dict) else {}
    denied_tools = route_plan.get("denied_tools") or []
    if denied_tools:
        records.append(
            AgentFailureRecord(
                failure_id=f"failure-{uuid4().hex[:12]}",
                failure_type="tool_denied",
                failed_role=normalize_agent_role(str(route_plan.get("role") or AgentRole.EXECUTOR.value)),
                failed_task_id=_first_task_id(delegation_plan),
                tool_route_plan=route_plan,
                model_id=(model_route_decision or {}).get("effective_model") if isinstance(model_route_decision, dict) else None,
                trajectory_id=trajectory_id,
                message=f"Tool Router denied {len(denied_tools)} tool(s).",
            )
        )
    if isinstance(delegation_plan, dict):
        for raw in delegation_plan.get("runs") or []:
            if isinstance(raw, dict) and raw.get("status") == "failed":
                records.append(
                    AgentFailureRecord(
                        failure_id=f"failure-{uuid4().hex[:12]}",
                        failure_type="critic_rejected",
                        failed_role=normalize_agent_role(str(raw.get("role") or AgentRole.CRITIC.value)),
                        failed_task_id=raw.get("task_id"),
                        tool_route_plan=route_plan,
                        model_id=raw.get("model_id"),
                        trajectory_id=trajectory_id,
                        message=str(raw.get("error") or "Delegated run failed."),
                    )
                )
    return records


def build_self_repair_preview(
    *,
    failures: Iterable[dict[str, Any] | AgentFailureRecord],
    case_id_prefix: str = "agent_delegation",
) -> AgentSelfRepairPreview:
    normalized = [
        item if isinstance(item, AgentFailureRecord) else AgentFailureRecord.model_validate(item)
        for item in failures
    ]
    candidates = [
        {
            "id": f"{case_id_prefix}_{failure.failure_type}_{index + 1}",
            "tags": ["agent_delegation", "self_repair", failure.failure_type],
            "input": {
                "user_message": failure.message or "Replay failed delegated agent behavior.",
                "initial_state": {"agent_failure_records": [failure.model_dump(mode="json")]},
            },
            "expected": {
                "answer_contains_any": [failure.failure_type, failure.failed_role.value, "retry", "denied"],
                "must_not_call_tools": ["web_search", "web_fetch"] if failure.failure_type == "tool_denied" else [],
            },
            "judge": {"rule": True, "llm": {"enabled": False}},
        }
        for index, failure in enumerate(normalized)
    ]
    return AgentSelfRepairPreview(enabled=True, candidates=candidates, failures=normalized)


def build_review_queue(
    *,
    settings: Settings,
    memory_curator_decision: dict[str, Any] | None = None,
    tool_route_plan: dict[str, Any] | None = None,
    model_route_decision: dict[str, Any] | None = None,
    agent_failure_records: Iterable[dict[str, Any]] = (),
) -> list[AgentReviewItem]:
    if not bool(getattr(settings, "agent_review_queue_enabled", False)):
        return []
    items: list[AgentReviewItem] = []
    memory_decision = memory_curator_decision if isinstance(memory_curator_decision, dict) else {}
    if memory_decision.get("conflicts"):
        items.append(
            AgentReviewItem(
                item_id=f"review-{uuid4().hex[:12]}",
                item_type="memory_promotion_conflict",
                role=AgentRole.MEMORY_CURATOR,
                summary="Memory Curator found semantic conflicts before promotion.",
                payload=memory_decision,
            )
        )
    route_plan = tool_route_plan if isinstance(tool_route_plan, dict) else {}
    denied_tools = set(str(item) for item in route_plan.get("denied_tools") or [])
    if denied_tools.intersection({"write_text_artifact", "artifact_update"}):
        items.append(
            AgentReviewItem(
                item_id=f"review-{uuid4().hex[:12]}",
                item_type="workspace_write_with_high_risk_tool",
                role=normalize_agent_role(str(route_plan.get("role") or AgentRole.EXECUTOR.value)),
                summary="Workspace write was denied by Tool Router and requires review.",
                payload=route_plan,
            )
        )
    model_decision = model_route_decision if isinstance(model_route_decision, dict) else {}
    if model_decision.get("enabled") and model_decision.get("mode") == "enforce" and model_decision.get("selected_model") != model_decision.get("effective_model"):
        items.append(
            AgentReviewItem(
                item_id=f"review-{uuid4().hex[:12]}",
                item_type="model_router_enforce_override",
                role=normalize_agent_role(str(model_decision.get("role") or AgentRole.EXECUTOR.value)),
                summary="Model Router changed the effective model under enforce mode.",
                payload=model_decision,
            )
        )
    for raw in agent_failure_records:
        if raw.get("failure_type") == "critic_rejected":
            items.append(
                AgentReviewItem(
                    item_id=f"review-{uuid4().hex[:12]}",
                    item_type="critic_rejected_continue_request",
                    role=normalize_agent_role(str(raw.get("failed_role") or AgentRole.CRITIC.value)),
                    task_id=raw.get("failed_task_id"),
                    summary=str(raw.get("message") or "Critic rejected a delegated run."),
                    payload=dict(raw),
                )
            )
    return items


def apply_review_decision(item: dict[str, Any], *, approved: bool) -> AgentReviewItem:
    review = AgentReviewItem.model_validate(item)
    return review.model_copy(update={"status": "approved" if approved else "rejected"})


def _route_decisions(route_plan: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = route_plan.get("decisions") if isinstance(route_plan, dict) else None
    if isinstance(decisions, list) and decisions:
        return [dict(item) for item in decisions if isinstance(item, dict)]
    return [{"role": AgentRole.EXECUTOR.value, "task_slice": "Execute the user request."}]


def _budget_for_role(role: AgentRole) -> AgentBudget:
    if role == AgentRole.ORCHESTRATOR:
        return AgentBudget(max_llm_calls=1, max_tool_calls=0)
    if role == AgentRole.CRITIC:
        return AgentBudget(max_llm_calls=1, max_tool_calls=2)
    if role in {AgentRole.MEMORY_CURATOR, AgentRole.SKILL_SCOUT}:
        return AgentBudget(max_llm_calls=1, max_tool_calls=2)
    return AgentBudget(max_llm_calls=2, max_tool_calls=5)


def _model_route_reason(role: AgentRole, *, task_text: str, tool_risk: str, context_size: int) -> str:
    if role == AgentRole.CRITIC:
        return "Critic can start with a lower-cost reviewer model and escalate on low confidence."
    if role == AgentRole.PLANNER:
        return "Planning/decomposition uses the planner/helper model before execution."
    if tool_risk in {"high", "critical"}:
        return "High-risk tool usage requires explicit model route observability."
    if context_size > 12000:
        return "Large context favors a model profile with stronger context handling."
    if task_text and len(task_text) < 120:
        return "Short direct task can stay on the selected executor model."
    return "Role-specific model route selected from current settings."


def _model_candidates(settings: Settings, role: AgentRole, current: str) -> list[str]:
    resolver = RoleModelResolver(settings)
    candidates = [resolver.resolve(role, fallback_model=current), current]
    helper = getattr(settings, "helper_model", None)
    if helper:
        candidates.append(canonical_model_id(helper, settings=settings))
    return list(dict.fromkeys(candidates))


def _first_task_id(delegation_plan: dict[str, Any] | None) -> str | None:
    if not isinstance(delegation_plan, dict):
        return None
    tasks = delegation_plan.get("tasks") or []
    if tasks and isinstance(tasks[0], dict):
        return tasks[0].get("task_id")
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "AgentArtifact",
    "AgentBudget",
    "AgentDecision",
    "AgentDelegationPlan",
    "AgentFailureRecord",
    "AgentReviewItem",
    "AgentRun",
    "AgentSelfRepairPreview",
    "AgentTask",
    "ModelRouteDecision",
    "apply_review_decision",
    "build_agent_delegation_plan",
    "build_failure_records",
    "build_model_route_decision",
    "build_review_queue",
    "build_self_repair_preview",
]
