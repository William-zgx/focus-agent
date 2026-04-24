from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Literal
from uuid import uuid4

from pydantic import Field

from .agent_roles import AgentRole, normalize_agent_role
from .config import Settings
from .core.types import StateModel


AgentTaskLedgerStatus = Literal["disabled", "planned", "running", "completed", "blocked", "rejected"]
AgentTaskStatus = Literal["planned", "running", "blocked", "completed", "rejected", "skipped"]
DelegatedArtifactKind = Literal[
    "plan",
    "patch_summary",
    "evidence",
    "critic_verdict",
    "memory_candidate",
    "tool_route_evidence",
    "context_ref",
    "final_synthesis",
]
DelegatedArtifactStatus = Literal["draft", "accepted", "rejected", "needs_review"]
CriticVerdict = Literal["pass", "reject", "retry", "needs_review", "skipped"]


class AgentTaskNode(StateModel):
    task_id: str
    parent_task_id: str | None = None
    role: AgentRole
    goal: str
    status: AgentTaskStatus = "planned"
    acceptance_criteria: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    retry_count: int = 0


class AgentTaskLedger(StateModel):
    enabled: bool = False
    status: AgentTaskLedgerStatus = "disabled"
    tasks: list[AgentTaskNode] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class DelegatedArtifact(StateModel):
    artifact_id: str
    task_id: str | None = None
    role: AgentRole = AgentRole.EXECUTOR
    kind: DelegatedArtifactKind = "evidence"
    title: str
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    status: DelegatedArtifactStatus = "draft"


class ArtifactSynthesisResult(StateModel):
    enabled: bool = False
    artifact_id: str | None = None
    accepted_artifact_ids: list[str] = Field(default_factory=list)
    skipped_artifact_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    blocked: bool = False
    reason: str = ""


class CriticGateResult(StateModel):
    enabled: bool = False
    enforce: bool = False
    verdict: CriticVerdict = "skipped"
    accepted_artifact_ids: list[str] = Field(default_factory=list)
    rejected_artifact_ids: list[str] = Field(default_factory=list)
    retry_task_ids: list[str] = Field(default_factory=list)
    reason: str = ""


def build_task_ledger_policy(settings: Settings | Any) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings, "agent_task_ledger_enabled", False)),
        "artifact_synthesis_enabled": bool(getattr(settings, "agent_artifact_synthesis_enabled", False)),
        "critic_gate_enabled": bool(getattr(settings, "agent_critic_gate_enabled", False)),
        "critic_gate_enforce": bool(getattr(settings, "agent_critic_gate_enforce", False)),
        "default_off_legacy_safe": True,
    }


def build_agent_task_ledger(
    *,
    settings: Settings | Any,
    delegation_plan: dict[str, Any] | None = None,
) -> AgentTaskLedger:
    if not bool(getattr(settings, "agent_task_ledger_enabled", False)):
        return AgentTaskLedger(enabled=False, status="disabled")

    raw_tasks = delegation_plan.get("tasks") if isinstance(delegation_plan, dict) else None
    tasks: list[AgentTaskNode] = []
    now = _utc_now()
    if isinstance(raw_tasks, list):
        for index, raw in enumerate(raw_tasks):
            if not isinstance(raw, dict):
                continue
            role = normalize_agent_role(str(raw.get("role") or AgentRole.EXECUTOR.value))
            task_id = str(raw.get("task_id") or f"task-{index + 1}-{role.value}")
            tasks.append(
                AgentTaskNode(
                    task_id=task_id,
                    parent_task_id=_optional_str(raw.get("parent_task_id")),
                    role=role,
                    goal=str(raw.get("goal") or raw.get("task_slice") or f"{role.value} delegated task"),
                    status=_task_status_from_run(delegation_plan, task_id),
                    acceptance_criteria=[str(item) for item in raw.get("acceptance_criteria") or []],
                    retry_count=int(raw.get("retry_count") or 0),
                )
            )
    if not tasks:
        tasks.append(
            AgentTaskNode(
                task_id="task-1-executor",
                role=AgentRole.EXECUTOR,
                goal="Execute the user request.",
                acceptance_criteria=["Produce a traceable artifact."],
            )
        )
    edges = [
        {"from": task.parent_task_id, "to": task.task_id}
        for task in tasks
        if task.parent_task_id
    ]
    return AgentTaskLedger(
        enabled=True,
        status="planned",
        tasks=tasks,
        edges=edges,
        created_at=now,
        updated_at=now,
    )


def build_delegated_artifacts(
    *,
    ledger: dict[str, Any] | AgentTaskLedger | None,
    delegation_plan: dict[str, Any] | None = None,
    memory_curator_decision: dict[str, Any] | None = None,
    tool_route_plan: dict[str, Any] | None = None,
    context_artifact_refs: Iterable[dict[str, Any]] = (),
) -> list[DelegatedArtifact]:
    ledger_model = ledger if isinstance(ledger, AgentTaskLedger) else AgentTaskLedger.model_validate(ledger or {})
    if not ledger_model.enabled:
        return []

    artifacts: list[DelegatedArtifact] = []
    task_by_id = {task.task_id: task for task in ledger_model.tasks}
    runs_by_task = _runs_by_task(delegation_plan)
    for task in ledger_model.tasks:
        run = runs_by_task.get(task.task_id, {})
        kind = _artifact_kind_for_role(task.role)
        status: DelegatedArtifactStatus = "accepted" if str(run.get("status") or "") == "completed" else "draft"
        artifact = DelegatedArtifact(
            artifact_id=f"artifact-{task.task_id}-{kind}",
            task_id=task.task_id,
            role=task.role,
            kind=kind,
            title=f"{task.role.value} {kind.replace('_', ' ')}",
            summary=str(run.get("artifacts", [{}])[0].get("summary") if isinstance(run.get("artifacts"), list) and run.get("artifacts") else task.goal),
            payload={
                "goal": task.goal,
                "acceptance_criteria": task.acceptance_criteria,
                "run": run,
            },
            status=status,
        )
        artifacts.append(artifact)
        task_by_id[task.task_id].artifact_ids.append(artifact.artifact_id)

    if memory_curator_decision:
        artifacts.append(
            DelegatedArtifact(
                artifact_id=f"artifact-memory-{uuid4().hex[:10]}",
                task_id=_task_id_for_role(ledger_model, AgentRole.MEMORY_CURATOR),
                role=AgentRole.MEMORY_CURATOR,
                kind="memory_candidate",
                title="Memory promotion candidate",
                summary="Memory Curator decision captured as a delegated artifact.",
                payload=memory_curator_decision,
                status="needs_review" if memory_curator_decision.get("conflicts") else "accepted",
            )
        )
    if tool_route_plan:
        artifacts.append(
            DelegatedArtifact(
                artifact_id=f"artifact-tool-route-{uuid4().hex[:10]}",
                task_id=_task_id_for_role(ledger_model, AgentRole.SKILL_SCOUT),
                role=AgentRole.SKILL_SCOUT,
                kind="tool_route_evidence",
                title="Tool route evidence",
                summary="Tool Router allow/deny plan captured as evidence.",
                payload=tool_route_plan,
                status="needs_review" if tool_route_plan.get("denied_tools") else "accepted",
            )
        )
    for index, ref in enumerate(context_artifact_refs):
        artifacts.append(
            DelegatedArtifact(
                artifact_id=str(ref.get("artifact_id") or f"artifact-context-{index + 1}"),
                task_id=_task_id_for_role(ledger_model, AgentRole.EXECUTOR),
                role=AgentRole.EXECUTOR,
                kind="context_ref",
                title=str(ref.get("title") or "Context artifact reference"),
                summary=str(ref.get("summary") or "Context Engineering v2 artifact reference."),
                payload=dict(ref),
                status="accepted",
            )
        )
    return artifacts


def synthesize_delegated_artifacts(
    *,
    settings: Settings | Any,
    artifacts: Iterable[dict[str, Any] | DelegatedArtifact],
    critic_gate_result: dict[str, Any] | CriticGateResult | None = None,
) -> ArtifactSynthesisResult:
    if not bool(getattr(settings, "agent_artifact_synthesis_enabled", False)):
        return ArtifactSynthesisResult(enabled=False, reason="AGENT_ARTIFACT_SYNTHESIS_ENABLED is off.")

    critic = critic_gate_result if isinstance(critic_gate_result, CriticGateResult) else CriticGateResult.model_validate(critic_gate_result or {})
    if critic.enforce and critic.verdict in {"reject", "retry", "needs_review"}:
        return ArtifactSynthesisResult(
            enabled=True,
            blocked=True,
            reason=f"Critic gate blocked synthesis with verdict={critic.verdict}.",
            skipped_artifact_ids=list(critic.rejected_artifact_ids),
        )

    normalized = _normalize_artifacts(artifacts)
    accepted = [
        item
        for item in normalized
        if item.status == "accepted" and item.kind != "critic_verdict"
    ]
    skipped = [item.artifact_id for item in normalized if item not in accepted]
    summary = "\n".join(f"- {item.title}: {item.summary}" for item in accepted) or "No accepted delegated artifacts."
    return ArtifactSynthesisResult(
        enabled=True,
        artifact_id=f"artifact-final-synthesis-{uuid4().hex[:10]}",
        accepted_artifact_ids=[item.artifact_id for item in accepted],
        skipped_artifact_ids=skipped,
        summary=summary,
        blocked=False,
        reason="Synthesized from accepted delegated artifacts.",
    )


def evaluate_critic_gate(
    *,
    settings: Settings | Any,
    ledger: dict[str, Any] | AgentTaskLedger | None,
    artifacts: Iterable[dict[str, Any] | DelegatedArtifact],
) -> CriticGateResult:
    enabled = bool(getattr(settings, "agent_critic_gate_enabled", False))
    enforce = bool(getattr(settings, "agent_critic_gate_enforce", False))
    if not enabled:
        return CriticGateResult(enabled=False, enforce=enforce, verdict="skipped", reason="AGENT_CRITIC_GATE_ENABLED is off.")

    normalized = _normalize_artifacts(artifacts)
    rejected = [item.artifact_id for item in normalized if item.status == "rejected"]
    needs_review = [item.artifact_id for item in normalized if item.status == "needs_review"]
    accepted = [item.artifact_id for item in normalized if item.status == "accepted"]
    ledger_model = ledger if isinstance(ledger, AgentTaskLedger) else AgentTaskLedger.model_validate(ledger or {})
    retry_tasks: list[str] = []
    verdict: CriticVerdict = "pass"
    reason = "All accepted artifacts can be synthesized."
    if rejected:
        verdict = "retry"
        retry_tasks = _retry_task_ids(ledger_model, rejected, normalized)
        if not retry_tasks:
            verdict = "reject"
        reason = "Rejected delegated artifacts require retry or block synthesis."
    elif needs_review:
        verdict = "needs_review"
        reason = "Some delegated artifacts require human review before synthesis."

    return CriticGateResult(
        enabled=True,
        enforce=enforce,
        verdict=verdict,
        accepted_artifact_ids=accepted,
        rejected_artifact_ids=[*rejected, *needs_review],
        retry_task_ids=retry_tasks,
        reason=reason,
    )


def apply_critic_retry_tasks(
    *,
    ledger: dict[str, Any] | AgentTaskLedger | None,
    critic_gate_result: dict[str, Any] | CriticGateResult | None,
) -> AgentTaskLedger:
    ledger_model = ledger if isinstance(ledger, AgentTaskLedger) else AgentTaskLedger.model_validate(ledger or {})
    critic = critic_gate_result if isinstance(critic_gate_result, CriticGateResult) else CriticGateResult.model_validate(critic_gate_result or {})
    if not ledger_model.enabled or not critic.retry_task_ids:
        return ledger_model
    retry_targets = set(critic.retry_task_ids)
    tasks: list[AgentTaskNode] = []
    for task in ledger_model.tasks:
        if task.task_id not in retry_targets or task.retry_count >= 1:
            tasks.append(task)
            continue
        retry_id = f"{task.task_id}-retry-1"
        tasks.append(task.model_copy(update={"status": "rejected"}))
        tasks.append(
            AgentTaskNode(
                task_id=retry_id,
                parent_task_id=task.task_id,
                role=task.role,
                goal=f"Retry after Critic rejection: {task.goal}",
                status="planned",
                acceptance_criteria=task.acceptance_criteria,
                retry_count=task.retry_count + 1,
            )
        )
    edges = [{"from": task.parent_task_id, "to": task.task_id} for task in tasks if task.parent_task_id]
    return ledger_model.model_copy(update={"tasks": tasks, "edges": edges, "updated_at": _utc_now()})


def _normalize_artifacts(artifacts: Iterable[dict[str, Any] | DelegatedArtifact]) -> list[DelegatedArtifact]:
    return [item if isinstance(item, DelegatedArtifact) else DelegatedArtifact.model_validate(item) for item in artifacts]


def _artifact_kind_for_role(role: AgentRole) -> DelegatedArtifactKind:
    if role == AgentRole.PLANNER:
        return "plan"
    if role == AgentRole.CRITIC:
        return "critic_verdict"
    if role == AgentRole.MEMORY_CURATOR:
        return "memory_candidate"
    if role == AgentRole.SKILL_SCOUT:
        return "tool_route_evidence"
    if role == AgentRole.EXECUTOR:
        return "patch_summary"
    return "evidence"


def _runs_by_task(delegation_plan: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(delegation_plan, dict):
        return {}
    return {
        str(raw.get("task_id")): dict(raw)
        for raw in delegation_plan.get("runs") or []
        if isinstance(raw, dict) and raw.get("task_id")
    }


def _task_status_from_run(delegation_plan: dict[str, Any] | None, task_id: str) -> AgentTaskStatus:
    run = _runs_by_task(delegation_plan).get(task_id)
    if not run:
        return "planned"
    status = str(run.get("status") or "planned")
    if status in {"running", "completed", "failed", "skipped", "needs_review"}:
        if status == "failed":
            return "rejected"
        if status == "needs_review":
            return "blocked"
        return status  # type: ignore[return-value]
    return "planned"


def _task_id_for_role(ledger: AgentTaskLedger, role: AgentRole) -> str | None:
    for task in ledger.tasks:
        if task.role == role:
            return task.task_id
    return ledger.tasks[0].task_id if ledger.tasks else None


def _retry_task_ids(
    ledger: AgentTaskLedger,
    rejected_artifact_ids: list[str],
    artifacts: list[DelegatedArtifact],
) -> list[str]:
    rejected = set(rejected_artifact_ids)
    task_by_id = {task.task_id: task for task in ledger.tasks}
    retry_ids: list[str] = []
    for artifact in artifacts:
        if artifact.artifact_id not in rejected or not artifact.task_id:
            continue
        task = task_by_id.get(artifact.task_id)
        if task and task.retry_count < 1:
            retry_ids.append(task.task_id)
    return list(dict.fromkeys(retry_ids))


def _optional_str(value: Any) -> str | None:
    return str(value) if value else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "AgentTaskLedger",
    "AgentTaskNode",
    "ArtifactSynthesisResult",
    "CriticGateResult",
    "DelegatedArtifact",
    "apply_critic_retry_tasks",
    "build_agent_task_ledger",
    "build_delegated_artifacts",
    "build_task_ledger_policy",
    "evaluate_critic_gate",
    "synthesize_delegated_artifacts",
]
