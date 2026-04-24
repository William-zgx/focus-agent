from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Literal

from langchain.messages import ToolMessage
from pydantic import Field

from .config import Settings
from .core.context_policy import assemble_context
from .core.types import ContextBudget, PromptMode, StateModel


ContextArtifactSource = Literal["tool_observation", "rolling_summary", "assembled_context"]


class ContextBudgetDecision(StateModel):
    enabled: bool = False
    mode: str = "disabled"
    prompt_chars: int = 0
    prompt_budget_chars: int = 0
    estimated_prompt_tokens: int = 0
    over_budget_chars: int = 0
    tokenizer_mode: str = "chars_fallback"
    tokenizer_id: str | None = None


class ContextCompressionItem(StateModel):
    source: str
    action: str
    original_chars: int
    target_chars: int
    reason: str = ""


class ContextCompressionPlan(StateModel):
    enabled: bool = False
    strategy: str = "none"
    items: list[ContextCompressionItem] = Field(default_factory=list)
    estimated_saved_chars: int = 0


class ContextArtifactRef(StateModel):
    artifact_id: str
    title: str
    source: ContextArtifactSource
    uri: str | None = None
    summary: str = ""
    original_chars: int = 0
    prompt_chars: int = 0
    materialized: bool = False


class RoleContextView(StateModel):
    role: str
    included_sections: list[str] = Field(default_factory=list)
    excluded_sections: list[str] = Field(default_factory=list)
    memory_scope: str = "thread"
    budget_ratio: float = 1.0


class ContextEngineeringDecision(StateModel):
    enabled: bool = False
    created_at: str
    budget: ContextBudgetDecision = Field(default_factory=ContextBudgetDecision)
    compression_plan: ContextCompressionPlan = Field(default_factory=ContextCompressionPlan)
    artifact_refs: list[ContextArtifactRef] = Field(default_factory=list)
    role_context_views: list[RoleContextView] = Field(default_factory=list)
    compressed_prompt: str | None = None
    policy: dict[str, Any] = Field(default_factory=dict)


def build_context_policy(settings: Settings | Any) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings, "agent_context_engineering_v2_enabled", False)),
        "artifactize_long_observations": bool(
            getattr(settings, "agent_context_artifactize_long_observations", False)
        ),
        "role_views_enabled": bool(getattr(settings, "agent_context_role_views_enabled", False)),
        "tokenizer_mode": str(getattr(settings, "agent_context_tokenizer_mode", "chars_fallback")),
        "artifact_min_chars": int(getattr(settings, "agent_context_artifact_min_chars", 12000) or 12000),
        "default_off_legacy_safe": True,
    }


def build_context_engineering_decision(
    *,
    settings: Settings | Any,
    state: dict[str, Any],
    prompt_mode: PromptMode | str,
    assembled_context: str | None = None,
    role: str = "executor",
    artifact_dir: str | Path | None = None,
    materialize: bool | None = None,
) -> ContextEngineeringDecision:
    policy = build_context_policy(settings)
    enabled = bool(policy["enabled"])
    budget = _coerce_budget(state.get("context_budget"))
    rendered_prompt = assembled_context
    if rendered_prompt is None:
        rendered_prompt = assemble_context(state, prompt_mode).render_prompt()
    prompt_chars = len(rendered_prompt)
    prompt_budget_chars = int(budget.prompt_token_limit) * max(1, int(budget.chars_per_token))
    budget_decision = ContextBudgetDecision(
        enabled=enabled,
        mode="observe" if enabled else "disabled",
        prompt_chars=prompt_chars,
        prompt_budget_chars=prompt_budget_chars,
        estimated_prompt_tokens=max(1, prompt_chars // max(1, int(budget.chars_per_token))) if prompt_chars else 0,
        over_budget_chars=max(0, prompt_chars - prompt_budget_chars),
        tokenizer_mode=str(policy["tokenizer_mode"]),
        tokenizer_id=budget.tokenizer_id,
    )
    compression_items = _compression_items(
        state=state,
        prompt_chars=prompt_chars,
        prompt_budget_chars=prompt_budget_chars,
    )
    compression_plan = ContextCompressionPlan(
        enabled=enabled and bool(compression_items),
        strategy="semantic_summary_plus_refs" if compression_items else "none",
        items=compression_items,
        estimated_saved_chars=sum(max(0, item.original_chars - item.target_chars) for item in compression_items),
    )
    artifact_refs = _context_artifact_refs(
        state=state,
        assembled_context=rendered_prompt,
        min_chars=int(policy["artifact_min_chars"]),
        artifact_dir=Path(artifact_dir).expanduser() if artifact_dir else None,
        materialize=enabled
        and bool(policy["artifactize_long_observations"])
        and (bool(policy["artifactize_long_observations"]) if materialize is None else materialize),
    )
    role_views = _role_context_views(enabled=enabled and bool(policy["role_views_enabled"]), role=role)
    compressed_prompt = None
    if enabled and budget_decision.over_budget_chars > 0:
        compressed_prompt = _compress_prompt_with_refs(
            rendered_prompt,
            artifact_refs=artifact_refs,
            target_chars=prompt_budget_chars,
        )
    return ContextEngineeringDecision(
        enabled=enabled,
        created_at=datetime.now(timezone.utc).isoformat(),
        budget=budget_decision,
        compression_plan=compression_plan,
        artifact_refs=artifact_refs,
        role_context_views=role_views,
        compressed_prompt=compressed_prompt,
        policy=policy,
    )


def _coerce_budget(value: Any) -> ContextBudget:
    if isinstance(value, ContextBudget):
        return value
    if isinstance(value, dict):
        try:
            return ContextBudget.model_validate(value)
        except Exception:  # noqa: BLE001
            return ContextBudget()
    return ContextBudget()


def _compression_items(
    *,
    state: dict[str, Any],
    prompt_chars: int,
    prompt_budget_chars: int,
) -> list[ContextCompressionItem]:
    items: list[ContextCompressionItem] = []
    summary = str(state.get("rolling_summary") or "")
    if len(summary) > 4000:
        items.append(
            ContextCompressionItem(
                source="rolling_summary",
                action="semantic_summary",
                original_chars=len(summary),
                target_chars=2000,
                reason="Long rolling summary should become a concise semantic digest.",
            )
        )
    for index, message in enumerate(state.get("messages") or []):
        if isinstance(message, ToolMessage):
            size = len(str(message.content or ""))
            if size > 4000:
                items.append(
                    ContextCompressionItem(
                        source=f"tool_message:{index}",
                        action="artifact_ref",
                        original_chars=size,
                        target_chars=600,
                        reason="Long tool observations should be replaced by artifact references in prompt view.",
                    )
                )
    if prompt_chars > prompt_budget_chars:
        items.append(
            ContextCompressionItem(
                source="assembled_context",
                action="priority_block_trim",
                original_chars=prompt_chars,
                target_chars=prompt_budget_chars,
                reason="Assembled context exceeds configured prompt budget.",
            )
        )
    return items


def _context_artifact_refs(
    *,
    state: dict[str, Any],
    assembled_context: str,
    min_chars: int,
    artifact_dir: Path | None,
    materialize: bool,
) -> list[ContextArtifactRef]:
    refs: list[ContextArtifactRef] = []
    for index, message in enumerate(state.get("messages") or []):
        if not isinstance(message, ToolMessage):
            continue
        content = str(message.content or "")
        if len(content) < min_chars:
            continue
        refs.append(
            _build_artifact_ref(
                source="tool_observation",
                title=f"Long tool observation {index + 1}",
                body=content,
                artifact_dir=artifact_dir,
                materialize=materialize,
            )
        )
    summary = str(state.get("rolling_summary") or "")
    if len(summary) >= min_chars:
        refs.append(
            _build_artifact_ref(
                source="rolling_summary",
                title="Long rolling summary",
                body=summary,
                artifact_dir=artifact_dir,
                materialize=materialize,
            )
        )
    if len(assembled_context) >= max(min_chars * 2, 1):
        refs.append(
            _build_artifact_ref(
                source="assembled_context",
                title="Assembled context snapshot",
                body=assembled_context,
                artifact_dir=artifact_dir,
                materialize=False,
            )
        )
    return refs


def _build_artifact_ref(
    *,
    source: ContextArtifactSource,
    title: str,
    body: str,
    artifact_dir: Path | None,
    materialize: bool,
) -> ContextArtifactRef:
    digest = sha256(body.encode("utf-8")).hexdigest()[:16]
    artifact_id = f"context/{source}-{digest}.txt"
    uri = None
    written = False
    if materialize and artifact_dir is not None:
        path = artifact_dir / artifact_id
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        uri = str(path)
        written = True
    return ContextArtifactRef(
        artifact_id=artifact_id,
        title=title,
        source=source,
        uri=uri,
        summary=_summarize_text(body),
        original_chars=len(body),
        prompt_chars=min(600, len(body)),
        materialized=written,
    )


def _role_context_views(*, enabled: bool, role: str) -> list[RoleContextView]:
    if not enabled:
        return []
    profiles = {
        "planner": (["task_brief", "constraints", "summary", "approved_findings"], ["raw_tool_observations"], 0.7),
        "executor": (["task_brief", "constraints", "recent_messages", "tool_refs", "artifacts"], [], 1.0),
        "critic": (["task_brief", "acceptance_criteria", "artifacts", "citations"], ["branch_local_memory"], 0.55),
        "memory_curator": (["memory_scope", "branch_findings", "imported_findings"], ["raw_tool_observations"], 0.45),
        "skill_scout": (["task_brief", "available_skills", "tool_capabilities"], ["durable_memory"], 0.35),
    }
    ordered_roles = list(dict.fromkeys([role, "planner", "executor", "critic", "memory_curator", "skill_scout"]))
    views: list[RoleContextView] = []
    for role_name in ordered_roles:
        included, excluded, ratio = profiles.get(role_name, profiles["executor"])
        views.append(
            RoleContextView(
                role=role_name,
                included_sections=list(included),
                excluded_sections=list(excluded),
                memory_scope="branch_local" if role_name == "memory_curator" else "thread",
                budget_ratio=ratio,
            )
        )
    return views


def _compress_prompt_with_refs(
    prompt: str,
    *,
    artifact_refs: Iterable[ContextArtifactRef],
    target_chars: int,
) -> str:
    if len(prompt) <= target_chars:
        return prompt
    ref_lines = [
        f"- {ref.title}: {ref.artifact_id} ({ref.source}, {ref.original_chars} chars)"
        for ref in artifact_refs
    ]
    refs_block = "\n\n## Context artifacts\n" + "\n".join(ref_lines) if ref_lines else ""
    keep = max(800, target_chars - len(refs_block) - 80)
    head = prompt[: keep // 2].rstrip()
    tail = prompt[-(keep // 2) :].lstrip()
    return f"{head}\n\n...[context compressed by Context Engineering v2]...\n\n{tail}{refs_block}".strip()


def _summarize_text(text: str, *, max_chars: int = 320) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 15].rstrip()} ...[trimmed]"


__all__ = [
    "ContextArtifactRef",
    "ContextBudgetDecision",
    "ContextCompressionItem",
    "ContextCompressionPlan",
    "ContextEngineeringDecision",
    "RoleContextView",
    "build_context_engineering_decision",
    "build_context_policy",
]
