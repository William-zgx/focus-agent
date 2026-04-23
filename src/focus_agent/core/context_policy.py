from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import importlib
import json
import re
from typing import Any, Iterable

from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

from .types import ArtifactRef, ConstraintItem, ContextBudget, FindingItem, PinnedFact, PromptMode
from .state import normalize_agent_state


_LINE_SCORE_RE = re.compile(r"\[score\s+([0-9.]+)\]\s*$", re.IGNORECASE)
_LINE_CONFIDENCE_RE = re.compile(r"\(confidence\s+([0-9.]+)\)", re.IGNORECASE)
_LINE_EVIDENCE_RE = re.compile(r"\[evidence:\s*([^\]]+)\]", re.IGNORECASE)
_LINE_SOURCE_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*")
_ARTIFACT_URI_RE = re.compile(r"\(([^()\s]+)\)\s*$")
_ARTIFACT_LINE_RE = re.compile(r"^(?P<title>.+?)\s\[(?P<kind>[^\[\]]+)\](?:\s\((?P<uri>[^()]+)\))?$")


@dataclass(slots=True)
class _PromptFindingCandidate:
    line: str
    section: str
    dedupe_key: str
    confidence: float
    evidence_count: int
    recency_order: int
    promoted: bool


@dataclass(slots=True)
class _PromptMemoryCandidate:
    line: str
    dedupe_key: str
    promoted: bool
    confidence: float
    evidence_count: int
    score: float
    recency_order: int


@dataclass(slots=True)
class _PromptArtifactCandidate:
    line: str
    dedupe_key: str
    has_artifact_id: bool
    has_uri: bool
    has_summary: bool
    recency_order: int


@dataclass(slots=True)
class _PromptTextCandidate:
    line: str
    dedupe_key: str
    promoted: bool
    confidence: float
    evidence_count: int
    score: float
    has_uri: bool
    recency_order: int


@dataclass(slots=True)
class ContextSlice:
    prompt_mode: PromptMode
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
        section_map = {
            "system_instructions": self.system_instructions,
            "active_skills_block": self.active_skills_block,
            "available_skills_block": self.available_skills_block,
            "memory_block": self.memory_block,
            "summary_block": self.summary_block,
            "pinned_block": self.pinned_block,
            "constraints_block": self.constraints_block,
            "findings_block": self.findings_block,
            "artifact_block": self.artifact_block,
        }
        ordered_keys = _render_block_order(self.prompt_mode)
        return "\n\n".join(
            section_map[key]
            for key in ordered_keys
            if section_map.get(key)
        )


def assemble_context(state: dict[str, Any], mode: PromptMode | str) -> ContextSlice:
    normalized = normalize_agent_state(state)
    prompt_mode = _coerce_prompt_mode(mode or normalized.get("prompt_mode"))
    budget = _coerce_context_budget(normalized.get("context_budget"))
    branch_meta = normalized.get("branch_meta") or {}
    is_branch = bool(branch_meta)

    messages = list(normalized.get("messages", []) or normalized.get("recent_messages", []))
    recent_messages = _conversation_safe_messages(messages, limit=budget.recent_message_limit)

    memory_lines = _dedupe_memory_lines(
        [str(item) for item in state.get("_memory_lines", [])],
        limit=budget.citation_limit,
    )
    memory_block = str(normalized.get("memory_prompt_block") or "").strip()
    if not memory_block:
        memory_block = _render_lines("Retrieved long-term memories", memory_lines)
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
    pinned_lines = _dedupe_text_lines(pinned_lines, limit=10)

    constraints = _coerce_constraints(normalized.get("user_constraints", []))
    constraint_lines = [item.constraint for item in constraints]
    if normalized.get("active_goal"):
        constraint_lines.insert(0, f"Active goal: {normalized['active_goal']}")
    current_step_goal = _current_plan_step_goal(normalized)
    if current_step_goal:
        constraint_lines.insert(1 if constraint_lines else 0, f"Current step: {current_step_goal}")
    constraint_lines = _dedupe_text_lines(constraint_lines, limit=10)

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

    imported_lines = _dedupe_finding_lines(imported_lines + legacy_imported_lines, limit=budget.findings_limit)
    local_finding_lines = _dedupe_preferring_reference(imported_lines, local_finding_lines, limit=budget.findings_limit)
    artifact_lines = _dedupe_artifact_lines(artifact_lines, limit=budget.artifact_limit)

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
        ]
    )

    findings_sections: list[str] = []
    if imported_lines:
        findings_sections.append(_render_lines("Imported findings already approved into this thread", imported_lines))
    if local_finding_lines:
        findings_sections.append(_render_lines("Local branch findings pending upstream review", local_finding_lines))
    findings_block = "## Findings\n" + "\n".join(findings_sections) if findings_sections else _render_lines("Findings", [])

    return ContextSlice(
        prompt_mode=prompt_mode,
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


def approximate_token_count(
    value: Any,
    *,
    chars_per_token: int = 4,
    tokenizer_id: str | None = None,
) -> int:
    text = _text_for_budget(value)
    if not text:
        return 0
    return _estimate_text_tokens(
        text,
        chars_per_token=chars_per_token,
        tokenizer_id=tokenizer_id,
        tokenizer_first=bool(tokenizer_id),
    )


def apply_prompt_budget_guard(
    prompt_messages: list[AnyMessage],
    *,
    budget: ContextBudget,
) -> list[AnyMessage]:
    """Deterministically trim a prompt before model invocation.

    The guard is deliberately mechanical: it uses approximate char/token accounting,
    preserves the current user turn and active constraints first, and only removes
    lower-priority context blocks or older dialogue turns.
    """
    guarded = [_trim_message_tool_observation(message, budget=budget) for message in prompt_messages]
    if _prompt_budget_count(guarded, budget=budget) <= budget.prompt_token_limit:
        return guarded

    main_system_index = _first_main_system_index(guarded)
    if main_system_index is not None:
        mandatory_indices = _mandatory_prompt_indices(guarded)
        other_units = _prompt_budget_count(
            [
                message
                for index, message in enumerate(guarded)
                if index != main_system_index
                and (index in mandatory_indices or isinstance(message, SystemMessage))
            ],
            budget=budget,
        )
        target_units = max(0, budget.prompt_token_limit - other_units)
        target_chars = _units_to_char_budget(target_units, budget=budget)
        trimmed_system = _trim_system_text_by_blocks(
            _text_for_budget(guarded[main_system_index]),
            max_chars=target_chars,
            target_units=target_units,
            budget=budget,
        )
        guarded[main_system_index] = _copy_message_with_content(
            guarded[main_system_index],
            trimmed_system,
        )

    if _prompt_budget_count(guarded, budget=budget) <= budget.prompt_token_limit:
        return guarded

    mandatory_indices = _mandatory_prompt_indices(guarded)
    removable = [
        index
        for index, message in enumerate(guarded)
        if index not in mandatory_indices and not isinstance(message, SystemMessage)
    ]
    for index in reversed(removable):
        if _prompt_budget_count(guarded, budget=budget) <= budget.prompt_token_limit:
            break
        del guarded[index]
        mandatory_indices = _mandatory_prompt_indices(guarded)

    if _prompt_budget_count(guarded, budget=budget) <= budget.prompt_token_limit:
        return guarded

    guarded = _shrink_tool_messages_to_fit(guarded, budget=budget)
    if _prompt_budget_count(guarded, budget=budget) <= budget.prompt_token_limit:
        return guarded

    return _hard_limit_prompt_messages(guarded, budget=budget)


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


def _prompt_char_limit(budget: ContextBudget) -> int:
    return max(1, int(budget.prompt_token_limit) * max(1, int(budget.chars_per_token)))


def _tool_observation_char_limit(budget: ContextBudget) -> int:
    return max(
        1,
        int(budget.tool_observation_token_limit) * max(1, int(budget.chars_per_token)),
    )


def _tool_reference_char_limit(budget: ContextBudget) -> int:
    return max(
        1,
        int(budget.tool_reference_token_limit) * max(1, int(budget.chars_per_token)),
    )


def _prompt_char_count(messages: list[AnyMessage]) -> int:
    return sum(len(_text_for_budget(message)) for message in messages)


def _prompt_budget_count(messages: list[AnyMessage], *, budget: ContextBudget) -> int:
    return sum(_message_budget_units(message, budget=budget) for message in messages)


def _message_budget_units(message: AnyMessage, *, budget: ContextBudget) -> int:
    return _estimate_text_tokens(
        _text_for_budget(message),
        chars_per_token=budget.chars_per_token,
        tokenizer_id=budget.tokenizer_id,
        tokenizer_first=budget.token_budget_mode == "tokenizer_first",
    )


def _units_to_char_budget(units: int, *, budget: ContextBudget) -> int:
    return max(0, int(units) * max(1, int(budget.chars_per_token)))


def _tool_observation_budget_mode(budget: ContextBudget) -> str:
    if budget.tool_observation_budget_mode == "inherit":
        return budget.token_budget_mode
    return budget.tool_observation_budget_mode


def _tool_observation_tokenizer_id(budget: ContextBudget) -> str | None:
    return budget.tool_observation_tokenizer_id or budget.tokenizer_id


def _tool_observation_budget_units(text: str, *, budget: ContextBudget) -> int:
    return _estimate_text_tokens(
        text,
        chars_per_token=budget.chars_per_token,
        tokenizer_id=_tool_observation_tokenizer_id(budget),
        tokenizer_first=_tool_observation_budget_mode(budget) == "tokenizer_first",
    )


def _tool_observation_within_budget(
    text: str,
    *,
    budget: ContextBudget,
    max_chars: int,
    enforce_token_budget: bool,
) -> bool:
    if len(text) > max_chars:
        return False
    if not enforce_token_budget:
        return True
    return _tool_observation_budget_units(text, budget=budget) <= budget.tool_observation_token_limit


def _fit_tool_observation_to_budget(text: str, *, budget: ContextBudget, max_chars: int) -> str:
    try:
        structured_payload = json.loads(text)
    except json.JSONDecodeError:
        structured_payload = None

    def _candidate_for_limit(limit: int) -> str:
        if structured_payload is not None:
            return _truncate_json_payload(structured_payload, max_chars=limit)
        return _truncate_text(text, max_chars=limit)

    candidate = _candidate_for_limit(max_chars)
    if _tool_observation_within_budget(
        candidate,
        budget=budget,
        max_chars=max_chars,
        enforce_token_budget=True,
    ):
        return candidate

    low = 1
    high = min(len(text), max_chars)
    best = candidate[:1]
    while low <= high:
        mid = (low + high) // 2
        probe = _candidate_for_limit(mid)
        if _tool_observation_within_budget(
            probe,
            budget=budget,
            max_chars=max_chars,
            enforce_token_budget=True,
        ):
            best = probe
            low = mid + 1
        else:
            high = mid - 1
    return best


def _estimate_text_tokens(
    text: str,
    *,
    chars_per_token: int,
    tokenizer_id: str | None,
    tokenizer_first: bool,
) -> int:
    if not text:
        return 0
    if tokenizer_first:
        estimated = _estimate_with_tokenizer(text, tokenizer_id=tokenizer_id)
        if estimated is not None:
            return estimated
    divisor = max(chars_per_token, 1)
    return max(1, (len(text) + divisor - 1) // divisor)


@lru_cache(maxsize=4)
def _resolve_tokenizer(tokenizer_id: str | None):
    try:
        tiktoken = importlib.import_module("tiktoken")
    except Exception:  # noqa: BLE001
        return None

    normalized = str(tokenizer_id or "").strip()
    try:
        if normalized:
            return tiktoken.encoding_for_model(normalized)
    except Exception:  # noqa: BLE001
        pass

    for fallback in ("cl100k_base", "o200k_base"):
        try:
            return tiktoken.get_encoding(fallback)
        except Exception:  # noqa: BLE001
            continue
    return None


def _estimate_with_tokenizer(text: str, *, tokenizer_id: str | None) -> int | None:
    tokenizer = _resolve_tokenizer(tokenizer_id)
    if tokenizer is None:
        return None
    try:
        return max(1, len(tokenizer.encode(text)))
    except Exception:  # noqa: BLE001
        return None


def _text_for_budget(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, default=str)
    content = getattr(value, "content", value)
    text = json.dumps(content, ensure_ascii=False, default=str) if isinstance(content, list) else str(content or "")
    tool_calls = getattr(value, "tool_calls", None)
    if tool_calls:
        text += "\n" + json.dumps(tool_calls, ensure_ascii=False, default=str)
    return text


def _copy_message_with_content(message: AnyMessage, content: str) -> AnyMessage:
    if hasattr(message, "model_copy"):
        return message.model_copy(update={"content": content})
    return type(message)(content=content)


def _trim_message_tool_observation(message: AnyMessage, *, budget: ContextBudget) -> AnyMessage:
    if not isinstance(message, ToolMessage):
        return message
    prompt_observation = _prompt_observation_for_tool_message(message)
    source_content = prompt_observation or str(message.content)
    trimmed = trim_tool_observation(
        source_content,
        tool_name=_tool_name_for_tool_message(message),
        tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
        budget=budget,
        artifactize_for_prompt=True,
        force_artifactize=_tool_message_was_runtime_compacted(
            message,
            max_chars=_tool_observation_char_limit(budget),
        ),
    )
    if trimmed == message.content:
        return message
    return _copy_message_with_content(message, trimmed)


def _first_main_system_index(messages: list[AnyMessage]) -> int | None:
    for index, message in enumerate(messages):
        if isinstance(message, SystemMessage):
            return index
    return None


def _mandatory_prompt_indices(messages: list[AnyMessage]) -> set[int]:
    indices = {index for index, message in enumerate(messages) if isinstance(message, SystemMessage)}
    latest_human = _latest_human_index(messages)
    if latest_human is not None:
        indices.add(latest_human)

    trailing_tool_start = _trailing_tool_span_start(messages)
    if trailing_tool_start is not None:
        indices.update(range(trailing_tool_start, len(messages)))
    return indices


def _latest_human_index(messages: list[AnyMessage]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return index
    return None


def _trailing_tool_span_start(messages: list[AnyMessage]) -> int | None:
    index = len(messages) - 1
    while index >= 0 and isinstance(messages[index], ToolMessage):
        index -= 1
    if index < 0:
        return None
    message = messages[index]
    if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
        return index
    return None


def _trim_system_text_by_blocks(
    text: str,
    *,
    max_chars: int,
    target_units: int | None = None,
    budget: ContextBudget | None = None,
) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    blocks = _split_context_blocks(text)
    prompt_mode = _prompt_mode_from_blocks(blocks)
    selected: set[int] = set()
    omitted = False
    used = 0
    unit_budget = max(0, int(target_units)) if target_units is not None and budget is not None else None
    used_units = 0

    for priority in range(0, 6):
        for index, block in enumerate(blocks):
            if index in selected or _context_block_priority(block, index=index, prompt_mode=prompt_mode) != priority:
                continue
            extra = len(block) + (2 if selected else 0)
            extra_units = (
                _message_budget_units(SystemMessage(content=block), budget=budget)
                if unit_budget is not None and budget is not None
                else 0
            )
            fits_unit_budget = unit_budget is None or used_units + extra_units <= unit_budget
            if used + extra <= max_chars and fits_unit_budget:
                selected.add(index)
                used += extra
                if unit_budget is not None:
                    used_units += extra_units
                continue
            remaining = max_chars - used - (2 if selected else 0)
            if priority <= 1 and remaining >= _minimum_truncation_budget(block):
                blocks[index] = _truncate_context_block(block, max_chars=remaining)
                selected.add(index)
                used = max_chars
                if unit_budget is not None:
                    used_units = unit_budget
            elif priority <= 3 and remaining >= _minimum_truncation_budget(block):
                blocks[index] = _truncate_context_block(block, max_chars=remaining)
                selected.add(index)
                used = max_chars
                if unit_budget is not None:
                    used_units = unit_budget
            else:
                omitted = True

    if not selected:
        return _truncate_block(text, max_chars=max_chars)

    rendered = "\n\n".join(blocks[index] for index in sorted(selected) if blocks[index])
    if omitted:
        note = "\n\n## Context trimming\n- Lower-priority context omitted to fit the prompt budget."
        if len(rendered) + len(note) <= max_chars:
            rendered += note
    if len(rendered) <= max_chars:
        return rendered
    return _truncate_block(rendered, max_chars=max_chars)


def _split_context_blocks(text: str) -> list[str]:
    return [block.strip() for block in text.split("\n\n") if block.strip()]


def _prompt_mode_from_blocks(blocks: list[str]) -> PromptMode:
    for block in blocks:
        lowered = block.lower()
        if not lowered.startswith("## prompt mode"):
            continue
        if "- execute" in lowered:
            return PromptMode.EXECUTE
        if "- synthesize" in lowered:
            return PromptMode.SYNTHESIZE
        if "- branch_review" in lowered:
            return PromptMode.BRANCH_REVIEW
    return PromptMode.EXPLORE


def _context_block_priority(block: str, *, index: int, prompt_mode: PromptMode) -> int:
    header = _context_block_header(block)
    if header == "empty":
        return 5
    if index == 0:
        return 2
    ordering = _block_priority_map(prompt_mode)
    return ordering.get(header, 5)


def _context_block_header(block: str) -> str:
    lowered = block.lower()
    if lowered.endswith("(none)"):
        return "empty"
    if lowered.startswith("## constraints and goals") or lowered.startswith("## 当前计划"):
        return "constraints"
    if lowered.startswith("## pinned facts"):
        return "pinned"
    if lowered.startswith("## imported findings already approved into this thread"):
        return "imported_findings"
    if lowered.startswith("## local branch findings pending upstream review"):
        return "branch_findings"
    if lowered.startswith("## findings"):
        return "findings"
    if lowered.startswith("## artifacts in scope"):
        return "artifacts"
    if lowered.startswith("## prompt mode"):
        return "prompt_mode"
    if lowered.startswith("## branch scope"):
        return "branch_scope"
    if lowered.startswith("## scene"):
        return "scene"
    if lowered.startswith("## skill system"):
        return "skill_system"
    if lowered.startswith("## active skills"):
        return "active_skills"
    if lowered.startswith("## rolling summary"):
        return "summary"
    if lowered.startswith("## retrieved long-term memories"):
        return "memory"
    if lowered.startswith("## available skills"):
        return "available_skills"
    return "other"


def _block_priority_map(prompt_mode: PromptMode) -> dict[str, int]:
    base = {
        "constraints": 1,
        "findings": 2,
        "pinned": 2,
        "imported_findings": 2,
        "branch_findings": 3,
        "artifacts": 3,
        "scene": 4,
        "prompt_mode": 4,
        "branch_scope": 4,
        "skill_system": 4,
        "active_skills": 4,
        "summary": 5,
        "memory": 5,
        "available_skills": 5,
        "other": 5,
    }
    if prompt_mode == PromptMode.SYNTHESIZE:
        return {
            **base,
            "imported_findings": 1,
            "findings": 1,
            "constraints": 1,
            "memory": 2,
            "pinned": 2,
            "summary": 4,
            "branch_findings": 5,
            "artifacts": 5,
        }
    if prompt_mode == PromptMode.BRANCH_REVIEW:
        return {
            **base,
            "branch_findings": 1,
            "artifacts": 1,
            "imported_findings": 2,
            "findings": 1,
            "constraints": 2,
            "memory": 4,
        }
    if prompt_mode == PromptMode.EXECUTE:
        return {
            **base,
            "constraints": 1,
            "pinned": 1,
            "findings": 2,
            "imported_findings": 2,
            "memory": 3,
            "branch_findings": 3,
            "artifacts": 3,
        }
    return {
        **base,
        "constraints": 1,
        "findings": 2,
        "branch_findings": 2,
        "imported_findings": 2,
        "memory": 3,
        "summary": 4,
    }


def _truncate_context_block(text: str, *, max_chars: int) -> str:
    structured = _truncate_bulleted_block(text, max_chars=max_chars)
    if structured:
        return structured
    return _truncate_block(text, max_chars=max_chars)


def _minimum_truncation_budget(text: str) -> int:
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    return max(36, min(96, len(first_line) + 8))


def _truncate_bulleted_block(text: str, *, max_chars: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    if len(lines) < 2 or not lines[0].startswith("## "):
        return ""

    header = lines[0].strip()
    bullets = [line.strip() for line in lines[1:] if line.strip()]
    if not bullets or not any(line.startswith("- ") for line in bullets):
        return ""

    kept_lines = [header]
    used = len(header)
    omitted_bullets: list[str] = []

    for bullet in bullets:
        extra = len(bullet) + 1
        if used + extra > max_chars:
            omitted_bullets.append(bullet)
            continue
        kept_lines.append(bullet)
        used += extra

    if len(kept_lines) == 1:
        remaining = max_chars - used - 1
        if remaining >= 18:
            kept_lines.append(omitted_bullets[0][:remaining].rstrip())
            return "\n".join(kept_lines)
        omitted_note = f"- ...[{len(bullets)} omitted]"
        if len(header) + 1 + len(omitted_note) <= max_chars:
            return "\n".join([header, omitted_note])
        if len(header) <= max_chars:
            return header
        return _truncate_block(header, max_chars=max_chars)

    rendered = "\n".join(kept_lines)
    if omitted_bullets:
        remaining = max_chars - len(rendered) - 1
        if remaining >= 18:
            partial = omitted_bullets[0][:remaining].rstrip()
            if partial:
                return rendered + "\n" + partial
        note = f"\n- ...[{len(omitted_bullets)} more omitted]"
        if len(rendered) + len(note) <= max_chars:
            rendered += note
    return rendered


def _truncate_block(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 24:
        return text[:max_chars]
    marker = "\n...[trimmed]...\n"
    keep = max_chars - len(marker)
    if keep <= 0:
        return text[:max_chars]
    head = max(1, keep // 2)
    tail = max(1, keep - head)
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def _truncate_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 32:
        return text[:max_chars]
    marker = "\n...[tool output trimmed]...\n"
    keep = max_chars - len(marker)
    head = max(1, keep // 2)
    tail = max(1, keep - head)
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def _shrink_tool_messages_to_fit(messages: list[AnyMessage], *, budget: ContextBudget) -> list[AnyMessage]:
    guarded = list(messages)
    for index in range(len(guarded) - 1, -1, -1):
        if _prompt_budget_count(guarded, budget=budget) <= budget.prompt_token_limit:
            break
        message = guarded[index]
        if not isinstance(message, ToolMessage):
            continue
        overflow_units = _prompt_budget_count(guarded, budget=budget) - budget.prompt_token_limit
        current = _text_for_budget(message)
        target = max(200, len(current) - _units_to_char_budget(overflow_units, budget=budget) - 16)
        guarded[index] = _copy_message_with_content(
            message,
            trim_tool_observation(
                current,
                tool_name=_tool_name_for_tool_message(message),
                tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
                max_chars=target,
                budget=budget,
                artifactize_for_prompt=True,
                force_artifactize=_tool_message_was_runtime_compacted(message, max_chars=target),
            ),
        )
    return guarded


def _hard_limit_prompt_messages(messages: list[AnyMessage], *, budget: ContextBudget) -> list[AnyMessage]:
    guarded = list(messages)
    latest_human = _latest_human_index(guarded)
    ordered_indices = [
        *[
            index
            for index in range(len(guarded) - 1, -1, -1)
            if isinstance(guarded[index], ToolMessage)
        ],
        *[
            index
            for index in range(len(guarded) - 1, -1, -1)
            if isinstance(guarded[index], SystemMessage)
        ],
        *[
            index
            for index in range(len(guarded) - 1, -1, -1)
            if index != latest_human
            and not isinstance(guarded[index], (SystemMessage, ToolMessage))
        ],
    ]
    if latest_human is not None:
        ordered_indices.append(latest_human)

    seen: set[int] = set()
    for index in ordered_indices:
        if index in seen or index >= len(guarded):
            continue
        seen.add(index)
        if _prompt_budget_count(guarded, budget=budget) <= budget.prompt_token_limit:
            break
        message = guarded[index]
        current = _text_for_budget(message)
        overflow_units = _prompt_budget_count(guarded, budget=budget) - budget.prompt_token_limit
        target = max(0, len(current) - _units_to_char_budget(overflow_units, budget=budget) - 16)
        if isinstance(message, ToolMessage):
            content = trim_tool_observation(
                current,
                tool_name=_tool_name_for_tool_message(message),
                tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
                max_chars=target,
                budget=budget,
                artifactize_for_prompt=True,
                force_artifactize=_tool_message_was_runtime_compacted(message, max_chars=target),
            )
        elif isinstance(message, SystemMessage):
            content = _truncate_context_block(current, max_chars=target)
        else:
            content = _truncate_block(current, max_chars=target)
        guarded[index] = _copy_message_with_content(message, content)

    return guarded


def _compact_structured_observation(
    payload: Any,
    *,
    tool_name: str,
    tool_call_id: str,
    max_chars: int,
    reference_chars: int,
    artifactize_for_prompt: bool,
) -> Any:
    if isinstance(payload, list):
        compact = {
            "tool": tool_name or "tool",
            "summary": f"Structured tool output trimmed to {len(payload[:3]) if payload else 0} representative items.",
            "items": _compact_result_list(
                payload,
                max_chars=max_chars,
                artifactize_for_prompt=artifactize_for_prompt,
            ),
            "reference": f"Prompt view keeps representative items only; original observation had {len(payload)} list entries.",
            "truncated_by_context_policy": True,
        }
        if artifactize_for_prompt:
            compact["artifact_ref"] = _tool_observation_ref(tool_name=tool_name, tool_call_id=tool_call_id)
            refs = _collect_artifact_like_refs(payload)
            if refs:
                compact["refs"] = refs[:6]
            compact["summary"] = f"Prompt-only artifactized view of {len(payload)} list item(s)."
            compact["reference"] = _truncate_text(
                "Representative refs: " + "; ".join(refs[:6]) if refs else compact["reference"],
                max_chars=reference_chars,
            )
            compact["original_chars"] = len(json.dumps(payload, ensure_ascii=False, default=str))
        return compact
    if not isinstance(payload, dict):
        if not artifactize_for_prompt:
            return _truncate_text(str(payload), max_chars=max_chars)
        return _format_textual_tool_reference(
            str(payload),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            max_chars=max_chars,
            reference_chars=reference_chars,
        )

    compact: dict[str, Any] = {}
    for key in (
        "query",
        "path",
        "glob",
        "literal",
        "case_sensitive",
        "start_line",
        "end_line",
        "total_lines",
        "url",
        "final_url",
        "title",
        "content_type",
        "truncated",
    ):
        if key in payload:
            compact[key] = payload[key]

    if "results" in payload and isinstance(payload["results"], list):
        compact["results"] = _compact_result_list(
            payload["results"],
            max_chars=max_chars,
            artifactize_for_prompt=artifactize_for_prompt,
        )
    elif "hits" in payload and isinstance(payload["hits"], list):
        compact["hits"] = _compact_result_list(
            payload["hits"],
            max_chars=max_chars,
            artifactize_for_prompt=artifactize_for_prompt,
        )

    if "content" in payload:
        compact["content"] = _trim_numbered_content(str(payload.get("content") or ""), max_chars=max_chars // 2)
    if "diff" in payload:
        compact["diff"] = _trim_diff(str(payload.get("diff") or ""), max_chars=max_chars // 2)

    if tool_name and "tool" not in compact:
        compact["tool"] = tool_name
    compact["summary"] = _structured_tool_summary(
        payload,
        tool_name=tool_name,
        artifactize_for_prompt=artifactize_for_prompt,
    )
    compact["reference"] = _structured_tool_reference(
        payload,
        tool_name=tool_name,
        max_chars=reference_chars,
        artifactize_for_prompt=artifactize_for_prompt,
    )
    if artifactize_for_prompt:
        compact["artifact_ref"] = _tool_observation_ref(tool_name=tool_name, tool_call_id=tool_call_id)
        refs = _collect_artifact_like_refs(payload)
        if refs:
            compact["refs"] = refs[:6]
    compact["truncated_by_context_policy"] = True
    compact["original_chars"] = len(json.dumps(payload, ensure_ascii=False, default=str))
    return compact


def _compact_result_list(
    results: list[Any],
    *,
    max_chars: int,
    artifactize_for_prompt: bool,
) -> list[Any]:
    compact_results: list[Any] = []
    for result in results:
        if isinstance(result, dict):
            compact = {}
            ref = _artifact_like_ref_from_mapping(result) if artifactize_for_prompt else None
            if artifactize_for_prompt and ref:
                compact["ref"] = ref
                compact_results.append(compact)
                rendered = json.dumps(compact_results, ensure_ascii=False, separators=(",", ":"), default=str)
                if len(rendered) >= max_chars // 2:
                    break
                continue
            for key in (
                "path",
                "line_number",
                "start_line",
                "end_line",
                "title",
                "url",
                "final_url",
            ):
                if key in result:
                    compact[key] = result[key]
            for key in ("line", "snippet", "content", "text"):
                if key in result:
                    compact[key] = _collapse_inline(str(result[key]))[:240]
                    break
            if artifactize_for_prompt:
                if ref:
                    compact["ref"] = ref
            compact_results.append(compact or _collapse_inline(str(result))[:240])
        else:
            compact_results.append(_collapse_inline(str(result))[:240])
        if len(json.dumps(compact_results, ensure_ascii=False, default=str)) >= max_chars // 2:
            break
    return compact_results


def _trim_numbered_content(content: str, *, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    lines = content.splitlines()
    kept: list[str] = []
    used = 0
    for line in lines:
        candidate = line[:400]
        extra = len(candidate) + (1 if kept else 0)
        if kept and used + extra > max_chars:
            break
        kept.append(candidate)
        used += extra
        if used >= max_chars:
            break
    return "\n".join(kept) + "\n...[tool output trimmed]..."


def _trim_diff(diff: str, *, max_chars: int) -> str:
    important = [
        line
        for line in diff.splitlines()
        if line.startswith(("diff --git", "+++", "---", "@@", "+", "-"))
    ]
    text = "\n".join(important or diff.splitlines())
    return _truncate_text(text, max_chars=max_chars)


def _structured_tool_summary(
    payload: dict[str, Any],
    *,
    tool_name: str,
    artifactize_for_prompt: bool,
) -> str:
    if tool_name == "search_code":
        count = len(payload.get("results") or [])
        query = str(payload.get("query") or "").strip()
        if artifactize_for_prompt:
            return f"artifactized search_code view: {count} hit(s) for {query or 'query'}."
        return f"search_code: {count} hit(s) for {query or 'query'}."
    if tool_name == "read_file":
        path = str(payload.get("path") or "the requested file").strip()
        start_line = payload.get("start_line")
        end_line = payload.get("end_line")
        if start_line is not None and end_line is not None:
            verb = "artifactized" if artifactize_for_prompt else "returned"
            return f"read_file {verb} {path} lines {start_line}-{end_line}."
        verb = "artifactized" if artifactize_for_prompt else "returned content from"
        return f"read_file {verb} {path}."
    if tool_name:
        if artifactize_for_prompt:
            return f"{tool_name} output was compressed into an artifact-like prompt reference."
        return f"{tool_name} output was compressed for prompt budgeting."
    if artifactize_for_prompt:
        return "Structured tool output was compressed into an artifact-like prompt reference."
    return "Structured tool output was compressed for prompt budgeting."


def _structured_tool_reference(
    payload: dict[str, Any],
    *,
    tool_name: str,
    max_chars: int,
    artifactize_for_prompt: bool,
) -> str:
    details: list[str] = []
    if tool_name == "search_code":
        query = str(payload.get("query") or "").strip()
        if query:
            details.append(f"query={query}")
        results = payload.get("results")
        if isinstance(results, list):
            details.append(f"hits={len(results)}")
    elif tool_name == "read_file":
        path = str(payload.get("path") or "").strip()
        if path:
            details.append(f"path={path}")
        start_line = payload.get("start_line")
        end_line = payload.get("end_line")
        if start_line is not None and end_line is not None:
            details.append(f"lines={start_line}-{end_line}")
        total_lines = payload.get("total_lines")
        if total_lines is not None:
            details.append(f"total_lines={total_lines}")
        sample_line = _first_nonempty_line(str(payload.get("content") or ""))
        if sample_line:
            details.append(f"sample={_collapse_inline(sample_line)[:120]}")
    else:
        for key in ("path", "url", "title", "query"):
            value = str(payload.get(key) or "").strip()
            if value:
                details.append(f"{key}={value}")
    if artifactize_for_prompt:
        refs = _collect_artifact_like_refs(payload)
        if refs:
            details[:0] = [f"refs={', '.join(refs[:4])}"]
    if not details:
        details.append("original observation omitted from prompt body")
    return _truncate_text("; ".join(details), max_chars=max_chars)


def _format_textual_tool_reference(
    text: str,
    *,
    tool_name: str,
    tool_call_id: str,
    max_chars: int,
    reference_chars: int,
) -> str:
    collapsed = " ".join(text.split())
    summary = f"{tool_name or 'tool'} trimmed."
    reference_budget = max(18, min(max_chars // 3, reference_chars, 36))
    reference = _truncate_text(collapsed, max_chars=reference_budget)
    rendered = {
        "summary": summary,
        "reference": reference,
        "truncated_by_context_policy": True,
        "original_chars": len(text),
    }
    if tool_call_id or tool_name in {"search_code", "read_file"}:
        rendered["tool"] = tool_name
    if tool_call_id:
        rendered["artifact_ref"] = _tool_observation_ref(tool_name=tool_name, tool_call_id=tool_call_id)
    return json.dumps(rendered, ensure_ascii=False, separators=(",", ":"))


def _truncate_json_payload(payload: Any, *, max_chars: int) -> str:
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(rendered) <= max_chars:
        return rendered
    if isinstance(payload, dict):
        compact = {
            key: value
            for key, value in payload.items()
            if key
            in {
                "query",
                "path",
                "start_line",
                "end_line",
                "total_lines",
                "results",
                "hits",
                "tool",
                "artifact_ref",
                "summary",
                "reference",
                "refs",
                "truncated_by_context_policy",
                "original_chars",
            }
        }
        compact = _shrink_json_payload(compact, max_chars=max_chars)
        rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(rendered) <= max_chars:
        return rendered
    base_summary = payload.get("summary") if isinstance(payload, dict) else "Tool output trimmed."
    fallback_variants = [
        {
            "tool": payload.get("tool") if isinstance(payload, dict) else "tool",
            "artifact_ref": payload.get("artifact_ref") if isinstance(payload, dict) else None,
            "refs": (
                payload.get("refs")[:1]
                if isinstance(payload, dict) and isinstance(payload.get("refs"), list)
                else []
            ),
            "summary": _collapse_inline(str(base_summary or "Tool output trimmed."))[:48],
            "truncated_by_context_policy": True,
            "original_chars": payload.get("original_chars") if isinstance(payload, dict) else None,
        },
        {
            "tool": payload.get("tool") if isinstance(payload, dict) else "tool",
            "artifact_ref": payload.get("artifact_ref") if isinstance(payload, dict) else None,
            "refs": (
                payload.get("refs")[:1]
                if isinstance(payload, dict) and isinstance(payload.get("refs"), list)
                else []
            ),
            "summary": _collapse_inline(str(base_summary or "Tool output trimmed."))[:24],
            "truncated_by_context_policy": True,
        },
        {
            "artifact_ref": payload.get("artifact_ref") if isinstance(payload, dict) else None,
            "refs": (
                payload.get("refs")[:1]
                if isinstance(payload, dict) and isinstance(payload.get("refs"), list)
                else []
            ),
            "truncated_by_context_policy": True,
        },
        {"truncated_by_context_policy": True},
    ]
    for fallback in fallback_variants:
        fallback = {key: value for key, value in fallback.items() if value not in (None, [], "")}
        rendered = json.dumps(fallback, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(rendered) <= max_chars:
            return rendered
    return "{}" if max_chars >= 2 else ""


def _collapse_inline(text: str) -> str:
    return " ".join(text.split())


def _shrink_json_payload(payload: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    compact = dict(payload)
    inline_limit = max(24, min(120, max_chars // 3))
    for key in ("summary", "reference", "excerpt", "content", "diff"):
        value = compact.get(key)
        if isinstance(value, str):
            compact[key] = _collapse_inline(value)[:inline_limit]
    for key in ("refs",):
        value = compact.get(key)
        if isinstance(value, list):
            compact[key] = [str(item)[: max(32, min(96, max_chars // 2))] for item in value[:4]]
    for key in ("results", "hits", "items"):
        value = compact.get(key)
        if isinstance(value, list):
            compact[key] = _shrink_json_result_list(value, max_chars=max_chars // 2)
    rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(rendered) <= max_chars:
        return compact

    optional_keys = [
        "content",
        "diff",
        "excerpt",
        "query",
        "path",
        "start_line",
        "end_line",
        "total_lines",
        "tool",
        "original_chars",
        "hits",
        "items",
        "reference",
        "summary",
        "results",
    ]
    for key in optional_keys:
        if key not in compact:
            continue
        trimmed = dict(compact)
        trimmed.pop(key, None)
        rendered = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(rendered) <= max_chars:
            return trimmed
        compact = trimmed
    return compact


def _shrink_json_result_list(results: list[Any], *, max_chars: int) -> list[Any]:
    compact_results: list[Any] = []
    for result in results[:4]:
        if isinstance(result, dict):
            compact_item: dict[str, Any] = {}
            for key, value in result.items():
                if isinstance(value, str):
                    compact_item[key] = _collapse_inline(value)[:120]
                else:
                    compact_item[key] = value
            compact_results.append(compact_item)
        else:
            compact_results.append(_collapse_inline(str(result))[:120])
        rendered = json.dumps(compact_results, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(rendered) > max_chars:
            if len(compact_results) == 1 and isinstance(result, dict):
                slim_item: dict[str, Any] = {}
                for key, value in compact_item.items():
                    if isinstance(value, str):
                        slim_item[key] = value[: max(24, min(72, max_chars // 2))]
                    else:
                        slim_item[key] = value
                compact_results[0] = slim_item
                rendered = json.dumps(compact_results, ensure_ascii=False, separators=(",", ":"), default=str)
                if len(rendered) <= max_chars:
                    continue
            compact_results.pop()
            break
    return compact_results


def _tool_name_for_tool_message(message: ToolMessage) -> str:
    artifact = getattr(message, "artifact", None)
    if not isinstance(artifact, dict):
        return ""
    tool_name = artifact.get("tool_name")
    if isinstance(tool_name, str):
        return tool_name
    tool_payload = artifact.get("tool")
    if isinstance(tool_payload, dict) and isinstance(tool_payload.get("name"), str):
        return str(tool_payload["name"])
    return ""


def _tool_message_was_runtime_compacted(message: ToolMessage, *, max_chars: int) -> bool:
    artifact = getattr(message, "artifact", None)
    if not isinstance(artifact, dict):
        return False
    runtime = artifact.get("runtime")
    if not isinstance(runtime, dict):
        return False
    if bool(runtime.get("observation_prompt_compacted")):
        return True
    original_chars = runtime.get("observation_original_chars")
    if isinstance(original_chars, int):
        return original_chars > max_chars
    return False


def _prompt_observation_for_tool_message(message: ToolMessage) -> str:
    artifact = getattr(message, "artifact", None)
    if not isinstance(artifact, dict):
        return ""
    value = artifact.get("prompt_observation")
    return str(value) if isinstance(value, str) else ""


def _tool_observation_ref(*, tool_name: str, tool_call_id: str) -> str:
    normalized_tool = (tool_name or "tool").strip() or "tool"
    normalized_call = (tool_call_id or "latest").strip() or "latest"
    return f"tool-observation://{normalized_tool}/{normalized_call}"


def _collect_artifact_like_refs(payload: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(payload, dict):
        top_level_ref = _artifact_like_ref_from_mapping(payload)
        if top_level_ref:
            refs.append(top_level_ref)
        for key in ("results", "hits", "items"):
            values = payload.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                ref = _artifact_like_ref_from_mapping(value)
                if ref:
                    refs.append(ref)
    elif isinstance(payload, list):
        for value in payload:
            ref = _artifact_like_ref_from_mapping(value)
            if ref:
                refs.append(ref)
    return list(dict.fromkeys(refs))


def _artifact_like_ref_from_mapping(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    path = value.get("path")
    line_number = value.get("line_number")
    start_line = value.get("start_line")
    end_line = value.get("end_line")
    url = value.get("final_url") or value.get("url")
    if path:
        if line_number is not None:
            return f"{path}:{line_number}"
        if start_line is not None and end_line is not None:
            return f"{path}:{start_line}-{end_line}"
        if start_line is not None:
            return f"{path}:{start_line}"
        return str(path)
    if url:
        return str(url)
    return None


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
    if limit <= 0:
        return []
    return findings


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
    if limit <= 0:
        return []
    return [line for line in lines if line]


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


def _render_block_order(prompt_mode: PromptMode) -> list[str]:
    if prompt_mode == PromptMode.SYNTHESIZE:
        return [
            "system_instructions",
            "active_skills_block",
            "memory_block",
            "pinned_block",
            "constraints_block",
            "findings_block",
            "summary_block",
            "available_skills_block",
            "artifact_block",
        ]
    return [
        "system_instructions",
        "active_skills_block",
        "available_skills_block",
        "memory_block",
        "summary_block",
        "pinned_block",
        "constraints_block",
        "findings_block",
        "artifact_block",
    ]


def _current_plan_step_goal(state: dict[str, Any]) -> str:
    plan = state.get("plan")
    current_step_id = str(state.get("current_step_id") or "").strip()
    if not current_step_id or plan is None:
        return ""
    for step in getattr(plan, "steps", []) or []:
        if str(getattr(step, "id", "")) == current_step_id:
            return str(getattr(step, "goal", "") or "").strip()
    if isinstance(plan, dict):
        for step in list(plan.get("steps", []) or []):
            if str(step.get("id") or "") == current_step_id:
                return str(step.get("goal") or "").strip()
    return ""


def _dedupe_text_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    if limit <= 0:
        return []

    deduped: dict[str, _PromptTextCandidate] = {}
    for index, value in enumerate(lines):
        line = str(value or "").strip()
        if not line:
            continue
        candidate = _text_candidate(line, recency_order=index)
        current = deduped.get(candidate.dedupe_key)
        if current is None or _text_candidate_preference(candidate) > _text_candidate_preference(current):
            deduped[candidate.dedupe_key] = candidate

    selected = sorted(deduped.values(), key=_text_candidate_preference, reverse=True)
    return [item.line for item in selected[:limit]]


def _dedupe_preferring_reference(reference_lines: Iterable[str], candidate_lines: Iterable[str], *, limit: int) -> list[str]:
    if limit <= 0:
        return []

    reference_keys = {
        _text_candidate(str(line or "").strip(), recency_order=index).dedupe_key
        for index, line in enumerate(reference_lines)
        if str(line or "").strip()
    }
    filtered = [
        str(line or "").strip()
        for line in candidate_lines
        if str(line or "").strip()
        and _text_candidate(str(line or "").strip(), recency_order=0).dedupe_key not in reference_keys
    ]
    return _dedupe_text_lines(filtered, limit=limit)


def _text_candidate(line: str, *, recency_order: int) -> _PromptTextCandidate:
    stripped = line.strip()
    source_stripped = _LINE_SOURCE_PREFIX_RE.sub("", stripped)
    artifact_key = _artifact_dedupe_key(source_stripped)
    dedupe_key = artifact_key or _normalize_for_dedupe(_strip_line_metadata(source_stripped)) or _normalize_for_dedupe(stripped)
    return _PromptTextCandidate(
        line=stripped,
        dedupe_key=dedupe_key or f"line:{recency_order}",
        promoted=_looks_promoted_line(stripped),
        confidence=_extract_line_confidence(stripped),
        evidence_count=_extract_line_evidence_count(stripped),
        score=_extract_line_score(stripped),
        has_uri=bool(_ARTIFACT_URI_RE.search(stripped)),
        recency_order=recency_order,
    )


def _text_candidate_preference(candidate: _PromptTextCandidate) -> tuple[float, ...]:
    return (
        1.0 if candidate.promoted else 0.0,
        candidate.confidence,
        float(candidate.evidence_count),
        candidate.score,
        1.0 if candidate.has_uri else 0.0,
        float(candidate.recency_order),
    )


def _strip_line_metadata(text: str) -> str:
    stripped = _LINE_SCORE_RE.sub("", text).strip()
    stripped = _LINE_EVIDENCE_RE.sub("", stripped).strip()
    stripped = _LINE_CONFIDENCE_RE.sub("", stripped).strip()
    return stripped


def _normalize_for_dedupe(text: str) -> str:
    lowered = str(text or "").casefold().strip()
    lowered = re.sub(r"[^0-9a-z\u4e00-\u9fff/._:-]+", " ", lowered)
    return " ".join(lowered.split())


def _looks_promoted_line(text: str) -> bool:
    lowered = text.casefold()
    return (
        "root_thread" in lowered
        or "imported_conclusion" in lowered
        or "approved finding" in lowered
        or "already approved" in lowered
    )


def _extract_line_confidence(text: str) -> float:
    match = _LINE_CONFIDENCE_RE.search(text)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _extract_line_evidence_count(text: str) -> int:
    match = _LINE_EVIDENCE_RE.search(text)
    if not match:
        return 0
    values = [item.strip() for item in match.group(1).split(",") if item.strip()]
    return len(values)


def _extract_line_score(text: str) -> float:
    match = _LINE_SCORE_RE.search(text)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _artifact_dedupe_key(text: str) -> str:
    match = _ARTIFACT_LINE_RE.match(text.strip())
    if match:
        kind = str(match.group("kind") or "").strip().casefold()
        if not kind.startswith(("evidence:", "score ")) and kind != "score":
            title = str(match.group("title") or "").strip()
            return _normalize_for_dedupe(f"{title} {kind}")
    return ""


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


def _render_block_order(prompt_mode: PromptMode) -> tuple[str, ...]:
    shared_tail = ("available_skills_block",)
    if prompt_mode == PromptMode.EXECUTE:
        return (
            "system_instructions",
            "active_skills_block",
            "constraints_block",
            "findings_block",
            "artifact_block",
            "pinned_block",
            "memory_block",
            "summary_block",
            *shared_tail,
        )
    if prompt_mode == PromptMode.SYNTHESIZE:
        return (
            "system_instructions",
            "constraints_block",
            "findings_block",
            "pinned_block",
            "memory_block",
            "summary_block",
            "active_skills_block",
            "artifact_block",
            *shared_tail,
        )
    if prompt_mode == PromptMode.BRANCH_REVIEW:
        return (
            "system_instructions",
            "findings_block",
            "artifact_block",
            "constraints_block",
            "pinned_block",
            "memory_block",
            "summary_block",
            "active_skills_block",
            *shared_tail,
        )
    return (
        "system_instructions",
        "active_skills_block",
        "memory_block",
        "constraints_block",
        "pinned_block",
        "findings_block",
        "summary_block",
        "artifact_block",
        *shared_tail,
    )


def _dedupe_text_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    if limit <= 0:
        return []

    kept: list[str] = []
    seen: set[str] = set()
    for raw in reversed([str(line).strip() for line in lines if str(line).strip()]):
        key = _text_line_dedupe_key(raw)
        if key in seen:
            continue
        seen.add(key)
        kept.append(raw)
        if len(kept) >= limit:
            break
    kept.reverse()
    return kept


def _dedupe_finding_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(lines, limit=limit, key_fn=_finding_line_dedupe_key, rank_fn=_finding_line_rank)


def _dedupe_memory_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(lines, limit=limit, key_fn=_memory_line_dedupe_key, rank_fn=_memory_line_rank)


def _dedupe_artifact_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(lines, limit=limit, key_fn=_artifact_line_dedupe_key, rank_fn=_artifact_line_rank)


def _dedupe_preferring_reference(
    reference_lines: Iterable[str],
    candidate_lines: Iterable[str],
    *,
    limit: int,
) -> list[str]:
    if limit <= 0:
        return []
    reference_keys = {_finding_line_dedupe_key(line) for line in reference_lines if str(line).strip()}
    filtered = [
        str(line).strip()
        for line in candidate_lines
        if str(line).strip() and _finding_line_dedupe_key(str(line)) not in reference_keys
    ]
    return _dedupe_finding_lines(filtered, limit=limit)


def _current_plan_step_goal(state: dict[str, Any]) -> str:
    plan = state.get("plan")
    if plan is None:
        return ""
    steps = getattr(plan, "steps", None)
    if steps is None and isinstance(plan, dict):
        steps = plan.get("steps")
    if not isinstance(steps, list):
        return ""
    for step in steps:
        done = getattr(step, "done", None)
        goal = getattr(step, "goal", None)
        if isinstance(step, dict):
            done = step.get("done", done)
            goal = step.get("goal", goal)
        if not done and goal:
            return str(goal).strip()
    return ""


def _context_block_header(block: str) -> str:
    lowered = block.lower()
    if lowered.endswith("(none)"):
        return "empty"
    if lowered.startswith("## constraints and goals") or lowered.startswith("## 当前计划"):
        return "constraints"
    if lowered.startswith("## pinned facts"):
        return "pinned"
    if lowered.startswith("## findings"):
        return "findings"
    if lowered.startswith("## imported findings already approved into this thread"):
        return "imported_findings"
    if lowered.startswith("## local branch findings pending upstream review"):
        return "branch_findings"
    if lowered.startswith("## artifacts in scope"):
        return "artifacts"
    if lowered.startswith("## prompt mode"):
        return "prompt_mode"
    if lowered.startswith("## branch scope"):
        return "branch_scope"
    if lowered.startswith("## scene"):
        return "scene"
    if lowered.startswith("## skill system"):
        return "skill_system"
    if lowered.startswith("## active skills"):
        return "active_skills"
    if lowered.startswith("## rolling summary"):
        return "summary"
    if lowered.startswith("## retrieved long-term memories"):
        return "memory"
    if lowered.startswith("## available skills"):
        return "available_skills"
    return "preamble"


def _context_block_priority(block: str, *, index: int, prompt_mode: PromptMode) -> int:
    header = _context_block_header(block)
    if header == "empty":
        return 5
    ordering = _block_priority_map(prompt_mode)
    return ordering.get(header, 5)


def _block_priority_map(prompt_mode: PromptMode) -> dict[str, int]:
    base = {
        "constraints": 0,
        "imported_findings": 1,
        "findings": 1,
        "pinned": 2,
        "branch_findings": 2,
        "artifacts": 3,
        "preamble": 3,
        "scene": 4,
        "prompt_mode": 4,
        "branch_scope": 4,
        "skill_system": 4,
        "active_skills": 4,
        "memory": 5,
        "summary": 5,
        "available_skills": 5,
    }
    if prompt_mode == PromptMode.SYNTHESIZE:
        return {**base, "constraints": 0, "imported_findings": 0, "findings": 0, "pinned": 1, "memory": 2, "summary": 4}
    if prompt_mode == PromptMode.BRANCH_REVIEW:
        return {**base, "branch_findings": 0, "findings": 0, "artifacts": 1, "constraints": 2}
    if prompt_mode == PromptMode.EXECUTE:
        return {**base, "constraints": 0, "pinned": 1, "imported_findings": 1, "findings": 1, "artifacts": 2}
    return {**base, "constraints": 0, "findings": 1, "branch_findings": 1, "imported_findings": 1}


def _prompt_budget_count(messages: list[AnyMessage], *, budget: ContextBudget) -> int:
    total = 0
    for message in messages:
        if isinstance(message, SystemMessage):
            total += _system_message_budget_units(str(message.content), budget=budget)
        else:
            total += _message_budget_units(message, budget=budget)
    return total


def _system_message_budget_units(text: str, *, budget: ContextBudget) -> int:
    blocks = _split_context_blocks(text)
    if not blocks:
        return _message_budget_units(SystemMessage(content=text), budget=budget)
    return sum(_message_budget_units(SystemMessage(content=block), budget=budget) for block in blocks)


def _trim_message_tool_observation(message: AnyMessage, *, budget: ContextBudget) -> AnyMessage:
    if not isinstance(message, ToolMessage):
        return message
    prompt_observation = _prompt_observation_for_tool_message(message)
    if prompt_observation:
        if _tool_observation_within_budget(
            prompt_observation,
            budget=budget,
            max_chars=_tool_observation_char_limit(budget),
            enforce_token_budget=True,
        ):
            trimmed = prompt_observation
        else:
            trimmed = trim_tool_observation(
                prompt_observation,
                tool_name=_tool_name_for_tool_message(message),
                tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
                budget=budget,
                artifactize_for_prompt=True,
            )
    else:
        trimmed = trim_tool_observation(
            str(message.content),
            tool_name=_tool_name_for_tool_message(message),
            tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
            budget=budget,
            artifactize_for_prompt=True,
            force_artifactize=_tool_message_was_runtime_compacted(
                message,
                max_chars=_tool_observation_char_limit(budget),
            ),
        )
    if trimmed == message.content and not prompt_observation:
        return message
    return _copy_message_with_content(message, trimmed)


def _truncate_bulleted_block(text: str, *, max_chars: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    if len(lines) < 2 or not lines[0].startswith("## "):
        return ""

    header = lines[0].strip()
    bullets = [line.strip() for line in lines[1:] if line.strip()]
    if not bullets or not any(line.startswith("- ") for line in bullets):
        return ""

    prioritized_bullets = list(bullets)
    if header.casefold().startswith("## constraints and goals") and len(bullets) > 1:
        prioritized_bullets = [bullets[0], bullets[-1], *bullets[1:-1]]

    kept_lines = [header]
    used = len(header)
    omitted_count = 0
    for bullet in prioritized_bullets:
        extra = len(bullet) + 1
        if used + extra > max_chars:
            omitted_count += 1
            continue
        kept_lines.append(bullet)
        used += extra

    if len(kept_lines) == 1:
        omitted_note = f"- ...[{len(bullets)} omitted]"
        if len(header) + 1 + len(omitted_note) <= max_chars:
            return "\n".join([header, omitted_note])
        return header if len(header) <= max_chars else _truncate_block(header, max_chars=max_chars)

    rendered = "\n".join(kept_lines)
    if omitted_count:
        note = f"\n- ...[{omitted_count} more omitted]"
        if len(rendered) + len(note) <= max_chars:
            rendered += note
    return rendered


def _artifact_line_dedupe_key(line: str) -> str:
    text = str(line).strip()
    match = _ARTIFACT_LINE_RE.match(text)
    if match:
        title = str(match.group("title") or "").strip()
        kind = str(match.group("kind") or "").strip()
        return _text_line_dedupe_key(f"{title} [{kind}]")
    normalized = _ARTIFACT_URI_RE.sub("", text)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold()


def _text_line_dedupe_key(line: str) -> str:
    return " ".join(str(line).split()).casefold()


def _dedupe_ranked_lines(
    lines: Iterable[str],
    *,
    limit: int,
    key_fn,
    rank_fn,
) -> list[str]:
    if limit <= 0:
        return []

    selected: dict[str, tuple[tuple[Any, ...], str]] = {}
    for recency_order, raw in enumerate(str(line).strip() for line in lines if str(line).strip()):
        key = key_fn(raw)
        rank = (*rank_fn(raw), recency_order)
        current = selected.get(key)
        if current is None or rank > current[0]:
            selected[key] = (rank, raw)

    ordered = sorted(selected.values(), key=lambda item: item[0], reverse=True)
    return [line for _, line in ordered[:limit]][::-1]


def _finding_line_dedupe_key(line: str) -> str:
    normalized = _LINE_SOURCE_PREFIX_RE.sub("", str(line).strip())
    normalized = _LINE_EVIDENCE_RE.sub("", normalized)
    normalized = _LINE_CONFIDENCE_RE.sub("", normalized)
    normalized = _LINE_SCORE_RE.sub("", normalized)
    return _text_line_dedupe_key(normalized)


def _memory_line_dedupe_key(line: str) -> str:
    normalized = _LINE_SOURCE_PREFIX_RE.sub("", str(line).strip())
    normalized = _LINE_SCORE_RE.sub("", normalized)
    return _text_line_dedupe_key(normalized)


def _artifact_line_dedupe_key(line: str) -> str:
    normalized = _ARTIFACT_URI_RE.sub("", str(line).strip()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold()


def _finding_line_rank(line: str) -> tuple[int, float, int, int]:
    text = str(line)
    promoted = 1 if "main-doc" in text or "imported" in text or text.startswith("[root_thread") else 0
    confidence = _extract_numeric(_LINE_CONFIDENCE_RE, text)
    evidence_count = len(_LINE_EVIDENCE_RE.findall(text))
    return promoted, confidence, evidence_count, len(text)


def _memory_line_rank(line: str) -> tuple[int, float, int]:
    text = str(line)
    promoted = 1 if "root_thread/imported_conclusion" in text else 0
    score = _extract_numeric(_LINE_SCORE_RE, text)
    return promoted, score, len(text)


def _artifact_line_rank(line: str) -> tuple[int, int, int]:
    text = str(line)
    has_uri = 1 if _ARTIFACT_URI_RE.search(text) else 0
    return has_uri, len(text), 0


def _extract_numeric(pattern: re.Pattern[str], text: str) -> float:
    match = pattern.search(text)
    if match is None:
        return 0.0
    try:
        return float(match.group(1))
    except (IndexError, ValueError):
        return 0.0


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _render_block_order(prompt_mode: PromptMode) -> tuple[str, ...]:
    if prompt_mode == PromptMode.SYNTHESIZE:
        return (
            "system_instructions",
            "constraints_block",
            "findings_block",
            "memory_block",
            "pinned_block",
            "summary_block",
            "active_skills_block",
            "available_skills_block",
            "artifact_block",
        )
    if prompt_mode == PromptMode.BRANCH_REVIEW:
        return (
            "system_instructions",
            "findings_block",
            "artifact_block",
            "constraints_block",
            "pinned_block",
            "memory_block",
            "summary_block",
            "active_skills_block",
            "available_skills_block",
        )
    if prompt_mode == PromptMode.EXECUTE:
        return (
            "system_instructions",
            "constraints_block",
            "pinned_block",
            "findings_block",
            "artifact_block",
            "memory_block",
            "summary_block",
            "active_skills_block",
            "available_skills_block",
        )
    return (
        "system_instructions",
        "constraints_block",
        "findings_block",
        "artifact_block",
        "memory_block",
        "summary_block",
        "pinned_block",
        "active_skills_block",
        "available_skills_block",
    )


def _dedupe_text_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    if limit <= 0:
        return []

    selected: dict[str, tuple[tuple[float, ...], str]] = {}
    for recency_order, raw in enumerate(lines):
        line = str(raw or "").strip()
        if not line:
            continue
        key = _semantic_line_key(line) or f"line:{recency_order}"
        rank = (*_line_preference(line), float(recency_order))
        current = selected.get(key)
        if current is None or rank > current[0]:
            selected[key] = (rank, line)

    ordered = sorted(selected.values(), key=lambda item: item[0], reverse=True)
    return [line for _, line in ordered[:limit]]


def _dedupe_preferring_reference(
    preferred_lines: Iterable[str],
    candidate_lines: Iterable[str],
    *,
    limit: int,
) -> list[str]:
    if limit <= 0:
        return []
    preferred_keys = {_semantic_line_key(line) for line in preferred_lines if str(line or "").strip()}
    filtered = [
        str(line or "").strip()
        for line in candidate_lines
        if str(line or "").strip()
        and _semantic_line_key(str(line or "").strip()) not in preferred_keys
    ]
    return _dedupe_text_lines(filtered, limit=limit)


def _semantic_line_key(line: str) -> str:
    normalized = _LINE_SOURCE_PREFIX_RE.sub("", str(line or "").strip())
    artifact_key = _artifact_dedupe_key(normalized)
    if artifact_key:
        return artifact_key
    normalized = _LINE_SCORE_RE.sub("", normalized)
    normalized = _LINE_EVIDENCE_RE.sub("", normalized)
    normalized = _LINE_CONFIDENCE_RE.sub("", normalized)
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff/._:-]+", " ", normalized.casefold())
    return " ".join(normalized.split())


def _line_preference(line: str) -> tuple[float, ...]:
    lowered = line.casefold()
    evidence_match = _LINE_EVIDENCE_RE.search(line)
    evidence_count = 0
    if evidence_match:
        evidence_count = len([item.strip() for item in evidence_match.group(1).split(",") if item.strip()])
    return (
        1.0 if "approved" in lowered or "主线" in lowered or "root_thread/imported_conclusion" in lowered else 0.0,
        _extract_numeric(_LINE_CONFIDENCE_RE, line),
        float(evidence_count),
        _extract_numeric(_LINE_SCORE_RE, line),
        1.0 if _ARTIFACT_URI_RE.search(line) else 0.0,
        float(len(line)),
    )


def _current_plan_step_goal(state: dict[str, Any]) -> str:
    plan = state.get("plan")
    current_step_id = str(state.get("current_step_id") or "").strip()
    if not current_step_id or plan is None:
        return ""
    steps = getattr(plan, "steps", None)
    if steps is None and isinstance(plan, dict):
        steps = plan.get("steps")
    if not isinstance(steps, list):
        return ""
    for step in steps:
        step_id = getattr(step, "id", None)
        step_goal = getattr(step, "goal", None)
        if isinstance(step, dict):
            step_id = step.get("id", step_id)
            step_goal = step.get("goal", step_goal)
        if str(step_id or "") == current_step_id:
            return str(step_goal or "").strip()
    return ""


def _units_to_char_budget(units: int, *, budget: ContextBudget) -> int:
    multiplier = max(1, int(budget.chars_per_token))
    char_budget = max(0, int(units) * multiplier)
    if units > 0 and budget.token_budget_mode == "tokenizer_first":
        char_budget += max(16, multiplier * 2)
    return char_budget


def trim_tool_observation(
    observation: Any,
    *,
    tool_name: str = "",
    tool_call_id: str = "",
    budget: ContextBudget | None = None,
    max_chars: int | None = None,
    artifactize_for_prompt: bool = False,
    force_artifactize: bool = False,
) -> str:
    text = str(observation)
    effective_budget = budget or ContextBudget()
    limit = max_chars if max_chars is not None else _tool_observation_char_limit(effective_budget)
    limit = max(1, int(limit))
    enforce_token_budget = max_chars is None
    if _tool_observation_within_budget(
        text,
        budget=effective_budget,
        max_chars=limit,
        enforce_token_budget=enforce_token_budget,
    ) and not (artifactize_for_prompt and force_artifactize):
        return text

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        if not artifactize_for_prompt and budget is None and max_chars is not None and not tool_name:
            return _truncate_text(text, max_chars=limit)
        rendered = _format_textual_tool_reference(
            text,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            max_chars=limit,
            reference_chars=min(limit, _tool_reference_char_limit(effective_budget)),
        )
        if artifactize_for_prompt:
            textual_payload = json.loads(rendered)
            textual_payload["truncated_by_context_policy"] = True
            rendered = _truncate_json_payload(textual_payload, max_chars=limit)
        if not enforce_token_budget:
            return rendered
        return _fit_tool_observation_to_budget(
            rendered,
            payload=json.loads(rendered),
            budget=effective_budget,
            max_chars=limit,
        )

    compact = _compact_structured_observation(
        payload,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        max_chars=limit,
        reference_chars=min(limit, _tool_reference_char_limit(effective_budget)),
        artifactize_for_prompt=artifactize_for_prompt,
    )
    rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if _tool_observation_within_budget(
        rendered,
        budget=effective_budget,
        max_chars=limit,
        enforce_token_budget=enforce_token_budget,
    ):
        return rendered
    return _fit_tool_observation_to_budget(
        rendered,
        payload=compact,
        budget=effective_budget,
        max_chars=limit,
    )


def _fit_tool_observation_to_budget(
    text: str,
    *,
    budget: ContextBudget,
    max_chars: int,
    payload: Any | None = None,
) -> str:
    candidate_payload = payload
    if candidate_payload is None:
        try:
            candidate_payload = json.loads(text)
        except json.JSONDecodeError:
            candidate_payload = None

    def _render(limit: int) -> str:
        if isinstance(candidate_payload, (dict, list)):
            return _truncate_json_payload(candidate_payload, max_chars=limit)
        return _truncate_text(text, max_chars=limit)

    candidate = _render(max_chars)
    if _tool_observation_within_budget(
        candidate,
        budget=budget,
        max_chars=max_chars,
        enforce_token_budget=True,
    ):
        return candidate

    low = 2 if isinstance(candidate_payload, (dict, list)) else 1
    high = min(len(candidate), max_chars)
    best = candidate
    while low <= high:
        mid = (low + high) // 2
        probe = _render(mid)
        if _tool_observation_within_budget(
            probe,
            budget=budget,
            max_chars=max_chars,
            enforce_token_budget=True,
        ):
            best = probe
            low = mid + 1
        else:
            high = mid - 1
    return best


def _format_textual_tool_reference(
    text: str,
    *,
    tool_name: str,
    tool_call_id: str,
    max_chars: int,
    reference_chars: int,
) -> str:
    reference_budget = max(18, min(max_chars // 3, reference_chars, 36))
    payload = {
        "summary": f"{tool_name or 'tool'} trimmed.",
        "reference": _truncate_text(_collapse_inline(text), max_chars=reference_budget),
        "original_chars": len(text),
    }
    if tool_call_id or tool_name in {"search_code", "read_file"}:
        payload["tool"] = tool_name or "tool"
    if tool_call_id:
        payload["artifact_ref"] = _tool_observation_ref(tool_name=tool_name, tool_call_id=tool_call_id)
    payload = {key: value for key, value in payload.items() if value is not None}
    return _truncate_json_payload(payload, max_chars=max_chars)


def _structured_tool_reference(
    payload: dict[str, Any],
    *,
    tool_name: str,
    max_chars: int,
    artifactize_for_prompt: bool,
) -> str:
    details: list[str] = []
    if tool_name == "search_code":
        query = str(payload.get("query") or "").strip()
        if query:
            details.append(f"query={query}")
        results = payload.get("results")
        if isinstance(results, list):
            details.append(f"hits={len(results)}")
    elif tool_name == "read_file":
        path = str(payload.get("path") or "").strip()
        if path:
            details.append(f"path={path}")
        start_line = payload.get("start_line")
        end_line = payload.get("end_line")
        if start_line is not None and end_line is not None:
            details.append(f"lines={start_line}-{end_line}")
        total_lines = payload.get("total_lines")
        if total_lines is not None:
            details.append(f"total_lines={total_lines}")
        sample_line = next(
            (line.strip() for line in str(payload.get("content") or "").splitlines() if line.strip()),
            "",
        )
        if sample_line:
            details.append(f"sample={_collapse_inline(sample_line)[:120]}")
    else:
        for key in ("path", "url", "title", "query"):
            value = str(payload.get(key) or "").strip()
            if value:
                details.append(f"{key}={value}")
    if artifactize_for_prompt:
        refs = _collect_artifact_like_refs(payload)
        if refs:
            details[:0] = [f"refs={', '.join(refs[:4])}"]
    if not details:
        details.append("original observation omitted from prompt body")
    return _collapse_inline("; ".join(details))[:max_chars]


def _truncate_bulleted_block(text: str, *, max_chars: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    if len(lines) < 2 or not lines[0].startswith("## "):
        return ""

    header = lines[0].strip()
    body_lines = [line.strip() for line in lines[1:] if line.strip()]
    if not body_lines:
        return ""

    kept_lines = [header]
    used = len(header)
    omitted_lines: list[str] = []
    prioritized_lines = list(body_lines)
    if header.casefold().startswith("## constraints and goals"):
        bullets = [line for line in body_lines if line.startswith("- ")]
        if bullets:
            last_bullet = bullets[-1]
            prioritized_lines = [last_bullet, *[line for line in body_lines if line != last_bullet]]

    for body_line in prioritized_lines:
        extra = len(body_line) + 1
        if used + extra > max_chars:
            omitted_lines.append(body_line)
            continue
        kept_lines.append(body_line)
        used += extra

    if len(kept_lines) == 1:
        omitted_note = f"- ...[{len(body_lines)} omitted]"
        if len(header) + 1 + len(omitted_note) <= max_chars:
            return "\n".join([header, omitted_note])
        return header if len(header) <= max_chars else _truncate_block(header, max_chars=max_chars)

    rendered = "\n".join(kept_lines)
    if omitted_lines:
        note = f"\n- ...[{len(omitted_lines)} more omitted]"
        if len(rendered) + len(note) <= max_chars:
            rendered += note
    return rendered


def _render_block_order(prompt_mode: PromptMode) -> tuple[str, ...]:
    if prompt_mode == PromptMode.SYNTHESIZE:
        return (
            "system_instructions",
            "constraints_block",
            "findings_block",
            "memory_block",
            "pinned_block",
            "summary_block",
            "active_skills_block",
            "available_skills_block",
            "artifact_block",
        )
    if prompt_mode == PromptMode.BRANCH_REVIEW:
        return (
            "system_instructions",
            "findings_block",
            "artifact_block",
            "constraints_block",
            "pinned_block",
            "memory_block",
            "summary_block",
            "active_skills_block",
            "available_skills_block",
        )
    if prompt_mode == PromptMode.EXECUTE:
        return (
            "system_instructions",
            "constraints_block",
            "pinned_block",
            "findings_block",
            "artifact_block",
            "memory_block",
            "summary_block",
            "active_skills_block",
            "available_skills_block",
        )
    return (
        "system_instructions",
        "constraints_block",
        "findings_block",
        "artifact_block",
        "memory_block",
        "summary_block",
        "pinned_block",
        "active_skills_block",
        "available_skills_block",
    )


def _dedupe_ranked_lines(lines: Iterable[str], *, limit: int, key_fn, rank_fn) -> list[str]:
    if limit <= 0:
        return []
    selected: dict[str, tuple[tuple[Any, ...], str]] = {}
    for recency_order, raw in enumerate(str(line).strip() for line in lines if str(line).strip()):
        key = key_fn(raw)
        rank = (*rank_fn(raw), recency_order)
        current = selected.get(key)
        if current is None or rank > current[0]:
            selected[key] = (rank, raw)
    ordered = sorted(selected.values(), key=lambda item: item[0], reverse=True)
    return [line for _, line in ordered[:limit]][::-1]


def _text_line_dedupe_key(line: str) -> str:
    return " ".join(str(line).split()).casefold()


def _finding_line_dedupe_key(line: str) -> str:
    normalized = _LINE_SOURCE_PREFIX_RE.sub("", str(line).strip())
    normalized = _LINE_EVIDENCE_RE.sub("", normalized)
    normalized = _LINE_CONFIDENCE_RE.sub("", normalized)
    normalized = _LINE_SCORE_RE.sub("", normalized)
    return _text_line_dedupe_key(normalized)


def _memory_line_dedupe_key(line: str) -> str:
    normalized = _LINE_SOURCE_PREFIX_RE.sub("", str(line).strip())
    normalized = _LINE_SCORE_RE.sub("", normalized)
    return _text_line_dedupe_key(normalized)


def _artifact_line_dedupe_key(line: str) -> str:
    normalized = _ARTIFACT_URI_RE.sub("", str(line).strip())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.casefold()


def _finding_line_rank(line: str) -> tuple[int, float, int, int]:
    text = str(line)
    promoted = 1 if "approved" in text.casefold() or text.startswith("[root_thread") else 0
    confidence = _extract_numeric(_LINE_CONFIDENCE_RE, text)
    evidence_count = 0
    evidence_match = _LINE_EVIDENCE_RE.search(text)
    if evidence_match:
        evidence_count = len([item for item in evidence_match.group(1).split(",") if item.strip()])
    return promoted, confidence, evidence_count, len(text)


def _memory_line_rank(line: str) -> tuple[int, float, int]:
    text = str(line)
    promoted = 1 if "root_thread/imported_conclusion" in text else 0
    score = _extract_numeric(_LINE_SCORE_RE, text)
    return promoted, score, len(text)


def _artifact_line_rank(line: str) -> tuple[int, int, int]:
    text = str(line)
    has_uri = 1 if _ARTIFACT_URI_RE.search(text) else 0
    return has_uri, len(text), 0


def _extract_numeric(pattern: re.Pattern[str], text: str) -> float:
    match = pattern.search(text)
    if match is None:
        return 0.0
    try:
        return float(match.group(1))
    except (IndexError, ValueError):
        return 0.0


def _dedupe_text_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(lines, limit=limit, key_fn=_text_line_dedupe_key, rank_fn=lambda line: (len(line),))


def _dedupe_finding_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(lines, limit=limit, key_fn=_finding_line_dedupe_key, rank_fn=_finding_line_rank)


def _dedupe_memory_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(lines, limit=limit, key_fn=_memory_line_dedupe_key, rank_fn=_memory_line_rank)


def _dedupe_artifact_lines(lines: Iterable[str], *, limit: int) -> list[str]:
    return _dedupe_ranked_lines(lines, limit=limit, key_fn=_artifact_line_dedupe_key, rank_fn=_artifact_line_rank)


def _dedupe_preferring_reference(reference_lines: Iterable[str], candidate_lines: Iterable[str], *, limit: int) -> list[str]:
    if limit <= 0:
        return []
    reference_keys = {_finding_line_dedupe_key(line) for line in reference_lines if str(line).strip()}
    filtered = [
        str(line).strip()
        for line in candidate_lines
        if str(line).strip() and _finding_line_dedupe_key(str(line)) not in reference_keys
    ]
    return _dedupe_finding_lines(filtered, limit=limit)


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _current_plan_step_goal(state: dict[str, Any]) -> str:
    plan = state.get("plan")
    current_step_id = str(state.get("current_step_id") or "").strip()
    if current_step_id and hasattr(plan, "steps"):
        for step in getattr(plan, "steps", []) or []:
            if str(getattr(step, "id", "")) == current_step_id:
                return str(getattr(step, "goal", "") or "").strip()
    if plan is None:
        return ""
    steps = getattr(plan, "steps", None)
    if steps is None and isinstance(plan, dict):
        steps = plan.get("steps")
    if not isinstance(steps, list):
        return ""
    for step in steps:
        done = getattr(step, "done", None)
        goal = getattr(step, "goal", None)
        if isinstance(step, dict):
            done = step.get("done", done)
            goal = step.get("goal", goal)
        if not done and goal:
            return str(goal).strip()
    return ""
