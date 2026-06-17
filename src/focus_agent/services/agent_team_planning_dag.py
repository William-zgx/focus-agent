from __future__ import annotations

from typing import Any

from focus_agent.core.agent_team import AgentTeamTaskRole

from .agent_team_planning_dag_contracts import (
    _apply_contract_defaults,
    _dedupe_values,
    _resource_claims_for_deliverable,
)
from .agent_team_planning_deliverables import (
    _debugging_deliverables,
    _implementation_deliverables,
    _research_deliverables,
    _review_deliverables,
    _verification_deliverables,
    _writing_deliverables,
)
from .agent_team_planning_deliverables import (
    _fallback_debug_deliverables as _fallback_debug_deliverables,
)
from .agent_team_planning_models import (
    AgentTeamPlanOptions,
    AgentTeamTaskDraft,
    MissionDeliverable,
    MissionProfile,
)
from .agent_team_planning_rules import (
    contains_cjk as _contains_cjk,
)
from .agent_team_planning_rules import (
    focused_goal as _focused_goal,
)
from .agent_team_planning_rules import (
    infer_focus as _infer_focus,
)


def classify_mission(goal: str, options: AgentTeamPlanOptions | None = None) -> MissionProfile:
    options = options or AgentTeamPlanOptions()
    base_goal = _focused_goal(goal, options)
    focus = _infer_focus(base_goal, options)
    normalized = base_goal.lower()
    language = "zh" if _contains_cjk(base_goal) else "en"
    has_frontend = any(
        marker in normalized for marker in ("frontend", "ui", "react", "web")
    ) or any(marker in base_goal for marker in ("前端", "界面", "页面", "交互"))
    has_backend = any(
        marker in normalized for marker in ("backend", "api", "database", "service", "server")
    ) or any(marker in base_goal for marker in ("后端", "接口", "数据库", "服务"))
    requires_code_change = focus in {"implementation", "debugging"}
    requires_research = focus in {"research", "writing"} or any(
        marker in normalized for marker in ("compare", "option", "strategy", "migration")
    )
    requires_verification = focus in {"implementation", "debugging", "verification"} or any(
        marker in normalized for marker in ("test", "verify", "regression")
    )
    requires_documentation = focus in {"research", "review", "writing"} or any(
        marker in normalized for marker in ("runbook", "guide", "docs", "document")
    )
    write_scope: list[str] = []
    if requires_code_change:
        if has_frontend and not has_backend:
            write_scope = ["apps/**", "packages/**", "tests/**"]
        else:
            write_scope = ["src/**", "tests/**"]
    elif focus == "writing":
        write_scope = ["docs/**"]
    risk_level = "high" if focus in {"debugging", "review"} else "medium"
    capability_requirements = _dedupe_values(
        [
            *(["research", "synthesis"] if requires_research else []),
            *(["code modification"] if requires_code_change else []),
            *(["test execution"] if requires_verification else []),
            *(["risk assessment"] if focus in {"review", "debugging"} else []),
            *(["technical writing"] if requires_documentation or focus == "writing" else []),
        ]
    )
    evidence_needs = _dedupe_values(
        [
            *(["source notes", "comparison rationale"] if requires_research else []),
            *(["changed files", "patch summary"] if requires_code_change else []),
            *(["test command and result"] if requires_verification else []),
            *(["finding rationale"] if focus == "review" else []),
        ]
    )
    return MissionProfile(
        goal=base_goal,
        focus=focus,
        language=language,
        risk_level=risk_level,
        has_backend=has_backend,
        has_frontend=has_frontend,
        requires_code_change=requires_code_change,
        requires_research=requires_research,
        requires_verification=requires_verification,
        requires_review=focus != "verification" or requires_code_change,
        requires_documentation=requires_documentation,
        write_scope=write_scope,
        capability_requirements=capability_requirements,
        evidence_needs=evidence_needs,
    )


def plan_deliverables(profile: MissionProfile) -> list[MissionDeliverable]:
    if profile.focus == "debugging":
        return _debugging_deliverables(profile)
    if profile.focus == "review":
        return _review_deliverables(profile)
    if profile.focus == "verification":
        return _verification_deliverables(profile)
    if profile.focus == "writing":
        return _writing_deliverables(profile)
    if profile.focus == "implementation":
        return _implementation_deliverables(profile)
    return _research_deliverables(profile)


def compile_mission_dag(
    profile: MissionProfile,
    deliverables: list[MissionDeliverable],
    *,
    max_tasks: int | None = None,
    plan_source: str = "model",
    context_refs: list[dict[str, Any]] | None = None,
    sandbox_id: str | None = None,
) -> list[AgentTeamTaskDraft]:
    limit = max(1, int(max_tasks or len(deliverables)))
    selected = list(deliverables[:limit])
    selected_keys = {item.key for item in selected}
    tasks: list[AgentTeamTaskDraft] = []
    for sort_order, deliverable in enumerate(selected, start=1):
        dependencies = [key for key in deliverable.depends_on if key in selected_keys]
        input_items = list(deliverable.input_items)
        for dependency in dependencies:
            upstream = next((item for item in selected if item.key == dependency), None)
            if upstream is not None:
                input_items.extend(upstream.output_items)
        input_items = _dedupe_values(input_items)
        output_items = _dedupe_values(deliverable.output_items or [deliverable.task_type])
        evidence = _dedupe_values(deliverable.evidence_required)
        tasks.append(
            AgentTeamTaskDraft(
                key=deliverable.key,
                title=deliverable.title,
                role=deliverable.role,
                goal=deliverable.goal,
                scope=list(deliverable.scope),
                dependencies=dependencies,
                acceptance_criteria=list(deliverable.acceptance_criteria),
                context_refs=list(context_refs or []),
                planning_rationale=deliverable.planning_rationale,
                sort_order=sort_order,
                task_type=deliverable.task_type,
                task_kind=deliverable.task_kind or deliverable.task_type,
                input_contract={"requires": input_items, "from_dependencies": dependencies},
                output_contract={"produces": output_items, "evidence": evidence},
                evidence_required=evidence,
                capability_requirements=_dedupe_values(deliverable.capability_requirements),
                risk_level=deliverable.risk_level or profile.risk_level,
                write_scope=list(deliverable.write_scope),
                resource_claims=_resource_claims_for_deliverable(
                    deliverable,
                    sandbox_id=sandbox_id,
                ),
                replan_policy={"replan_when": list(deliverable.replan_when)},
                plan_source=plan_source,
            )
        )
    return tasks


# Backwards-compatible seam for tests and callers that patched the old adaptive planner.
def _adaptive_task_specs(goal: str, *, focus: str, language: str) -> list[dict[str, Any]]:
    options = AgentTeamPlanOptions(focus=focus)
    profile = classify_mission(goal, options).model_copy(
        update={"language": language, "focus": focus}
    )
    deliverables = plan_deliverables(profile)
    tasks = compile_mission_dag(profile, deliverables, plan_source="model", context_refs=[])
    return [
        {
            "key": task.key,
            "title": task.title,
            "role": task.role.value,
            "goal": task.goal,
            "scope": task.scope,
            "dependencies": task.dependencies,
            "acceptance_criteria": task.acceptance_criteria,
            "planning_rationale": task.planning_rationale,
            "task_type": task.task_type,
            "task_kind": task.task_kind,
            "input_contract": task.input_contract,
            "output_contract": task.output_contract,
            "evidence_required": task.evidence_required,
            "capability_requirements": task.capability_requirements,
            "risk_level": task.risk_level,
            "write_scope": task.write_scope,
            "resource_claims": task.resource_claims,
            "replan_policy": task.replan_policy,
        }
        for task in tasks
    ]


def _fallback_task_specs(goal: str, *, focus: str) -> list[dict[str, Any]]:
    return _apply_contract_defaults(_fallback_task_specs_raw(goal, focus=focus))


def _fallback_task(
    *,
    key: str,
    title: str,
    role: str,
    goal: str,
    acceptance_criteria: list[str],
    planning_rationale: str,
    task_type: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "role": role,
        "goal": goal,
        **extra,
        "acceptance_criteria": list(acceptance_criteria),
        "planning_rationale": planning_rationale,
        "task_type": task_type,
    }


def _fallback_task_specs_raw(goal: str, *, focus: str) -> list[dict[str, Any]]:
    if focus == "debugging":
        return [
            _fallback_task(
                key="fallback-reproduce",
                title="Reproduce and isolate failure",
                role=AgentTeamTaskRole.VERIFIER.value,
                goal=f"Reproduce the failure, identify signals, and narrow likely causes for: {goal}",
                acceptance_criteria=[
                    "Observed symptoms, inputs, and failing checks are recorded.",
                    "Likely root-cause areas and unknowns are listed.",
                ],
                planning_rationale="Debugging fallback starts with evidence before changing code.",
                task_type="diagnosis",
                evidence=["reproduction steps", "failure output"],
                capabilities=["debugging", "test analysis"],
                risk="high",
            ),
            _fallback_task(
                key="fallback-fix",
                title="Apply targeted fix",
                role=AgentTeamTaskRole.BACKEND_EXECUTOR.value,
                goal=f"Make the smallest targeted fix for the isolated cause: {goal}",
                dependencies=["fallback-reproduce"],
                acceptance_criteria=[
                    "The fix is limited to the diagnosed cause.",
                    "Regression risk and touched files are reported.",
                ],
                planning_rationale="Only fix after reproducing enough evidence to avoid speculative edits.",
                task_type="implementation",
                input_items=["reproduction evidence"],
                output_items=["targeted fix", "changed files"],
                evidence=["patch summary"],
                capabilities=["code modification"],
                risk="high",
                write_scope=["src/**", "tests/**"],
                replan_when=["root cause differs from initial diagnosis"],
            ),
            _fallback_task(
                key="fallback-regression",
                title="Verify regression is fixed",
                role=AgentTeamTaskRole.VERIFIER.value,
                goal=f"Run focused checks proving the failure is fixed and no nearby regression remains: {goal}",
                dependencies=["fallback-fix"],
                acceptance_criteria=[
                    "The original failure path is covered.",
                    "Verification evidence includes command/result details.",
                ],
                planning_rationale="Debugging is not complete until the reproduced failure is verified fixed.",
                task_type="verification",
                input_items=["targeted fix"],
                output_items=["regression evidence"],
                evidence=["test command and result"],
                capabilities=["test execution"],
                risk="medium",
            ),
        ]
    if focus == "review":
        return [
            _fallback_task(
                key="fallback-review-scope",
                title="Map review scope",
                role=AgentTeamTaskRole.PLANNER.value,
                goal=f"Identify review boundaries, risk areas, and required evidence for: {goal}",
                acceptance_criteria=[
                    "Review scope and exclusions are explicit.",
                    "High-risk areas are prioritized.",
                ],
                planning_rationale="Review missions need clear scope before critique.",
                task_type="coordination",
                output_items=["review checklist"],
            ),
            _fallback_task(
                key="fallback-risk-review",
                title="Review risks and gaps",
                role=AgentTeamTaskRole.REVIEWER.value,
                goal=f"Assess correctness, regressions, security, and maintainability risks for: {goal}",
                dependencies=["fallback-review-scope"],
                acceptance_criteria=[
                    "Blocking and non-blocking findings are separated.",
                    "Each finding names supporting evidence or uncertainty.",
                ],
                planning_rationale="The core review task focuses on evidence-backed findings.",
                task_type="review",
                evidence=["findings with rationale"],
                capabilities=["code review", "risk assessment"],
                risk="high",
            ),
            _fallback_task(
                key="fallback-review-summary",
                title="Summarize review decision",
                role=AgentTeamTaskRole.WRITER.value,
                goal=f"Produce a concise review decision and follow-up list for: {goal}",
                dependencies=["fallback-risk-review"],
                acceptance_criteria=[
                    "Decision is actionable and tied to findings.",
                    "Follow-ups are prioritized.",
                ],
                planning_rationale="Review output must be consumable by the requester.",
                task_type="documentation",
                input_items=["review findings"],
                output_items=["review report"],
                capabilities=["technical writing"],
            ),
        ]
    if focus == "verification":
        return [
            _fallback_task(
                key="fallback-evidence-plan",
                title="Choose verification evidence",
                role=AgentTeamTaskRole.PLANNER.value,
                goal=f"Define the minimum checks and pass criteria for: {goal}",
                acceptance_criteria=[
                    "Required checks and data are listed.",
                    "Pass/fail criteria are explicit.",
                ],
                planning_rationale="Verification fallback should optimize for meaningful evidence.",
                task_type="coordination",
                output_items=["verification checklist"],
            ),
            _fallback_task(
                key="fallback-run-checks",
                title="Run checks",
                role=AgentTeamTaskRole.VERIFIER.value,
                goal=f"Execute the selected checks and collect reproducible evidence for: {goal}",
                dependencies=["fallback-evidence-plan"],
                acceptance_criteria=[
                    "Commands, inputs, and results are recorded.",
                    "Failures include likely causes or next checks.",
                ],
                planning_rationale="Verifier owns the evidence-producing step.",
                task_type="verification",
                evidence=["command output", "manual check notes"],
                capabilities=["test execution"],
            ),
            _fallback_task(
                key="fallback-verdict",
                title="Issue verification verdict",
                role=AgentTeamTaskRole.REVIEWER.value,
                goal=f"Decide whether evidence supports pass, block, or more testing for: {goal}",
                dependencies=["fallback-run-checks"],
                acceptance_criteria=[
                    "Verdict references evidence and gaps.",
                    "Residual risks are listed.",
                ],
                planning_rationale="A separate verdict avoids confusing raw evidence with recommendation.",
                task_type="review",
                input_items=["verification evidence"],
                output_items=["verification verdict"],
            ),
        ]
    if focus == "writing":
        return [
            _fallback_task(
                key="fallback-outline",
                title="Outline deliverable",
                role=AgentTeamTaskRole.PLANNER.value,
                goal=f"Define audience, structure, and source material for: {goal}",
                acceptance_criteria=[
                    "Audience, tone, and required sections are clear.",
                    "Unknowns and source gaps are listed.",
                ],
                planning_rationale="Writing work benefits from outline-first planning.",
                task_type="coordination",
                output_items=["outline"],
                capabilities=["content planning"],
            ),
            _fallback_task(
                key="fallback-draft",
                title="Draft content",
                role=AgentTeamTaskRole.WRITER.value,
                goal=f"Write the requested deliverable using the outline and available evidence: {goal}",
                dependencies=["fallback-outline"],
                acceptance_criteria=[
                    "Draft covers required sections.",
                    "Claims are caveated when evidence is missing.",
                ],
                planning_rationale="The writer produces the primary artifact after scope is clear.",
                task_type="documentation",
                input_items=["outline", "source material"],
                output_items=["draft deliverable"],
                capabilities=["technical writing"],
                write_scope=["docs/**"],
            ),
            _fallback_task(
                key="fallback-edit",
                title="Edit for accuracy and usability",
                role=AgentTeamTaskRole.REVIEWER.value,
                goal=f"Review the draft for clarity, accuracy, gaps, and actionability: {goal}",
                dependencies=["fallback-draft"],
                acceptance_criteria=[
                    "Corrections and gaps are identified.",
                    "Final recommendation is clear.",
                ],
                planning_rationale="Writing deliverables still need independent editorial review.",
                task_type="review",
                input_items=["draft deliverable"],
                output_items=["editorial review"],
            ),
        ]
    if focus == "research":
        return [
            _fallback_task(
                key="fallback-questions",
                title="Frame research questions",
                role=AgentTeamTaskRole.PLANNER.value,
                goal=f"Turn the mission into answerable research questions and constraints: {goal}",
                acceptance_criteria=[
                    "Key questions and decision criteria are listed.",
                    "Assumptions and missing inputs are explicit.",
                ],
                planning_rationale="Research fallback should avoid jumping straight to conclusions.",
                task_type="coordination",
                output_items=["research questions"],
            ),
            _fallback_task(
                key="fallback-research",
                title="Collect findings",
                role=AgentTeamTaskRole.PLANNER.value,
                goal=f"Gather and compare evidence, options, and risks for: {goal}",
                dependencies=["fallback-questions"],
                acceptance_criteria=[
                    "Findings distinguish evidence from assumptions.",
                    "Conflicts, gaps, and confidence are recorded.",
                ],
                planning_rationale="The core research task builds the evidence base.",
                task_type="research",
                evidence=["source notes", "comparison rationale"],
                capabilities=["research", "synthesis"],
            ),
            _fallback_task(
                key="fallback-synthesis",
                title="Synthesize answer",
                role=AgentTeamTaskRole.WRITER.value,
                goal=f"Turn findings into a concise answer or plan for: {goal}",
                dependencies=["fallback-research"],
                acceptance_criteria=[
                    "Answer covers the main questions.",
                    "Caveats and next steps are included.",
                ],
                planning_rationale="Research needs a user-facing synthesis, not just raw notes.",
                task_type="documentation",
                input_items=["research findings"],
                output_items=["synthesized answer"],
            ),
        ]
    return [
        _fallback_task(
            key="fallback-architecture",
            title="Define implementation boundary",
            role=AgentTeamTaskRole.ARCHITECT.value,
            goal=f"Clarify touched areas, dependencies, and acceptance checks for: {goal}",
            acceptance_criteria=[
                "Scope and acceptance checks are explicit.",
                "Implementation risks and write boundaries are listed.",
            ],
            planning_rationale="Implementation fallback starts by reducing write-conflict risk.",
            task_type="coordination",
            output_items=["implementation checklist"],
            risk="medium",
        ),
        _fallback_task(
            key="fallback-implement",
            title="Implement focused slice",
            role=AgentTeamTaskRole.BACKEND_EXECUTOR.value,
            goal=f"Implement the smallest verifiable slice for: {goal}",
            dependencies=["fallback-architecture"],
            acceptance_criteria=[
                "Changes stay within the requested scope.",
                "Outputs name changed files and known risks.",
            ],
            planning_rationale="Execution is scoped by the architecture task.",
            task_type="implementation",
            input_items=["implementation checklist"],
            output_items=["patch summary"],
            evidence=["changed files"],
            capabilities=["code modification"],
            write_scope=["src/**", "tests/**"],
            replan_when=["required write scope expands"],
        ),
        _fallback_task(
            key="fallback-verify",
            title="Verify focused slice",
            role=AgentTeamTaskRole.VERIFIER.value,
            goal=f"Run focused verification for the implemented slice: {goal}",
            dependencies=["fallback-implement"],
            acceptance_criteria=[
                "Verification evidence includes commands and results.",
                "Unverified risks are called out.",
            ],
            planning_rationale="Implementation fallback ends with evidence, not only code changes.",
            task_type="verification",
            input_items=["patch summary"],
            output_items=["verification evidence"],
            evidence=["test command and result"],
            capabilities=["test execution"],
        ),
    ]


__all__ = [
    "MissionDeliverable",
    "MissionProfile",
    "classify_mission",
    "compile_mission_dag",
    "plan_deliverables",
]
