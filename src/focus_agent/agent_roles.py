from __future__ import annotations

from enum import Enum
from typing import Iterable, Mapping

from pydantic import Field

from .config import Settings
from .core.types import StateModel
from .model_registry import canonical_model_id


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    EXECUTOR = "executor"
    CRITIC = "critic"
    MEMORY_CURATOR = "memory_curator"
    SKILL_SCOUT = "skill_scout"


_ROLE_SETTING_ATTRS: Mapping[AgentRole, str] = {
    AgentRole.ORCHESTRATOR: "agent_role_orchestrator_model",
    AgentRole.PLANNER: "agent_role_planner_model",
    AgentRole.EXECUTOR: "agent_role_executor_model",
    AgentRole.CRITIC: "agent_role_critic_model",
    AgentRole.MEMORY_CURATOR: "agent_role_memory_model",
    AgentRole.SKILL_SCOUT: "agent_role_skill_model",
}

_ROLE_ALIASES: Mapping[str, AgentRole] = {
    "architect": AgentRole.ORCHESTRATOR,
    "coordinator": AgentRole.ORCHESTRATOR,
    "research": AgentRole.PLANNER,
    "researcher": AgentRole.PLANNER,
    "analyst": AgentRole.PLANNER,
    "coding": AgentRole.EXECUTOR,
    "backend": AgentRole.EXECUTOR,
    "frontend": AgentRole.EXECUTOR,
    "review": AgentRole.CRITIC,
    "qa": AgentRole.CRITIC,
    "tester": AgentRole.CRITIC,
    "memory": AgentRole.MEMORY_CURATOR,
    "memory_curator": AgentRole.MEMORY_CURATOR,
    "skill": AgentRole.SKILL_SCOUT,
    "skill_scout": AgentRole.SKILL_SCOUT,
}

_PLANNER_MARKERS = (
    "plan",
    "design",
    "research",
    "analyze",
    "compare",
    "investigate",
    "search",
    "lookup",
    "architecture",
    "方案",
    "规划",
    "联网",
    "搜索",
    "分析",
    "对比",
    "调研",
)
_EXECUTOR_MARKERS = (
    "implement",
    "fix",
    "change",
    "modify",
    "refactor",
    "backend",
    "frontend",
    "runtime",
    "test",
    "实现",
    "修复",
    "修改",
    "代码",
    "测试",
)
_CRITIC_MARKERS = (
    "review",
    "verify",
    "validate",
    "qa",
    "regression",
    "审核",
    "验证",
    "检查",
    "回归",
)
_MEMORY_MARKERS = (
    "memory",
    "remember",
    "promotion",
    "promote",
    "记忆",
    "沉淀",
    "晋升",
)
_SKILL_MARKERS = (
    "skill",
    "tool",
    "toolset",
    "技能",
    "工具",
)

_ROLE_GOVERNANCE: Mapping[AgentRole, tuple[str, ...]] = {
    AgentRole.ORCHESTRATOR: ("conversation_summary", "skills_list", "skill_view"),
    AgentRole.PLANNER: (
        "web_search",
        "web_fetch",
        "current_utc_time",
        "search_code",
        "read_file",
        "conversation_summary",
        "skills_list",
        "skill_view",
    ),
    AgentRole.EXECUTOR: (
        "list_files",
        "read_file",
        "search_code",
        "codebase_stats",
        "git_status",
        "git_diff",
        "artifact_list",
        "artifact_read",
        "artifact_update",
        "write_text_artifact",
    ),
    AgentRole.CRITIC: (
        "list_files",
        "read_file",
        "search_code",
        "git_status",
        "git_diff",
        "git_log",
        "artifact_list",
        "artifact_read",
    ),
    AgentRole.MEMORY_CURATOR: (
        "memory_search",
        "conversation_summary",
        "artifact_list",
        "artifact_read",
    ),
    AgentRole.SKILL_SCOUT: (
        "skills_list",
        "skill_view",
        "conversation_summary",
    ),
}


class RoleToolGovernance(StateModel):
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    allow_network: bool = False
    allow_workspace_write: bool = False


class AgentDecision(StateModel):
    role: AgentRole
    model_id: str
    task_slice: str
    rationale: str
    tool_governance: RoleToolGovernance = Field(default_factory=RoleToolGovernance)
    run_isolation_key: str
    depends_on: list[str] = Field(default_factory=list)
    dry_run: bool = True


class RoleRoutePlan(StateModel):
    enabled: bool = False
    source: str = "dry_run"
    route_reason: str = ""
    orchestrator_model_id: str | None = None
    max_parallel_runs: int = 1
    decisions: list[AgentDecision] = Field(default_factory=list)
    legacy_execution_unchanged: bool = True


class RoleModelResolver:
    def __init__(self, settings: Settings):
        self._settings = settings

    def resolve(self, role: AgentRole | str, *, fallback_model: str | None = None) -> str:
        normalized_role = normalize_agent_role(role)
        configured_model = getattr(
            self._settings,
            _ROLE_SETTING_ATTRS[normalized_role],
            None,
        )
        if normalized_role == AgentRole.EXECUTOR:
            model_id = (
                configured_model
                or fallback_model
                or getattr(self._settings, "model", None)
                or getattr(self._settings, "helper_model", None)
            )
        else:
            model_id = (
                configured_model
                or fallback_model
                or getattr(self._settings, "helper_model", None)
                or getattr(self._settings, "model", None)
            )
        return canonical_model_id(model_id, settings=self._settings)

    def mapping(self, roles: Iterable[AgentRole | str]) -> dict[AgentRole, str]:
        return {normalize_agent_role(role): self.resolve(role) for role in roles}


def normalize_agent_role(role: AgentRole | str) -> AgentRole:
    if isinstance(role, AgentRole):
        return role
    normalized = str(role or "").strip().lower().replace("-", "_")
    aliased = _ROLE_ALIASES.get(normalized)
    if aliased is not None:
        return aliased
    return AgentRole(normalized)


def infer_role_candidates(task_text: str, *, max_parallel_runs: int) -> list[AgentRole]:
    normalized = task_text.lower()
    candidates: list[AgentRole] = []
    if _contains_any(normalized, _PLANNER_MARKERS):
        candidates.append(AgentRole.PLANNER)
    if _contains_any(normalized, _EXECUTOR_MARKERS):
        candidates.append(AgentRole.EXECUTOR)
    if _contains_any(normalized, _CRITIC_MARKERS):
        candidates.append(AgentRole.CRITIC)
    if _contains_any(normalized, _MEMORY_MARKERS):
        candidates.append(AgentRole.MEMORY_CURATOR)
    if _contains_any(normalized, _SKILL_MARKERS):
        candidates.append(AgentRole.SKILL_SCOUT)
    if not candidates:
        candidates.append(AgentRole.EXECUTOR)
    return list(dict.fromkeys(candidates))[: max(1, max_parallel_runs)]


def build_role_route_plan(
    *,
    settings: Settings,
    task_text: str,
    available_tool_names: Iterable[str] = (),
    tool_policy: str = "",
) -> RoleRoutePlan:
    if not settings.agent_role_routing_enabled:
        return RoleRoutePlan(
            enabled=False,
            route_reason="AGENT_ROLE_ROUTING_ENABLED is off.",
            max_parallel_runs=max(1, settings.agent_role_max_parallel_runs),
        )

    max_parallel_runs = max(1, settings.agent_role_max_parallel_runs)
    resolver = RoleModelResolver(settings)
    tool_names = tuple(dict.fromkeys(str(name) for name in available_tool_names if str(name)))
    selected_roles = infer_role_candidates(task_text, max_parallel_runs=max_parallel_runs)
    orchestrator_model_id = resolver.resolve(AgentRole.ORCHESTRATOR)
    decisions = [
        AgentDecision(
            role=AgentRole.ORCHESTRATOR,
            model_id=orchestrator_model_id,
            task_slice=_compact_task_slice(task_text) or "Coordinate this turn.",
            rationale="Coordinate the dry-run role routing decision before isolated role runs.",
            tool_governance=_governance_for(AgentRole.ORCHESTRATOR, tool_names),
            run_isolation_key="role:orchestrator",
        )
    ]
    for role in selected_roles:
        decisions.append(
            AgentDecision(
                role=role,
                model_id=resolver.resolve(role),
                task_slice=_task_slice_for_role(role, task_text),
                rationale=_rationale_for_role(role, tool_policy),
                tool_governance=_governance_for(role, tool_names),
                run_isolation_key=f"role:{role.value}",
                depends_on=["role:orchestrator"],
            )
        )

    return RoleRoutePlan(
        enabled=True,
        route_reason=f"Dry-run route selected {len(selected_roles)} delegated role run(s).",
        orchestrator_model_id=orchestrator_model_id,
        max_parallel_runs=max_parallel_runs,
        decisions=decisions,
    )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _compact_task_slice(task_text: str, *, max_chars: int = 240) -> str:
    compacted = " ".join(task_text.strip().split())
    if len(compacted) <= max_chars:
        return compacted
    return f"{compacted[: max_chars - 3]}..."


def _task_slice_for_role(role: AgentRole, task_text: str) -> str:
    base = _compact_task_slice(task_text)
    if role == AgentRole.PLANNER:
        return f"Plan isolated role runs and success criteria for: {base}"
    if role == AgentRole.EXECUTOR:
        return f"Execute the approved implementation slice for: {base}"
    if role == AgentRole.CRITIC:
        return f"Critique completion quality and regression risk for: {base}"
    if role == AgentRole.MEMORY_CURATOR:
        return f"Preview memory candidates and branch promotion safety for: {base}"
    if role == AgentRole.SKILL_SCOUT:
        return f"Select relevant skills and toolsets for: {base}"
    return base


def _rationale_for_role(role: AgentRole, tool_policy: str) -> str:
    if role == AgentRole.PLANNER:
        return f"Task text suggests planning or investigation; tool policy is {tool_policy or 'unspecified'}."
    if role == AgentRole.EXECUTOR:
        return f"Task text suggests implementation work; tool policy is {tool_policy or 'unspecified'}."
    if role == AgentRole.CRITIC:
        return f"Task text suggests validation or review; tool policy is {tool_policy or 'unspecified'}."
    if role == AgentRole.MEMORY_CURATOR:
        return f"Task text suggests memory or promotion governance; tool policy is {tool_policy or 'unspecified'}."
    if role == AgentRole.SKILL_SCOUT:
        return f"Task text suggests skill or tool selection; tool policy is {tool_policy or 'unspecified'}."
    return "Coordinate role routing."


def _governance_for(role: AgentRole, available_tool_names: tuple[str, ...]) -> RoleToolGovernance:
    allowlist = _ROLE_GOVERNANCE.get(role, ())
    allowed = [name for name in available_tool_names if name in allowlist]
    denied = [name for name in available_tool_names if name not in allowlist]
    return RoleToolGovernance(
        allowed_tools=allowed,
        denied_tools=denied,
        allow_network=any(name in allowed for name in ("web_search", "web_fetch", "current_utc_time")),
        allow_workspace_write=any(name in allowed for name in ("write_text_artifact", "artifact_update")),
    )


__all__ = [
    "AgentDecision",
    "AgentRole",
    "RoleModelResolver",
    "RoleRoutePlan",
    "RoleToolGovernance",
    "build_role_route_plan",
    "infer_role_candidates",
    "normalize_agent_role",
]
