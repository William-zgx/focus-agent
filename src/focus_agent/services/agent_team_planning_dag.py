from __future__ import annotations

from typing import Any

from focus_agent.core.agent_team import AgentTeamTaskRole

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
                resource_claims=_resource_claims_for_deliverable(deliverable),
                replan_policy={"replan_when": list(deliverable.replan_when)},
                plan_source=plan_source,
            )
        )
    return tasks


def _deliverable(
    profile: MissionProfile,
    *,
    key: str,
    title: str,
    role: AgentTeamTaskRole,
    goal: str,
    task_type: str,
    planning_rationale: str,
    depends_on: list[str] | None = None,
    input_items: list[str] | None = None,
    output_items: list[str] | None = None,
    evidence_required: list[str] | None = None,
    capability_requirements: list[str] | None = None,
    risk_level: str | None = None,
    write_scope: list[str] | None = None,
    replan_when: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> MissionDeliverable:
    return MissionDeliverable(
        key=key,
        title=title,
        role=role,
        goal=goal,
        task_type=task_type,
        task_kind=task_type,
        depends_on=list(depends_on or []),
        input_items=list(input_items or []),
        output_items=list(output_items or [task_type]),
        evidence_required=list(evidence_required or []),
        capability_requirements=list(capability_requirements or []),
        risk_level=risk_level or profile.risk_level,
        write_scope=list(write_scope or []),
        resource_claims=_resource_claims_for_scope(write_scope or []),
        replan_when=list(replan_when or []),
        acceptance_criteria=list(acceptance_criteria or []),
        planning_rationale=planning_rationale,
    )


def _mission_text(profile: MissionProfile) -> str:
    return profile.goal


def _research_deliverables(profile: MissionProfile) -> list[MissionDeliverable]:
    goal = _mission_text(profile)
    if profile.language == "zh":
        return [
            _deliverable(
                profile,
                key="mission-brief",
                title="确认目标与边界",
                role=AgentTeamTaskRole.PLANNER,
                goal=f"澄清目标、受众、约束和成功标准：{goal}",
                task_type="coordination",
                output_items=["mission brief", "decision questions"],
                capability_requirements=["scope analysis"],
                planning_rationale="先收敛边界，避免后续研究和产出方向发散。",
                acceptance_criteria=[
                    "明确产物范围、默认假设和不确定信息。",
                    "列出后续任务需要验证的关键问题。",
                ],
            ),
            _deliverable(
                profile,
                key="mission-research",
                title="调研关键决策",
                role=AgentTeamTaskRole.PLANNER,
                goal=f"围绕目标收集并比较关键信息、选项和约束：{goal}",
                task_type="research",
                depends_on=["mission-brief"],
                input_items=["mission brief", "decision questions"],
                output_items=["research findings", "option comparison"],
                evidence_required=["source notes", "comparison rationale"],
                capability_requirements=["research", "synthesis"],
                planning_rationale="该目标以研究和方案质量为核心，需要先建立证据底座。",
                acceptance_criteria=[
                    "覆盖主要决策维度，并区分事实、建议和假设。",
                    "记录可复查的依据、冲突信息和风险点。",
                ],
            ),
            _deliverable(
                profile,
                key="mission-synthesis",
                title="产出可执行方案",
                role=AgentTeamTaskRole.WRITER,
                goal=f"把调研结果整理成结构清晰、可直接使用的最终方案：{goal}",
                task_type="documentation",
                depends_on=["mission-research"],
                input_items=["research findings", "option comparison"],
                output_items=["synthesized deliverable"],
                capability_requirements=["technical writing"],
                planning_rationale="把分散证据转成用户真正需要的可交付内容。",
                acceptance_criteria=[
                    "方案覆盖用户目标中的主要部分，并给出优先级或选择建议。",
                    "输出包含可执行步骤、注意事项和可替代选项。",
                ],
            ),
            _deliverable(
                profile,
                key="mission-review",
                title="审查证据与风险",
                role=AgentTeamTaskRole.REVIEWER,
                goal=f"检查最终方案的完整性、风险、遗漏和可执行性：{goal}",
                task_type="review",
                depends_on=["mission-synthesis"],
                input_items=["synthesized deliverable", "research findings"],
                output_items=["review verdict"],
                evidence_required=["risk notes"],
                capability_requirements=["risk assessment"],
                planning_rationale="合并前需要独立检查证据和风险，避免只有产出没有把关。",
                acceptance_criteria=[
                    "指出缺失信息、潜在风险和需要用户确认的问题。",
                    "给出是否可交付或需要补充研究的建议。",
                ],
            ),
        ]
    return [
        _deliverable(
            profile,
            key="mission-brief",
            title="Clarify mission boundaries",
            role=AgentTeamTaskRole.PLANNER,
            goal=f"Clarify scope, audience, constraints, and success criteria for: {goal}",
            task_type="coordination",
            output_items=["mission brief", "decision questions"],
            capability_requirements=["scope analysis"],
            planning_rationale="The first deliverable fixes the mission boundary and the questions downstream work must answer.",
            acceptance_criteria=[
                "Scope, assumptions, and success checks are explicit.",
                "Open questions for downstream tasks are listed.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-research",
            title="Research key decisions",
            role=AgentTeamTaskRole.PLANNER,
            goal=f"Gather and compare key facts, options, constraints, and risks for: {goal}",
            task_type="research",
            depends_on=["mission-brief"],
            input_items=["mission brief", "decision questions"],
            output_items=["research findings", "option comparison"],
            evidence_required=["source notes", "comparison rationale"],
            capability_requirements=["research", "synthesis"],
            planning_rationale="The research deliverable produces the evidence base required before any recommendation can be written.",
            acceptance_criteria=[
                "Main decision dimensions are covered.",
                "Evidence, conflicts, and assumptions are captured.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-synthesis",
            title="Synthesize deliverable",
            role=AgentTeamTaskRole.WRITER,
            goal=f"Turn the research into a clear, directly usable deliverable for: {goal}",
            task_type="documentation",
            depends_on=["mission-research"],
            input_items=["research findings", "option comparison"],
            output_items=["synthesized deliverable"],
            capability_requirements=["technical writing"],
            planning_rationale="The synthesis deliverable converts evidence into the user-facing answer.",
            acceptance_criteria=[
                "The deliverable covers the main requested sections.",
                "Recommendations, steps, caveats, and alternatives are included.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-review",
            title="Review evidence and risks",
            role=AgentTeamTaskRole.REVIEWER,
            goal=f"Review completeness, risks, omissions, and handoff quality for: {goal}",
            task_type="review",
            depends_on=["mission-synthesis"],
            input_items=["synthesized deliverable", "research findings"],
            output_items=["review verdict"],
            evidence_required=["risk notes"],
            capability_requirements=["risk assessment"],
            planning_rationale="A separate review deliverable checks whether the answer is supported by evidence.",
            acceptance_criteria=[
                "Missing information and risks are called out.",
                "A clear deliver/request-changes recommendation is provided.",
            ],
        ),
    ]


def _implementation_deliverables(profile: MissionProfile) -> list[MissionDeliverable]:
    goal = _mission_text(profile)
    execution_role = (
        AgentTeamTaskRole.FRONTEND_EXECUTOR
        if profile.has_frontend and not profile.has_backend
        else AgentTeamTaskRole.BACKEND_EXECUTOR
    )
    execution_title = (
        "Implement frontend experience"
        if execution_role == AgentTeamTaskRole.FRONTEND_EXECUTOR
        else "Implement core change"
    )
    if profile.language == "zh":
        return [
            _deliverable(
                profile,
                key="mission-architecture",
                title="拆解实现边界",
                role=AgentTeamTaskRole.ARCHITECT,
                goal=f"定义实现范围、依赖关系、验收标准和风险：{goal}",
                task_type="coordination",
                output_items=["implementation contract", "write boundaries"],
                capability_requirements=["systems analysis"],
                risk_level="medium",
                planning_rationale="实现类目标需要先拆清边界和依赖，避免多 Agent 写入冲突。",
                acceptance_criteria=[
                    "明确哪些文件或模块会被触达。",
                    "列出验收标准、依赖和回滚风险。",
                ],
            ),
            _deliverable(
                profile,
                key="mission-implementation",
                title="实现核心改动",
                role=execution_role,
                goal=f"按明确边界实现最小可验证改动：{goal}",
                task_type="implementation",
                depends_on=["mission-architecture"],
                input_items=["implementation contract", "write boundaries"],
                output_items=["patch summary", "changed files"],
                evidence_required=["changed files"],
                capability_requirements=["code modification"],
                risk_level="high",
                write_scope=profile.write_scope,
                replan_when=[
                    "required write scope expands",
                    "implementation contract is incomplete",
                ],
                planning_rationale="核心执行任务负责把目标转成可验证产物。",
                acceptance_criteria=[
                    "改动保持在任务范围内，并遵循现有架构风格。",
                    "产物记录 changed files、关键决策和已知风险。",
                ],
            ),
            _deliverable(
                profile,
                key="mission-verification",
                title="验证行为与回归",
                role=AgentTeamTaskRole.VERIFIER,
                goal=f"运行与改动相关的测试、构建或手动检查：{goal}",
                task_type="verification",
                depends_on=["mission-implementation"],
                input_items=["patch summary", "changed files"],
                output_items=["verification evidence"],
                evidence_required=["test command and result"],
                capability_requirements=["test execution"],
                planning_rationale="执行结果必须带证据，才能进入合并建议。",
                acceptance_criteria=[
                    "测试证据包含命令、结果和失败时的原因。",
                    "覆盖主要用户路径或风险路径。",
                ],
            ),
            _deliverable(
                profile,
                key="mission-review",
                title="审查实现风险",
                role=AgentTeamTaskRole.REVIEWER,
                goal=f"审查实现质量、架构风险、回归风险和未决问题：{goal}",
                task_type="review",
                depends_on=["mission-verification"],
                input_items=["patch summary", "verification evidence"],
                output_items=["merge recommendation"],
                evidence_required=["review findings"],
                capability_requirements=["risk assessment"],
                planning_rationale="最后由独立审查任务决定是否具备交付条件。",
                acceptance_criteria=[
                    "列出阻塞问题、非阻塞风险和建议动作。",
                    "基于证据给出合并或继续修改建议。",
                ],
            ),
        ]
    return [
        _deliverable(
            profile,
            key="mission-architecture",
            title="Decompose implementation scope",
            role=AgentTeamTaskRole.ARCHITECT,
            goal=f"Define implementation scope, dependencies, acceptance criteria, and risks for: {goal}",
            task_type="coordination",
            output_items=["implementation contract", "write boundaries"],
            capability_requirements=["systems analysis"],
            risk_level="medium",
            planning_rationale="The architecture deliverable defines the write contract and dependency boundary before code changes begin.",
            acceptance_criteria=[
                "Touched modules or files are identified.",
                "Acceptance criteria, dependencies, and rollback risks are listed.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-implementation",
            title=execution_title,
            role=execution_role,
            goal=f"Implement the smallest verifiable slice for: {goal}",
            task_type="implementation",
            depends_on=["mission-architecture"],
            input_items=["implementation contract", "write boundaries"],
            output_items=["patch summary", "changed files"],
            evidence_required=["changed files"],
            capability_requirements=["code modification"],
            risk_level="high",
            write_scope=profile.write_scope,
            replan_when=["required write scope expands", "implementation contract is incomplete"],
            planning_rationale="The implementation deliverable consumes the contract and produces a reviewable patch artifact.",
            acceptance_criteria=[
                "Changes stay within scope and follow existing architecture.",
                "Outputs include changed files, decisions, and known risks.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-verification",
            title="Verify behavior and regressions",
            role=AgentTeamTaskRole.VERIFIER,
            goal=f"Run relevant tests, builds, or manual checks for: {goal}",
            task_type="verification",
            depends_on=["mission-implementation"],
            input_items=["patch summary", "changed files"],
            output_items=["verification evidence"],
            evidence_required=["test command and result"],
            capability_requirements=["test execution"],
            planning_rationale="The verification deliverable proves the patch against the agreed acceptance evidence.",
            acceptance_criteria=[
                "Evidence includes commands, results, and failure reasons.",
                "The main user or risk path is covered.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-review",
            title="Review implementation risk",
            role=AgentTeamTaskRole.REVIEWER,
            goal=f"Review implementation quality, architecture risk, regression risk, and open questions for: {goal}",
            task_type="review",
            depends_on=["mission-verification"],
            input_items=["patch summary", "verification evidence"],
            output_items=["merge recommendation"],
            evidence_required=["review findings"],
            capability_requirements=["risk assessment"],
            planning_rationale="The review deliverable decides whether the evidenced patch is ready to deliver.",
            acceptance_criteria=[
                "Blocking issues, residual risks, and suggested action are listed.",
                "Merge or request-changes advice is based on evidence.",
            ],
        ),
    ]


def _debugging_deliverables(profile: MissionProfile) -> list[MissionDeliverable]:
    goal = _mission_text(profile)
    return [
        _deliverable(
            profile,
            key="mission-reproduce",
            title="Reproduce failure",
            role=AgentTeamTaskRole.VERIFIER,
            goal=f"Reproduce the failure and capture symptoms, inputs, logs, and failing checks for: {goal}",
            task_type="diagnosis",
            output_items=["reproduction evidence", "failure signals"],
            evidence_required=["reproduction steps", "failure output"],
            capability_requirements=["debugging", "test analysis"],
            risk_level="high",
            planning_rationale="Debugging starts with observed evidence rather than speculative fixes.",
            acceptance_criteria=[
                "The failure condition is reproducible or the limits of reproduction are documented.",
                "Relevant logs, commands, inputs, and expected behavior are captured.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-root-cause",
            title="Analyze root cause",
            role=AgentTeamTaskRole.ARCHITECT,
            goal=f"Trace the failure to likely root cause, impacted components, and safe fix boundary for: {goal}",
            task_type="diagnosis",
            depends_on=["mission-reproduce"],
            input_items=["reproduction evidence", "failure signals"],
            output_items=["root cause analysis", "fix boundary"],
            evidence_required=["cause analysis"],
            capability_requirements=["systems analysis"],
            risk_level="high",
            replan_when=["evidence contradicts the suspected root cause"],
            planning_rationale="Root-cause analysis turns failure evidence into a safe fix contract.",
            acceptance_criteria=[
                "Likely root cause and alternative hypotheses are listed.",
                "A minimal fix and verification strategy are proposed.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-fix",
            title="Implement targeted fix",
            role=AgentTeamTaskRole.BACKEND_EXECUTOR,
            goal=f"Implement the minimal targeted fix within the diagnosed boundary for: {goal}",
            task_type="implementation",
            depends_on=["mission-root-cause"],
            input_items=["root cause analysis", "fix boundary"],
            output_items=["targeted patch", "changed files"],
            evidence_required=["patch summary"],
            capability_requirements=["code modification"],
            risk_level="high",
            write_scope=profile.write_scope or ["src/**", "tests/**"],
            replan_when=["fix requires unrelated modules"],
            planning_rationale="The fix deliverable depends on diagnosis and should not broaden scope without replanning.",
            acceptance_criteria=[
                "The change is limited to the root cause boundary.",
                "Changed files, assumptions, and residual risks are recorded.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-regression",
            title="Verify regression path",
            role=AgentTeamTaskRole.VERIFIER,
            goal=f"Verify the original failure and nearby regression risks after the fix for: {goal}",
            task_type="verification",
            depends_on=["mission-fix"],
            input_items=["targeted patch", "changed files"],
            output_items=["regression evidence"],
            evidence_required=["test command and result"],
            capability_requirements=["test execution"],
            planning_rationale="Debugging is complete only when the failure evidence turns green.",
            acceptance_criteria=[
                "The original failure path is checked again.",
                "Evidence includes commands, results, and remaining gaps.",
            ],
        ),
    ]


def _review_deliverables(profile: MissionProfile) -> list[MissionDeliverable]:
    goal = _mission_text(profile)
    return [
        _deliverable(
            profile,
            key="mission-review-map",
            title="Map review scope",
            role=AgentTeamTaskRole.PLANNER,
            goal=f"Define review boundaries, high-risk areas, and required evidence for: {goal}",
            task_type="coordination",
            output_items=["review checklist"],
            capability_requirements=["risk triage"],
            planning_rationale="The scope map names the evidence and risk areas required before critique.",
            acceptance_criteria=[
                "Review scope, exclusions, and priority risks are explicit.",
                "Evidence needed for a recommendation is listed.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-critique",
            title="Critique correctness and risks",
            role=AgentTeamTaskRole.REVIEWER,
            goal=f"Review correctness, security, maintainability, regression risk, and missing evidence for: {goal}",
            task_type="review",
            depends_on=["mission-review-map"],
            input_items=["review checklist"],
            output_items=["review findings"],
            evidence_required=["finding rationale"],
            capability_requirements=["code review", "risk assessment"],
            risk_level="high",
            planning_rationale="The critique deliverable produces evidence-backed findings, not implementation changes.",
            acceptance_criteria=[
                "Findings are classified by severity and confidence.",
                "Each finding includes rationale, evidence, or uncertainty.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-review-verdict",
            title="Prepare review verdict",
            role=AgentTeamTaskRole.WRITER,
            goal=f"Synthesize findings into an actionable review verdict and follow-up plan for: {goal}",
            task_type="documentation",
            depends_on=["mission-critique"],
            input_items=["review findings"],
            output_items=["review verdict"],
            capability_requirements=["technical writing"],
            planning_rationale="The verdict deliverable makes the review actionable for the requester.",
            acceptance_criteria=[
                "Verdict distinguishes blockers, non-blockers, and follow-ups.",
                "Recommendation is tied to review evidence.",
            ],
        ),
    ]


def _verification_deliverables(profile: MissionProfile) -> list[MissionDeliverable]:
    goal = _mission_text(profile)
    return [
        _deliverable(
            profile,
            key="mission-scope",
            title="Define verification scope",
            role=AgentTeamTaskRole.PLANNER,
            goal=f"Define behaviors, risk paths, and pass criteria for: {goal}",
            task_type="coordination",
            output_items=["verification checklist", "pass criteria"],
            capability_requirements=["test planning"],
            planning_rationale="The scope deliverable defines what evidence is sufficient before checks run.",
            acceptance_criteria=[
                "Required paths, data, and failure modes are listed.",
                "Sufficient evidence is defined.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-verify",
            title="Run verification",
            role=AgentTeamTaskRole.VERIFIER,
            goal=f"Run checks and collect reproducible evidence for: {goal}",
            task_type="verification",
            depends_on=["mission-scope"],
            input_items=["verification checklist", "pass criteria"],
            output_items=["verification evidence"],
            evidence_required=["command output", "manual check notes"],
            capability_requirements=["test execution"],
            planning_rationale="The verification deliverable produces reproducible evidence against the chosen criteria.",
            acceptance_criteria=[
                "Commands, inputs, results, and failures are recorded.",
                "Evidence covers key risk or user paths.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-review",
            title="Review verification conclusion",
            role=AgentTeamTaskRole.REVIEWER,
            goal=f"Review whether the evidence supports a delivery recommendation for: {goal}",
            task_type="review",
            depends_on=["mission-verify"],
            input_items=["verification evidence"],
            output_items=["verification verdict"],
            evidence_required=["evidence gap notes"],
            capability_requirements=["risk assessment"],
            planning_rationale="The verdict deliverable separates raw evidence from the delivery recommendation.",
            acceptance_criteria=[
                "Evidence gaps and residual risks are called out.",
                "A pass, block, or continue-verification recommendation is made.",
            ],
        ),
    ]


def _writing_deliverables(profile: MissionProfile) -> list[MissionDeliverable]:
    goal = _mission_text(profile)
    return [
        _deliverable(
            profile,
            key="mission-outline",
            title="Outline deliverable",
            role=AgentTeamTaskRole.PLANNER,
            goal=f"Define audience, structure, source material, and acceptance bar for: {goal}",
            task_type="coordination",
            output_items=["content outline"],
            capability_requirements=["content planning"],
            planning_rationale="The outline deliverable establishes structure and evidence boundaries before drafting.",
            acceptance_criteria=[
                "Audience, tone, required sections, and exclusions are clear.",
                "Source gaps and assumptions are listed.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-source-check",
            title="Check source material",
            role=AgentTeamTaskRole.PLANNER,
            goal=f"Collect or validate source material, facts, and caveats needed for: {goal}",
            task_type="research",
            depends_on=["mission-outline"],
            input_items=["content outline"],
            output_items=["source notes"],
            evidence_required=["source notes"],
            capability_requirements=["research"],
            planning_rationale="Source checking produces the factual contract the draft must satisfy.",
            acceptance_criteria=[
                "Key claims have source notes or are marked as assumptions.",
                "Contradictions and missing facts are called out.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-draft",
            title="Draft deliverable",
            role=AgentTeamTaskRole.WRITER,
            goal=f"Write the deliverable in the requested format using the outline and source notes for: {goal}",
            task_type="documentation",
            depends_on=["mission-source-check"],
            input_items=["content outline", "source notes"],
            output_items=["draft deliverable"],
            capability_requirements=["technical writing"],
            write_scope=profile.write_scope,
            planning_rationale="The draft deliverable converts structured inputs into the requested artifact.",
            acceptance_criteria=[
                "Draft covers required sections and intended audience.",
                "Unverified claims are caveated or omitted.",
            ],
        ),
        _deliverable(
            profile,
            key="mission-edit",
            title="Review clarity and accuracy",
            role=AgentTeamTaskRole.REVIEWER,
            goal=f"Review the draft for accuracy, completeness, clarity, and usability for: {goal}",
            task_type="review",
            depends_on=["mission-draft"],
            input_items=["draft deliverable"],
            output_items=["editorial review"],
            evidence_required=["correction notes"],
            capability_requirements=["risk assessment"],
            planning_rationale="Editorial review determines whether the written deliverable is usable and accurate.",
            acceptance_criteria=[
                "Corrections, gaps, and residual uncertainties are listed.",
                "Final deliverability recommendation is clear.",
            ],
        ),
    ]


def _fallback_debug_deliverables(
    deliverables: list[MissionDeliverable],
) -> list[MissionDeliverable]:
    by_key = {deliverable.key: deliverable for deliverable in deliverables}
    reproduce = by_key.get("mission-reproduce")
    fix = by_key.get("mission-fix")
    regression = by_key.get("mission-regression")
    if reproduce is None or fix is None or regression is None:
        return deliverables
    fix = fix.model_copy(
        update={
            "depends_on": ["mission-reproduce"],
            "input_items": _dedupe_values([*fix.input_items, "reproduction evidence"]),
            "replan_when": _dedupe_values(
                [*fix.replan_when, "root cause differs from initial diagnosis"]
            ),
        }
    )
    regression = regression.model_copy(update={"depends_on": ["mission-fix"]})
    return [reproduce, fix, regression]


def _dedupe_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


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


def _resource_claims_for_deliverable(deliverable: MissionDeliverable) -> list[str]:
    return list(deliverable.resource_claims or _resource_claims_for_scope(deliverable.write_scope))


def _resource_claims_for_scope(write_scope: list[str]) -> list[str]:
    claims: list[str] = []
    for item in write_scope:
        text = str(item or "").strip()
        if text:
            claims.append(f"file:{text}")
    return _dedupe_values(claims)


def _contract_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _dedupe_values([value])
    return _dedupe_values([str(item) for item in value if str(item).strip()])


def _apply_contract_defaults(task_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [dict(spec) for spec in task_specs]
    output_by_key = {
        str(spec.get("key")): _contract_values(
            spec.get("output_items") or [str(spec.get("task_type") or "output")]
        )
        for spec in specs
    }
    for spec in specs:
        task_type = str(spec.get("task_type") or "execution")
        dependencies = _contract_values(spec.get("dependencies"))
        input_items = _contract_values(spec.get("input_items"))
        for dependency in dependencies:
            input_items.extend(output_by_key.get(dependency, []))
        input_items = _dedupe_values(input_items)
        output_items = _contract_values(spec.get("output_items") or [task_type])
        evidence = _contract_values(spec.get("evidence_required") or spec.get("evidence"))
        capabilities = _contract_values(
            spec.get("capability_requirements") or spec.get("capabilities")
        )
        replan_when = _contract_values(spec.get("replan_when"))

        spec["dependencies"] = dependencies
        spec.setdefault("task_kind", task_type)
        spec.setdefault("output_items", output_items)
        if not isinstance(spec.get("input_contract"), dict):
            spec["input_contract"] = {
                "requires": input_items,
                "from_dependencies": dependencies,
            }
        if not isinstance(spec.get("output_contract"), dict):
            spec["output_contract"] = {"produces": output_items, "evidence": evidence}
        spec["evidence_required"] = evidence
        spec["capability_requirements"] = capabilities
        if not spec.get("risk_level") and spec.get("risk"):
            spec["risk_level"] = str(spec["risk"])
        if not isinstance(spec.get("replan_policy"), dict):
            spec["replan_policy"] = {"replan_when": replan_when}
    return specs


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
