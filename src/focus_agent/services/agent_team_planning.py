from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from focus_agent.agent_delegation import AgentDelegationPlan, build_agent_delegation_plan
from focus_agent.agent_roles import AgentRole
from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)

from .agent_team_helpers import _now


_AGENT_ROLE_TO_TEAM_ROLE: dict[AgentRole, AgentTeamTaskRole] = {
    AgentRole.ORCHESTRATOR: AgentTeamTaskRole.ARCHITECT,
    AgentRole.PLANNER: AgentTeamTaskRole.PLANNER,
    AgentRole.EXECUTOR: AgentTeamTaskRole.BACKEND_EXECUTOR,
    AgentRole.CRITIC: AgentTeamTaskRole.REVIEWER,
    AgentRole.MEMORY_CURATOR: AgentTeamTaskRole.PLANNER,
    AgentRole.SKILL_SCOUT: AgentTeamTaskRole.PLANNER,
}


class AgentTeamPlanOptions(BaseModel):
    replace_existing: bool = False
    granularity: str | None = None
    focus: str | None = None
    max_tasks: int | None = None


class AgentTeamTaskDraft(BaseModel):
    key: str
    title: str
    role: AgentTeamTaskRole
    goal: str
    scope: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    planning_rationale: str
    sort_order: int
    task_type: str = "execution"
    plan_source: str


class AgentTeamPlanDraft(BaseModel):
    planning_source: str
    planning_rationale: str
    planner_model_id: str | None = None
    planning_error: str | None = None
    plan_hash: str
    tasks: list[AgentTeamTaskDraft] = Field(default_factory=list)


class AgentTeamPlanningService:
    def __init__(self, *, settings: Any | None = None):
        self.settings = settings

    def build_plan(
        self,
        *,
        session: AgentTeamSession,
        options: AgentTeamPlanOptions,
    ) -> AgentTeamPlanDraft:
        adaptive_error: str | None = None
        delegation_error: str | None = None
        if _should_prefer_adaptive_model_plan(session=session, options=options):
            try:
                return self._adaptive_model_plan(session=session, options=options)
            except Exception as exc:  # noqa: BLE001
                adaptive_error = f"{type(exc).__name__}: {exc}"

        try:
            plan = self._build_delegation_plan(session=session, options=options)
            if plan is not None:
                return plan
        except Exception as exc:  # noqa: BLE001
            delegation_error = f"{type(exc).__name__}: {exc}"

        try:
            return self._adaptive_model_plan(
                session=session,
                options=options,
                planning_note=delegation_error,
            )
        except Exception as exc:  # noqa: BLE001
            planning_error = f"Adaptive planning failed: {type(exc).__name__}: {exc}"
            if adaptive_error:
                planning_error = (
                    f"{planning_error}; preferred adaptive planning failed: {adaptive_error}"
                )
            if delegation_error:
                planning_error = f"{planning_error}; delegation planning failed: {delegation_error}"
            return self._fallback_plan(
                session=session,
                options=options,
                planning_error=planning_error,
            )

    def _build_delegation_plan(
        self,
        *,
        session: AgentTeamSession,
        options: AgentTeamPlanOptions,
    ) -> AgentTeamPlanDraft | None:
        if self.settings is None:
            return None
        delegation = build_agent_delegation_plan(settings=self.settings, task_text=session.goal)
        if not delegation.enabled or not delegation.tasks:
            return None

        max_tasks = _max_tasks_for(options)
        decision_by_task_id = {
            str(decision.task_id): decision
            for decision in delegation.decisions
            if getattr(decision, "task_id", None)
        }
        included_task_ids = {task.task_id for task in delegation.tasks[:max_tasks]}
        tasks: list[AgentTeamTaskDraft] = []
        for sort_order, delegated in enumerate(delegation.tasks[:max_tasks], start=1):
            role = _team_role_for_agent_role(delegated.role)
            dependencies = [
                parent_id
                for parent_id in [delegated.parent_task_id]
                if parent_id and parent_id in included_task_ids
            ]
            decision = decision_by_task_id.get(delegated.task_id)
            rationale = (
                getattr(decision, "rationale", None)
                or _artifact_rationale_for(delegation, delegated.task_id)
                or "Role routing produced this task from the session goal."
            )
            task_goal = _focused_goal(str(delegated.goal), options)
            tasks.append(
                AgentTeamTaskDraft(
                    key=delegated.task_id,
                    title=_title_for(role, task_goal),
                    role=role,
                    goal=task_goal,
                    scope=list(delegated.allowed_tools),
                    dependencies=dependencies,
                    acceptance_criteria=list(delegated.acceptance_criteria)
                    or ["The task output is traceable to the session goal."],
                    context_refs=list(delegated.context_refs),
                    planning_rationale=str(rationale),
                    sort_order=sort_order,
                    task_type=_task_type_for(role),
                    plan_source="model",
                )
            )

        _validate_task_draft(tasks)
        planner_model_id = _planner_model_id(delegation)
        draft = AgentTeamPlanDraft(
            planning_source="model",
            planning_rationale=delegation.route_reason
            or "Delegation role routing produced a structured task plan.",
            planner_model_id=planner_model_id,
            plan_hash="",
            tasks=tasks,
        )
        return draft.model_copy(update={"plan_hash": _plan_hash(session, options, draft)})

    def _adaptive_model_plan(
        self,
        *,
        session: AgentTeamSession,
        options: AgentTeamPlanOptions,
        planning_note: str | None = None,
    ) -> AgentTeamPlanDraft:
        max_tasks = _max_tasks_for(options)
        base_goal = _focused_goal(session.goal, options)
        language = "zh" if _contains_cjk(base_goal) else "en"
        focus = _infer_focus(base_goal, options)
        task_specs = _adaptive_task_specs(base_goal, focus=focus, language=language)
        task_specs = _fit_task_specs_to_limit(task_specs, max_tasks=max_tasks)
        tasks = [
            AgentTeamTaskDraft(
                key=spec["key"],
                title=spec["title"],
                role=AgentTeamTaskRole(str(spec["role"])),
                goal=spec["goal"],
                scope=list(spec.get("scope") or []),
                dependencies=list(spec.get("dependencies") or []),
                acceptance_criteria=list(spec["acceptance_criteria"]),
                context_refs=_context_refs_for(session),
                planning_rationale=str(spec["planning_rationale"]),
                sort_order=index,
                task_type=str(spec["task_type"]),
                plan_source="model",
            )
            for index, spec in enumerate(task_specs, start=1)
        ]
        _validate_task_draft(tasks)
        draft = AgentTeamPlanDraft(
            planning_source="model",
            planning_rationale=_adaptive_plan_rationale(
                base_goal,
                focus=focus,
                task_count=len(tasks),
                language=language,
                planning_note=planning_note,
            ),
            planner_model_id=_planner_model_id_for_settings(self.settings),
            plan_hash="",
            tasks=tasks,
        )
        return draft.model_copy(update={"plan_hash": _plan_hash(session, options, draft)})

    def _fallback_plan(
        self,
        *,
        session: AgentTeamSession,
        options: AgentTeamPlanOptions,
        planning_error: str,
    ) -> AgentTeamPlanDraft:
        max_tasks = _max_tasks_for(options)
        count = min(max_tasks, 2 if _is_coarse(options) else 3)
        source = "fallback_heuristic"
        base_goal = _focused_goal(session.goal, options)
        candidates = [
            AgentTeamTaskDraft(
                key="fallback-coordinate",
                title="Coordinate the work",
                role=AgentTeamTaskRole.PLANNER,
                goal=f"Clarify the smallest safe plan for: {base_goal}",
                acceptance_criteria=[
                    "Scope, assumptions, and success checks are explicit.",
                    "Dependencies and handoff expectations are clear.",
                ],
                planning_rationale="Use a coordinator first because adaptive planning was unavailable.",
                sort_order=1,
                task_type="coordination",
                plan_source=source,
            ),
            AgentTeamTaskDraft(
                key="fallback-execute",
                title="Execute the focused slice",
                role=AgentTeamTaskRole.BACKEND_EXECUTOR,
                goal=f"Implement the smallest verifiable slice for: {base_goal}",
                dependencies=["fallback-coordinate"],
                acceptance_criteria=[
                    "Changes stay within the requested scope.",
                    "Behavior is tied to at least one automated or manual verification check.",
                ],
                planning_rationale="Keep fallback execution conservative and goal-bound.",
                sort_order=2,
                task_type="execution",
                plan_source=source,
            ),
            AgentTeamTaskDraft(
                key="fallback-review",
                title="Review and verify",
                role=AgentTeamTaskRole.REVIEWER,
                goal=f"Review the implementation and verification evidence for: {base_goal}",
                dependencies=["fallback-execute"],
                acceptance_criteria=[
                    "Regressions, missing tests, and release risks are called out.",
                    "Final evidence is concise and reproducible.",
                ],
                planning_rationale="A small fallback plan still needs independent review evidence.",
                sort_order=3,
                task_type="review",
                plan_source=source,
            ),
        ][:count]
        _validate_task_draft(candidates)
        draft = AgentTeamPlanDraft(
            planning_source=source,
            planning_rationale="Fallback heuristic produced a conservative dynamic plan.",
            planning_error=planning_error,
            plan_hash="",
            tasks=candidates,
        )
        return draft.model_copy(update={"plan_hash": _plan_hash(session, options, draft)})


class AgentTeamPlanningMixin:
    settings: Any | None

    def plan_session(
        self,
        *,
        session_id: str,
        user_id: str,
        create_branches: bool = True,
        parent_thread_id: str | None = None,
        replace_existing: bool = False,
        granularity: str | None = None,
        focus: str | None = None,
        max_tasks: int | None = None,
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        session = self.get_session(session_id, user_id=user_id)
        options = AgentTeamPlanOptions(
            replace_existing=replace_existing,
            granularity=granularity,
            focus=focus,
            max_tasks=max_tasks,
        )
        draft = AgentTeamPlanningService(settings=self.settings).build_plan(
            session=session,
            options=options,
        )

        existing = self.list_tasks(session_id=session_id, user_id=user_id)
        active_existing = [
            task for task in existing if task.status != AgentTeamTaskStatus.CANCELLED
        ]
        if (
            active_existing
            and not options.replace_existing
            and session.plan_hash == draft.plan_hash
        ):
            session = self._save_planning_metadata(session, draft)
            return session, active_existing

        if active_existing and options.replace_existing:
            self._cancel_unstarted_tasks(tasks=active_existing, user_id=user_id)
            active_existing = [
                task
                for task in self.list_tasks(session_id=session_id, user_id=user_id)
                if task.status != AgentTeamTaskStatus.CANCELLED
            ]

        created_by_key: dict[str, AgentTeamTask] = {}
        existing_by_identity = {_task_identity(task): task for task in active_existing}
        for task_draft in draft.tasks:
            key = (task_draft.role, task_draft.goal.strip())
            existing_task = existing_by_identity.get(key)
            if existing_task is not None:
                created_by_key[task_draft.key] = existing_task
                continue

            dependencies = [
                created_by_key[dependency].task_id
                for dependency in task_draft.dependencies
                if dependency in created_by_key
            ]
            task = self.create_task(
                session_id=session_id,
                user_id=user_id,
                role=task_draft.role,
                title=task_draft.title,
                goal=task_draft.goal,
                scope=task_draft.scope,
                dependencies=dependencies,
                acceptance_criteria=task_draft.acceptance_criteria,
                planning_rationale=task_draft.planning_rationale,
                sort_order=task_draft.sort_order,
                task_type=task_draft.task_type,
                plan_source=task_draft.plan_source,
                context_refs=task_draft.context_refs,
                create_branch=create_branches,
                parent_thread_id=parent_thread_id or session.root_thread_id,
            )
            created_by_key[task_draft.key] = task
            existing_by_identity[key] = task

        session = self._save_planning_metadata(self.get_session(session_id, user_id=user_id), draft)
        tasks = [
            task
            for task in self.list_tasks(session_id=session_id, user_id=user_id)
            if task.status != AgentTeamTaskStatus.CANCELLED
        ]
        return session, tasks

    def _save_planning_metadata(
        self,
        session: AgentTeamSession,
        draft: AgentTeamPlanDraft,
    ) -> AgentTeamSession:
        updated = session.model_copy(
            update={
                "planning_source": draft.planning_source,
                "planning_rationale": draft.planning_rationale,
                "planner_model_id": draft.planner_model_id,
                "plan_generated_at": _now(),
                "plan_hash": draft.plan_hash,
                "planning_error": draft.planning_error,
                "updated_at": _now(),
            }
        )
        self.repository.save_session(updated)
        return updated

    def _cancel_unstarted_tasks(self, *, tasks: list[AgentTeamTask], user_id: str) -> None:
        for task in tasks:
            if not _is_unstarted(task):
                continue
            self.update_task(
                task_id=task.task_id,
                user_id=user_id,
                status=AgentTeamTaskStatus.CANCELLED,
                last_error="Replaced by a regenerated Agent Team plan.",
            )


def _task_identity(task: AgentTeamTask) -> tuple[AgentTeamTaskRole, str]:
    return (task.role, task.goal.strip())


def _team_role_for_agent_role(role: AgentRole) -> AgentTeamTaskRole:
    return _AGENT_ROLE_TO_TEAM_ROLE.get(role, AgentTeamTaskRole.BACKEND_EXECUTOR)


def _max_tasks_for(options: AgentTeamPlanOptions) -> int:
    if options.max_tasks is not None:
        return min(8, max(1, int(options.max_tasks)))
    if _is_coarse(options):
        return 3
    if str(options.granularity or "").strip().lower() in {"fine", "detailed", "high"}:
        return 8
    return 6


def _is_coarse(options: AgentTeamPlanOptions) -> bool:
    return str(options.granularity or "").strip().lower() in {"coarse", "low", "small"}


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _infer_focus(goal: str, options: AgentTeamPlanOptions) -> str:
    explicit = str(options.focus or "").strip().lower()
    if explicit in {"research", "implementation", "verification"}:
        return explicit
    normalized = goal.lower()
    if any(marker in normalized for marker in _IMPLEMENTATION_MARKERS):
        return "implementation"
    if any(marker in normalized for marker in _VERIFICATION_MARKERS):
        return "verification"
    if any(marker in normalized for marker in _RESEARCH_MARKERS):
        return "research"
    return "research" if _contains_cjk(goal) and "攻略" in goal else "implementation"


def _should_prefer_adaptive_model_plan(
    *,
    session: AgentTeamSession,
    options: AgentTeamPlanOptions,
) -> bool:
    base_goal = _focused_goal(session.goal, options)
    focus = _infer_focus(base_goal, options)
    # Role routing is useful for code execution, but it can turn open-ended
    # research or validation missions into generic executor tasks. For those
    # goals, the Workbench should show a domain-shaped DAG directly.
    return focus in {"research", "verification"}


_RESEARCH_MARKERS = (
    "research",
    "plan",
    "guide",
    "strategy",
    "travel",
    "itinerary",
    "compare",
    "分析",
    "调研",
    "规划",
    "方案",
    "攻略",
    "旅行",
    "行程",
    "对比",
)
_IMPLEMENTATION_MARKERS = (
    "implement",
    "build",
    "fix",
    "refactor",
    "backend",
    "frontend",
    "sdk",
    "api",
    "database",
    "ui",
    "实现",
    "开发",
    "修复",
    "重构",
    "前端",
    "后端",
    "接口",
    "代码",
)
_VERIFICATION_MARKERS = (
    "verify",
    "test",
    "review",
    "audit",
    "qa",
    "验证",
    "测试",
    "审查",
    "检查",
    "评审",
)


def _adaptive_task_specs(goal: str, *, focus: str, language: str) -> list[dict[str, Any]]:
    if focus == "verification":
        return _verification_task_specs(goal, language=language)
    if focus == "implementation":
        return _implementation_task_specs(goal, language=language)
    return _research_task_specs(goal, language=language)


def _research_task_specs(goal: str, *, language: str) -> list[dict[str, Any]]:
    if language == "zh":
        return [
            {
                "key": "mission-brief",
                "title": "确认目标与边界",
                "role": AgentTeamTaskRole.PLANNER.value,
                "goal": f"澄清目标、受众、约束和成功标准：{goal}",
                "acceptance_criteria": [
                    "明确产物范围、默认假设和不确定信息。",
                    "列出后续任务需要验证的关键问题。",
                ],
                "planning_rationale": "先收敛边界，避免后续研究和产出方向发散。",
                "task_type": "coordination",
            },
            {
                "key": "mission-research",
                "title": "调研关键决策",
                "role": AgentTeamTaskRole.PLANNER.value,
                "goal": f"围绕目标收集并比较关键信息、选项和约束：{goal}",
                "dependencies": ["mission-brief"],
                "acceptance_criteria": [
                    "覆盖主要决策维度，并区分事实、建议和假设。",
                    "记录可复查的依据、冲突信息和风险点。",
                ],
                "planning_rationale": "该目标以研究和方案质量为核心，需要先建立证据底座。",
                "task_type": "research",
            },
            {
                "key": "mission-synthesis",
                "title": "产出可执行方案",
                "role": AgentTeamTaskRole.WRITER.value,
                "goal": f"把调研结果整理成结构清晰、可直接使用的最终方案：{goal}",
                "dependencies": ["mission-research"],
                "acceptance_criteria": [
                    "方案覆盖用户目标中的主要部分，并给出优先级或选择建议。",
                    "输出包含可执行步骤、注意事项和可替代选项。",
                ],
                "planning_rationale": "把分散证据转成用户真正需要的可交付内容。",
                "task_type": "documentation",
            },
            {
                "key": "mission-review",
                "title": "审查证据与风险",
                "role": AgentTeamTaskRole.REVIEWER.value,
                "goal": f"检查最终方案的完整性、风险、遗漏和可执行性：{goal}",
                "dependencies": ["mission-synthesis"],
                "acceptance_criteria": [
                    "指出缺失信息、潜在风险和需要用户确认的问题。",
                    "给出是否可交付或需要补充研究的建议。",
                ],
                "planning_rationale": "合并前需要独立检查证据和风险，避免只有产出没有把关。",
                "task_type": "review",
            },
        ]
    return [
        {
            "key": "mission-brief",
            "title": "Clarify mission boundaries",
            "role": AgentTeamTaskRole.PLANNER.value,
            "goal": f"Clarify scope, audience, constraints, and success criteria for: {goal}",
            "acceptance_criteria": [
                "Scope, assumptions, and success checks are explicit.",
                "Open questions for downstream tasks are listed.",
            ],
            "planning_rationale": "The plan starts by narrowing the mission before research begins.",
            "task_type": "coordination",
        },
        {
            "key": "mission-research",
            "title": "Research key decisions",
            "role": AgentTeamTaskRole.PLANNER.value,
            "goal": f"Gather and compare key facts, options, constraints, and risks for: {goal}",
            "dependencies": ["mission-brief"],
            "acceptance_criteria": [
                "Main decision dimensions are covered.",
                "Evidence, conflicts, and assumptions are captured.",
            ],
            "planning_rationale": "This mission depends on evidence quality before synthesis.",
            "task_type": "research",
        },
        {
            "key": "mission-synthesis",
            "title": "Synthesize deliverable",
            "role": AgentTeamTaskRole.WRITER.value,
            "goal": f"Turn the research into a clear, directly usable deliverable for: {goal}",
            "dependencies": ["mission-research"],
            "acceptance_criteria": [
                "The deliverable covers the main requested sections.",
                "Recommendations, steps, caveats, and alternatives are included.",
            ],
            "planning_rationale": "The user needs a coherent output, not only raw findings.",
            "task_type": "documentation",
        },
        {
            "key": "mission-review",
            "title": "Review evidence and risks",
            "role": AgentTeamTaskRole.REVIEWER.value,
            "goal": f"Review completeness, risks, omissions, and handoff quality for: {goal}",
            "dependencies": ["mission-synthesis"],
            "acceptance_criteria": [
                "Missing information and risks are called out.",
                "A clear deliver/request-changes recommendation is provided.",
            ],
            "planning_rationale": "Independent review keeps the final recommendation trustworthy.",
            "task_type": "review",
        },
    ]


def _implementation_task_specs(goal: str, *, language: str) -> list[dict[str, Any]]:
    has_frontend = any(
        marker in goal.lower() for marker in ("frontend", "ui", "react", "web")
    ) or any(marker in goal for marker in ("前端", "界面", "页面", "交互"))
    has_backend = any(
        marker in goal.lower() for marker in ("backend", "api", "database", "service")
    ) or any(marker in goal for marker in ("后端", "接口", "数据库", "服务"))
    execution_role = (
        AgentTeamTaskRole.FRONTEND_EXECUTOR
        if has_frontend and not has_backend
        else AgentTeamTaskRole.BACKEND_EXECUTOR
    )
    execution_type = "implementation"
    if language == "zh":
        execution_title = (
            "实现前端体验"
            if execution_role == AgentTeamTaskRole.FRONTEND_EXECUTOR
            else "实现核心改动"
        )
        execution_goal = f"按明确边界实现最小可验证改动：{goal}"
        return [
            {
                "key": "mission-architecture",
                "title": "拆解实现边界",
                "role": AgentTeamTaskRole.ARCHITECT.value,
                "goal": f"定义实现范围、依赖关系、验收标准和风险：{goal}",
                "acceptance_criteria": [
                    "明确哪些文件或模块会被触达。",
                    "列出验收标准、依赖和回滚风险。",
                ],
                "planning_rationale": "实现类目标需要先拆清边界和依赖，避免多 Agent 写入冲突。",
                "task_type": "coordination",
            },
            {
                "key": "mission-implementation",
                "title": execution_title,
                "role": execution_role.value,
                "goal": execution_goal,
                "dependencies": ["mission-architecture"],
                "acceptance_criteria": [
                    "改动保持在任务范围内，并遵循现有架构风格。",
                    "产物记录 changed files、关键决策和已知风险。",
                ],
                "planning_rationale": "核心执行任务负责把目标转成可验证产物。",
                "task_type": execution_type,
            },
            {
                "key": "mission-verification",
                "title": "验证行为与回归",
                "role": AgentTeamTaskRole.VERIFIER.value,
                "goal": f"运行与改动相关的测试、构建或手动检查：{goal}",
                "dependencies": ["mission-implementation"],
                "acceptance_criteria": [
                    "测试证据包含命令、结果和失败时的原因。",
                    "覆盖主要用户路径或风险路径。",
                ],
                "planning_rationale": "执行结果必须带证据，才能进入合并建议。",
                "task_type": "verification",
            },
            {
                "key": "mission-review",
                "title": "审查实现风险",
                "role": AgentTeamTaskRole.REVIEWER.value,
                "goal": f"审查实现质量、架构风险、回归风险和未决问题：{goal}",
                "dependencies": ["mission-verification"],
                "acceptance_criteria": [
                    "列出阻塞问题、非阻塞风险和建议动作。",
                    "基于证据给出合并或继续修改建议。",
                ],
                "planning_rationale": "最后由独立审查任务决定是否具备交付条件。",
                "task_type": "review",
            },
        ]
    execution_title = (
        "Implement frontend experience"
        if execution_role == AgentTeamTaskRole.FRONTEND_EXECUTOR
        else "Implement core change"
    )
    return [
        {
            "key": "mission-architecture",
            "title": "Decompose implementation scope",
            "role": AgentTeamTaskRole.ARCHITECT.value,
            "goal": f"Define implementation scope, dependencies, acceptance criteria, and risks for: {goal}",
            "acceptance_criteria": [
                "Touched modules or files are identified.",
                "Acceptance criteria, dependencies, and rollback risks are listed.",
            ],
            "planning_rationale": "Implementation work needs explicit boundaries before agents write.",
            "task_type": "coordination",
        },
        {
            "key": "mission-implementation",
            "title": execution_title,
            "role": execution_role.value,
            "goal": f"Implement the smallest verifiable slice for: {goal}",
            "dependencies": ["mission-architecture"],
            "acceptance_criteria": [
                "Changes stay within scope and follow existing architecture.",
                "Outputs include changed files, decisions, and known risks.",
            ],
            "planning_rationale": "The execution task turns the mission into a reviewable artifact.",
            "task_type": execution_type,
        },
        {
            "key": "mission-verification",
            "title": "Verify behavior and regressions",
            "role": AgentTeamTaskRole.VERIFIER.value,
            "goal": f"Run relevant tests, builds, or manual checks for: {goal}",
            "dependencies": ["mission-implementation"],
            "acceptance_criteria": [
                "Evidence includes commands, results, and failure reasons.",
                "The main user or risk path is covered.",
            ],
            "planning_rationale": "Execution needs evidence before merge advice is credible.",
            "task_type": "verification",
        },
        {
            "key": "mission-review",
            "title": "Review implementation risk",
            "role": AgentTeamTaskRole.REVIEWER.value,
            "goal": f"Review implementation quality, architecture risk, regression risk, and open questions for: {goal}",
            "dependencies": ["mission-verification"],
            "acceptance_criteria": [
                "Blocking issues, residual risks, and suggested action are listed.",
                "Merge or request-changes advice is based on evidence.",
            ],
            "planning_rationale": "Independent review decides whether the mission is deliverable.",
            "task_type": "review",
        },
    ]


def _verification_task_specs(goal: str, *, language: str) -> list[dict[str, Any]]:
    if language == "zh":
        return [
            {
                "key": "mission-scope",
                "title": "定义验证范围",
                "role": AgentTeamTaskRole.PLANNER.value,
                "goal": f"确认需要验证的行为、风险路径和通过标准：{goal}",
                "acceptance_criteria": [
                    "列出必须覆盖的路径、数据和失败模式。",
                    "明确哪些证据足以支持结论。",
                ],
                "planning_rationale": "验证类任务先定义证据口径，减少无效检查。",
                "task_type": "coordination",
            },
            {
                "key": "mission-verify",
                "title": "执行验证",
                "role": AgentTeamTaskRole.VERIFIER.value,
                "goal": f"运行检查并收集可复查证据：{goal}",
                "dependencies": ["mission-scope"],
                "acceptance_criteria": [
                    "记录命令、输入、结果和失败原因。",
                    "证据覆盖关键风险或用户路径。",
                ],
                "planning_rationale": "Verifier 负责把判断建立在可复查证据上。",
                "task_type": "verification",
            },
            {
                "key": "mission-review",
                "title": "复核验证结论",
                "role": AgentTeamTaskRole.REVIEWER.value,
                "goal": f"复核验证证据是否足够支撑交付建议：{goal}",
                "dependencies": ["mission-verify"],
                "acceptance_criteria": [
                    "指出证据缺口和残余风险。",
                    "给出通过、阻塞或继续验证建议。",
                ],
                "planning_rationale": "验证结果需要独立复核后才能进入合并建议。",
                "task_type": "review",
            },
        ]
    return [
        {
            "key": "mission-scope",
            "title": "Define verification scope",
            "role": AgentTeamTaskRole.PLANNER.value,
            "goal": f"Define behaviors, risk paths, and pass criteria for: {goal}",
            "acceptance_criteria": [
                "Required paths, data, and failure modes are listed.",
                "Sufficient evidence is defined.",
            ],
            "planning_rationale": "Verification starts by choosing meaningful evidence.",
            "task_type": "coordination",
        },
        {
            "key": "mission-verify",
            "title": "Run verification",
            "role": AgentTeamTaskRole.VERIFIER.value,
            "goal": f"Run checks and collect reproducible evidence for: {goal}",
            "dependencies": ["mission-scope"],
            "acceptance_criteria": [
                "Commands, inputs, results, and failures are recorded.",
                "Evidence covers key risk or user paths.",
            ],
            "planning_rationale": "Verifier turns the question into reproducible evidence.",
            "task_type": "verification",
        },
        {
            "key": "mission-review",
            "title": "Review verification conclusion",
            "role": AgentTeamTaskRole.REVIEWER.value,
            "goal": f"Review whether the evidence supports a delivery recommendation for: {goal}",
            "dependencies": ["mission-verify"],
            "acceptance_criteria": [
                "Evidence gaps and residual risks are called out.",
                "A pass, block, or continue-verification recommendation is made.",
            ],
            "planning_rationale": "Independent review keeps verification conclusions honest.",
            "task_type": "review",
        },
    ]


def _fit_task_specs_to_limit(
    task_specs: list[dict[str, Any]],
    *,
    max_tasks: int,
) -> list[dict[str, Any]]:
    selected = [dict(item) for item in task_specs[: max(1, max_tasks)]]
    selected_keys = {str(item["key"]) for item in selected}
    for spec in selected:
        dependencies = [key for key in spec.get("dependencies") or [] if key in selected_keys]
        if dependencies:
            spec["dependencies"] = dependencies
        else:
            spec.pop("dependencies", None)
    return selected


def _adaptive_plan_rationale(
    goal: str,
    *,
    focus: str,
    task_count: int,
    language: str,
    planning_note: str | None,
) -> str:
    if language == "zh":
        rationale = (
            f"根据目标语义识别为「{focus}」型 Mission，并生成 {task_count} 个按依赖推进的动态任务。"
        )
        if planning_note:
            rationale += " 已绕过不可用的 delegation 路径，改用自适应规划。"
        return rationale
    rationale = (
        f"Classified the mission as {focus} work and generated {task_count} dynamic DAG tasks "
        "from the goal, dependencies, and expected evidence."
    )
    if planning_note:
        rationale += " Delegation planning was unavailable, so adaptive planning was used."
    return rationale


def _context_refs_for(session: AgentTeamSession) -> list[dict[str, Any]]:
    return [{"kind": "thread", "id": session.root_thread_id}]


def _planner_model_id_for_settings(settings: Any | None) -> str:
    if settings is None:
        return "adaptive-planner:v1"
    for attr in ("agent_role_orchestrator_model", "agent_role_planner_model", "model"):
        value = getattr(settings, attr, None)
        if value:
            return str(value)
    return "adaptive-planner:v1"


def _focused_goal(goal: str, options: AgentTeamPlanOptions) -> str:
    normalized = " ".join(str(goal or "").split())
    focus = " ".join(str(options.focus or "").split())
    if not focus or focus.lower() == "auto":
        return normalized
    return f"{normalized}\n\nFocus: {focus}"


def _title_for(role: AgentTeamTaskRole, goal: str) -> str:
    prefix = {
        AgentTeamTaskRole.ARCHITECT: "Coordinate",
        AgentTeamTaskRole.PLANNER: "Plan",
        AgentTeamTaskRole.BACKEND_EXECUTOR: "Implement",
        AgentTeamTaskRole.FRONTEND_EXECUTOR: "Implement UI",
        AgentTeamTaskRole.TEST_ENGINEER: "Test",
        AgentTeamTaskRole.REVIEWER: "Review",
        AgentTeamTaskRole.VERIFIER: "Verify",
        AgentTeamTaskRole.WRITER: "Document",
    }.get(role, "Work")
    compact = " ".join(goal.split())
    if len(compact) > 72:
        compact = f"{compact[:69].rstrip()}..."
    return f"{prefix}: {compact}"


def _task_type_for(role: AgentTeamTaskRole) -> str:
    if role in {AgentTeamTaskRole.ARCHITECT, AgentTeamTaskRole.PLANNER}:
        return "coordination"
    if role in {
        AgentTeamTaskRole.REVIEWER,
        AgentTeamTaskRole.VERIFIER,
        AgentTeamTaskRole.TEST_ENGINEER,
    }:
        return "review"
    if role == AgentTeamTaskRole.WRITER:
        return "writeup"
    return "execution"


def _artifact_rationale_for(delegation: AgentDelegationPlan, task_id: str) -> str | None:
    for run in delegation.runs:
        if run.task_id != task_id:
            continue
        for artifact in run.artifacts:
            if artifact.summary:
                return artifact.summary
    return None


def _planner_model_id(delegation: AgentDelegationPlan) -> str | None:
    for run in delegation.runs:
        if run.role in {AgentRole.ORCHESTRATOR, AgentRole.PLANNER} and run.model_id:
            return run.model_id
    return delegation.runs[0].model_id if delegation.runs else None


def _validate_task_draft(tasks: list[AgentTeamTaskDraft]) -> None:
    if not 1 <= len(tasks) <= 8:
        raise ValueError("Agent Team planning requires between 1 and 8 tasks.")
    seen: set[str] = set()
    for task in tasks:
        if not task.goal.strip():
            raise ValueError(f"Planned task {task.key} is missing a goal.")
        if task.key in seen:
            raise ValueError(f"Planned task {task.key} is duplicated.")
        for dependency in task.dependencies:
            if dependency not in seen:
                raise ValueError(
                    f"Planned task {task.key} has an unknown or cyclic dependency: {dependency}."
                )
        seen.add(task.key)


def _plan_hash(
    session: AgentTeamSession,
    options: AgentTeamPlanOptions,
    draft: AgentTeamPlanDraft,
) -> str:
    payload = {
        "goal": session.goal,
        "options": {
            "granularity": options.granularity,
            "focus": options.focus,
            "max_tasks": options.max_tasks,
        },
        "source": draft.planning_source,
        "tasks": [
            task.model_dump(
                mode="json",
                exclude={"sort_order"},
            )
            for task in draft.tasks
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_unstarted(task: AgentTeamTask) -> bool:
    return (
        task.status == AgentTeamTaskStatus.PENDING
        and not task.started_at
        and not task.run_status
        and not task.execution_status
        and not task.agent_run_id
        and not task.output_artifact_ids
    )


__all__ = [
    "AgentTeamPlanDraft",
    "AgentTeamPlanOptions",
    "AgentTeamPlanningMixin",
    "AgentTeamPlanningService",
    "AgentTeamTaskDraft",
]
