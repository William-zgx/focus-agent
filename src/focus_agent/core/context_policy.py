from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

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


def approximate_token_count(value: Any, *, chars_per_token: int = 4) -> int:
    text = _text_for_budget(value)
    if not text:
        return 0
    return max(1, (len(text) + max(chars_per_token, 1) - 1) // max(chars_per_token, 1))


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

    max_chars = _prompt_char_limit(budget)
    guarded = [
        _trim_message_tool_observation(message, max_chars=_tool_observation_char_limit(budget))
        for message in prompt_messages
    ]
    if _prompt_char_count(guarded) <= max_chars:
        return guarded

    main_system_index = _first_main_system_index(guarded)
    if main_system_index is not None:
        mandatory_indices = _mandatory_prompt_indices(guarded)
        other_chars = _prompt_char_count(
            [
                message
                for index, message in enumerate(guarded)
                if index != main_system_index
                and (index in mandatory_indices or isinstance(message, SystemMessage))
            ]
        )
        target_chars = max(0, max_chars - other_chars)
        trimmed_system = _trim_system_text_by_blocks(
            _text_for_budget(guarded[main_system_index]),
            max_chars=target_chars,
        )
        guarded[main_system_index] = _copy_message_with_content(
            guarded[main_system_index],
            trimmed_system,
        )

    if _prompt_char_count(guarded) <= max_chars:
        return guarded

    mandatory_indices = _mandatory_prompt_indices(guarded)
    removable = [
        index
        for index, message in enumerate(guarded)
        if index not in mandatory_indices and not isinstance(message, SystemMessage)
    ]
    for index in reversed(removable):
        if _prompt_char_count(guarded) <= max_chars:
            break
        del guarded[index]
        mandatory_indices = _mandatory_prompt_indices(guarded)

    if _prompt_char_count(guarded) <= max_chars:
        return guarded

    guarded = _shrink_tool_messages_to_fit(guarded, max_chars=max_chars)
    if _prompt_char_count(guarded) <= max_chars:
        return guarded

    return _hard_limit_prompt_messages(guarded, max_chars=max_chars)


def trim_tool_observation(
    observation: Any,
    *,
    tool_name: str = "",
    budget: ContextBudget | None = None,
    max_chars: int | None = None,
) -> str:
    text = str(observation)
    limit = max_chars if max_chars is not None else _tool_observation_char_limit(budget or ContextBudget())
    limit = max(1, int(limit))
    if len(text) <= limit:
        return text

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _truncate_text(text, max_chars=limit)

    compact = _compact_structured_observation(payload, tool_name=tool_name, max_chars=limit)
    rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    if len(rendered) <= limit:
        return rendered
    return _truncate_json_payload(compact, max_chars=limit)


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


def _prompt_char_count(messages: list[AnyMessage]) -> int:
    return sum(len(_text_for_budget(message)) for message in messages)


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


def _trim_message_tool_observation(message: AnyMessage, *, max_chars: int) -> AnyMessage:
    if not isinstance(message, ToolMessage):
        return message
    trimmed = trim_tool_observation(message.content, max_chars=max_chars)
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


def _trim_system_text_by_blocks(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    blocks = _split_context_blocks(text)
    selected: set[int] = set()
    omitted = False
    used = 0

    for priority in range(0, 6):
        for index, block in enumerate(blocks):
            if index in selected or _context_block_priority(block, index=index) != priority:
                continue
            extra = len(block) + (2 if selected else 0)
            if used + extra <= max_chars:
                selected.add(index)
                used += extra
                continue
            remaining = max_chars - used - (2 if selected else 0)
            if priority <= 1 and remaining >= _minimum_truncation_budget(block):
                blocks[index] = _truncate_context_block(block, max_chars=remaining)
                selected.add(index)
                used = max_chars
            elif priority <= 3 and remaining >= _minimum_truncation_budget(block):
                blocks[index] = _truncate_context_block(block, max_chars=remaining)
                selected.add(index)
                used = max_chars
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


def _context_block_priority(block: str, *, index: int) -> int:
    lowered = block.lower()
    if lowered.endswith("(none)"):
        return 5
    if lowered.startswith("## constraints and goals") or lowered.startswith("## 当前计划"):
        return 0
    if index == 0:
        return 1
    if lowered.startswith("## pinned facts"):
        return 2
    if lowered.startswith("## imported findings already approved into this thread"):
        return 2
    if lowered.startswith("## local branch findings pending upstream review"):
        return 3
    if lowered.startswith("## artifacts in scope"):
        return 3
    if lowered.startswith("## prompt mode") or lowered.startswith("## branch scope"):
        return 3
    if lowered.startswith("## scene") or lowered.startswith("## skill system") or lowered.startswith("## active skills"):
        return 3
    if lowered.startswith("## rolling summary"):
        return 4
    if lowered.startswith("## retrieved long-term memories"):
        return 4
    if lowered.startswith("## findings"):
        return 4
    if lowered.startswith("## available skills"):
        return 5
    return 5


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
    omitted_count = 0

    for bullet in bullets:
        extra = len(bullet) + 1
        if used + extra > max_chars:
            omitted_count += 1
            continue
        kept_lines.append(bullet)
        used += extra

    if len(kept_lines) == 1:
        remaining = max_chars - used - 1
        if remaining >= 18:
            kept_lines.append(bullets[0][:remaining].rstrip())
            return "\n".join(kept_lines)
        omitted_note = f"- ...[{len(bullets)} omitted]"
        if len(header) + 1 + len(omitted_note) <= max_chars:
            return "\n".join([header, omitted_note])
        if len(header) <= max_chars:
            return header
        return _truncate_block(header, max_chars=max_chars)

    rendered = "\n".join(kept_lines)
    if omitted_count:
        note = f"\n- ...[{omitted_count} more omitted]"
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


def _shrink_tool_messages_to_fit(messages: list[AnyMessage], *, max_chars: int) -> list[AnyMessage]:
    guarded = list(messages)
    for index in range(len(guarded) - 1, -1, -1):
        if _prompt_char_count(guarded) <= max_chars:
            break
        message = guarded[index]
        if not isinstance(message, ToolMessage):
            continue
        overflow = _prompt_char_count(guarded) - max_chars
        current = _text_for_budget(message)
        target = max(200, len(current) - overflow - 16)
        guarded[index] = _copy_message_with_content(
            message,
            trim_tool_observation(current, max_chars=target),
        )
    return guarded


def _hard_limit_prompt_messages(messages: list[AnyMessage], *, max_chars: int) -> list[AnyMessage]:
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
        if _prompt_char_count(guarded) <= max_chars:
            break
        message = guarded[index]
        current = _text_for_budget(message)
        overflow = _prompt_char_count(guarded) - max_chars
        target = max(0, len(current) - overflow - 16)
        if isinstance(message, ToolMessage):
            content = trim_tool_observation(current, max_chars=target)
        elif isinstance(message, SystemMessage):
            content = _truncate_context_block(current, max_chars=target)
        else:
            content = _truncate_block(current, max_chars=target)
        guarded[index] = _copy_message_with_content(message, content)

    return guarded


def _compact_structured_observation(payload: Any, *, tool_name: str, max_chars: int) -> Any:
    if isinstance(payload, list):
        return {
            "items": _compact_result_list(payload, max_chars=max_chars),
            "truncated_by_context_policy": True,
        }
    if not isinstance(payload, dict):
        return _truncate_text(str(payload), max_chars=max_chars)

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
        compact["results"] = _compact_result_list(payload["results"], max_chars=max_chars)
    elif "hits" in payload and isinstance(payload["hits"], list):
        compact["hits"] = _compact_result_list(payload["hits"], max_chars=max_chars)

    if "content" in payload:
        compact["content"] = _trim_numbered_content(str(payload.get("content") or ""), max_chars=max_chars // 2)
    if "diff" in payload:
        compact["diff"] = _trim_diff(str(payload.get("diff") or ""), max_chars=max_chars // 2)

    if tool_name and "tool" not in compact:
        compact["tool"] = tool_name
    compact["truncated_by_context_policy"] = True
    compact["original_chars"] = len(json.dumps(payload, ensure_ascii=False, default=str))
    return compact


def _compact_result_list(results: list[Any], *, max_chars: int) -> list[Any]:
    compact_results: list[Any] = []
    for result in results:
        if isinstance(result, dict):
            compact = {}
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
                "truncated_by_context_policy",
                "original_chars",
            }
        }
        rendered = json.dumps(compact, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(rendered) <= max_chars:
        return rendered
    return _truncate_text(rendered, max_chars=max_chars)


def _collapse_inline(text: str) -> str:
    return " ".join(text.split())


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
