from __future__ import annotations

from focus_agent.core.agent_team import AgentTeamTaskRole

from .agent_team_planning_dag_contracts import (
    _dedupe_values,
    _resource_claims_for_scope,
)
from .agent_team_planning_models import MissionDeliverable, MissionProfile


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


__all__ = [
    "_debugging_deliverables",
    "_deliverable",
    "_fallback_debug_deliverables",
    "_implementation_deliverables",
    "_research_deliverables",
    "_review_deliverables",
    "_verification_deliverables",
    "_writing_deliverables",
]
