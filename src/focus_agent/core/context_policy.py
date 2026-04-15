from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from langchain.messages import AIMessage, AnyMessage, ToolMessage

from .types import ArtifactRef, ConstraintItem, ContextBudget, FindingItem, PinnedFact, PromptMode
from .state import normalize_agent_state


@dataclass(slots=True)
class ContextSlice:
    system_instructions: str
    recent_messages: list[AnyMessage]
    active_skills_block: str
    available_skills_block: str
    memory_block: str
    summary_block: str
    pinned_block: str
    constraints_block: str
    findings_block: str
    artifact_block: str

    def render_prompt(self) -> str:
        return "\n\n".join(
            block
            for block in [
                self.system_instructions,
                self.active_skills_block,
                self.available_skills_block,
                self.memory_block,
                self.summary_block,
                self.pinned_block,
                self.constraints_block,
                self.findings_block,
                self.artifact_block,
            ]
            if block
        )


def assemble_context(state: dict[str, Any], mode: PromptMode | str) -> ContextSlice:
    normalized = normalize_agent_state(state)
    prompt_mode = _coerce_prompt_mode(mode or normalized.get("prompt_mode"))
    budget = _coerce_context_budget(normalized.get("context_budget"))
    branch_meta = normalized.get("branch_meta") or {}
    is_branch = bool(branch_meta)

    messages = list(normalized.get("messages", []) or normalized.get("recent_messages", []))
    recent_messages = _conversation_safe_messages(messages, limit=budget.recent_message_limit)

    memory_lines = [str(item) for item in state.get("_memory_lines", [])][-budget.citation_limit :]
    memory_block = normalized.get("memory_prompt_block") or _render_lines(
        "Retrieved long-term memories",
        memory_lines,
    )
    active_skills_block = str(
        state.get("_active_skills_block")
        or normalized.get("active_skills_block")
        or ""
    ).strip()
    available_skills_block = str(
        state.get("_available_skills_block")
        or normalized.get("available_skills_block")
        or ""
    ).strip()
    scene = str(state.get("_scene") or "long_dialog_research")

    pinned_facts = _coerce_pinned_facts(normalized.get("pinned_facts", []))
    pinned_lines = [item.fact for item in pinned_facts]
    pinned_lines.extend(str(item) for item in normalized.get("pinned_items", []))

    constraints = _coerce_constraints(normalized.get("user_constraints", []))
    constraint_lines = [item.constraint for item in constraints]
    if normalized.get("active_goal"):
        constraint_lines.insert(0, f"Active goal: {normalized['active_goal']}")

    imported_lines = _coerce_imported_lines(normalized.get("imported_findings", []))
    legacy_imported_lines = _coerce_legacy_imported_lines(normalized.get("merge_queue", []))

    local_finding_lines: list[str] = []
    if is_branch and prompt_mode in {PromptMode.EXPLORE, PromptMode.EXECUTE, PromptMode.BRANCH_REVIEW}:
        local_finding_lines = _coerce_local_finding_lines(
            normalized.get("branch_local_findings", []),
            limit=budget.findings_limit,
        )

    artifact_lines = _coerce_artifact_lines(
        normalized.get("artifacts", []),
        limit=budget.artifact_limit,
        include_local=is_branch and prompt_mode != PromptMode.SYNTHESIZE,
    )

    imported_lines = (imported_lines + legacy_imported_lines)[-budget.findings_limit :]

    system_instructions = "\n\n".join(
        [
            "You are Focus Agent, a concise research-oriented assistant optimized for long dialogues.",
            _mode_instructions(prompt_mode),
            _skill_system_block(
                has_available_skills=bool(available_skills_block),
                has_active_skills=bool(active_skills_block),
            ),
            f"## Scene\n- {scene}",
            _branch_scope_block(branch_meta=branch_meta, is_branch=is_branch),
            _render_lines("Retrieved long-term memories", memory_lines),
        ]
    )

    findings_sections: list[str] = []
    if imported_lines:
        findings_sections.append(_render_lines("Imported findings already approved into this thread", imported_lines))
    if local_finding_lines:
        findings_sections.append(_render_lines("Local branch findings pending upstream review", local_finding_lines))
    findings_block = "\n\n".join(findings_sections) if findings_sections else _render_lines("Findings", [])

    return ContextSlice(
        system_instructions=system_instructions,
        recent_messages=recent_messages,
        active_skills_block=active_skills_block,
        available_skills_block=available_skills_block,
        memory_block=memory_block,
        summary_block=f"## Rolling summary\n{normalized.get('rolling_summary') or '(empty)'}",
        pinned_block=_render_lines("Pinned facts", pinned_lines[-10:]),
        constraints_block=_render_lines("Constraints and goals", constraint_lines[-10:]),
        findings_block=findings_block,
        artifact_block=_render_lines("Artifacts in scope", artifact_lines),
    )


def _coerce_prompt_mode(mode: PromptMode | str | None) -> PromptMode:
    if isinstance(mode, PromptMode):
        return mode
    if isinstance(mode, str):
        try:
            return PromptMode(mode)
        except ValueError:
            return PromptMode.EXPLORE
    return PromptMode.EXPLORE


def _conversation_safe_messages(messages: list[AnyMessage], *, limit: int) -> list[AnyMessage]:
    safe_messages: list[AnyMessage] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            continue
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            continue
        safe_messages.append(message)
    return safe_messages[-limit:]


def _coerce_context_budget(value: Any) -> ContextBudget:
    if isinstance(value, ContextBudget):
        return value
    if isinstance(value, dict):
        return ContextBudget.model_validate(value)
    return ContextBudget()


def _coerce_pinned_facts(values: Iterable[Any]) -> list[PinnedFact]:
    facts: list[PinnedFact] = []
    for value in values:
        if isinstance(value, PinnedFact):
            facts.append(value)
        elif isinstance(value, dict):
            facts.append(PinnedFact.model_validate(value))
        elif value:
            facts.append(PinnedFact(fact=str(value)))
    return facts


def _coerce_constraints(values: Iterable[Any]) -> list[ConstraintItem]:
    constraints: list[ConstraintItem] = []
    for value in values:
        if isinstance(value, ConstraintItem):
            constraints.append(value)
        elif isinstance(value, dict):
            constraints.append(ConstraintItem.model_validate(value))
        elif value:
            constraints.append(ConstraintItem(constraint=str(value)))
    return constraints


def _coerce_local_finding_lines(values: Iterable[Any], *, limit: int) -> list[str]:
    findings: list[str] = []
    for value in values:
        finding = _finding_to_line(value)
        if finding:
            findings.append(finding)
    return findings[-limit:]


def _coerce_imported_lines(values: Iterable[Any]) -> list[str]:
    findings: list[str] = []
    for value in values:
        if isinstance(value, FindingItem):
            findings.append(_finding_to_line(value))
        elif isinstance(value, dict):
            findings.append(_finding_to_line(FindingItem.model_validate(value)))
        elif value:
            findings.append(str(value))
    return [line for line in findings if line]


def _coerce_legacy_imported_lines(values: Iterable[Any]) -> list[str]:
    lines: list[str] = []
    for value in values:
        if isinstance(value, dict):
            branch_label = value.get("branch_name") or value.get("branch_id") or "branch"
            summary = value.get("summary") or ""
            if summary:
                lines.append(f"[{branch_label}] {summary}")
        elif value:
            lines.append(str(value))
    return lines


def _coerce_artifact_lines(values: Iterable[Any], *, limit: int, include_local: bool) -> list[str]:
    if not include_local:
        return []

    lines: list[str] = []
    for value in values:
        if isinstance(value, ArtifactRef):
            lines.append(_artifact_to_line(value))
        elif isinstance(value, dict):
            lines.append(_artifact_to_line(ArtifactRef.model_validate(value)))
        elif value:
            lines.append(str(value))
    return [line for line in lines if line][-limit:]


def _artifact_to_line(artifact: ArtifactRef) -> str:
    location = f" ({artifact.uri})" if artifact.uri else ""
    return f"{artifact.title} [{artifact.kind}]{location}"


def _finding_to_line(value: Any) -> str:
    if isinstance(value, FindingItem):
        confidence = "" if value.confidence is None else f" (confidence {value.confidence:.2f})"
        refs = "" if not value.evidence_refs else f" [evidence: {', '.join(value.evidence_refs)}]"
        return f"{value.finding}{confidence}{refs}"
    if isinstance(value, dict):
        return _finding_to_line(FindingItem.model_validate(value))
    return str(value)


def _branch_scope_block(*, branch_meta: dict[str, Any], is_branch: bool) -> str:
    if not is_branch:
        return "## Branch scope\n- This is the main thread."

    policy_lines = [
        "- This is a child branch. Stay focused on this local exploration.",
        "- This branch may later be reviewed for upstream import into its return thread.",
        "- Do not assume local branch findings are upstream facts until they are explicitly approved.",
        "- Prepare import-worthy findings clearly, but treat them as local until approved.",
    ]

    lines = [
        "## Branch scope",
        f"- branch_id: {branch_meta.get('branch_id')}",
        f"- branch_name: {branch_meta.get('branch_name')}",
        f"- branch_role: {branch_meta.get('branch_role')}",
        *policy_lines,
    ]
    return "\n".join(lines)


def _mode_instructions(mode: PromptMode) -> str:
    instructions = {
        PromptMode.EXPLORE: (
            "## Prompt mode\n"
            "- explore\n"
            "- Explore hypotheses, surface uncertainties, and keep local conclusions clearly scoped."
        ),
        PromptMode.EXECUTE: (
            "## Prompt mode\n"
            "- execute\n"
            "- Prioritize concrete next steps, follow user constraints closely, and avoid speculative branches."
        ),
        PromptMode.SYNTHESIZE: (
            "## Prompt mode\n"
            "- synthesize\n"
            "- Consolidate approved information into a clean answer and avoid surfacing unreviewed branch-local findings."
        ),
        PromptMode.BRANCH_REVIEW: (
            "## Prompt mode\n"
            "- branch_review\n"
            "- Prepare the conversation for merge review by highlighting import-worthy findings, evidence, and artifacts."
        ),
    }
    return instructions[mode]


def _skill_system_block(*, has_available_skills: bool, has_active_skills: bool) -> str:
    if not has_available_skills and not has_active_skills:
        return ""

    lines = ["## Skill system"]
    if has_active_skills:
        lines.append("- Active skills are attached below and should shape the current turn.")
    if has_available_skills:
        lines.append("- Available skill prefixes are listed below for future turns and explicit activation.")
    return "\n".join(lines)


def _render_lines(title: str, lines: list[str]) -> str:
    if not lines:
        return f"## {title}\n(none)"
    return "## " + title + "\n" + "\n".join(f"- {line}" for line in lines)
