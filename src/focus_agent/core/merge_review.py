from __future__ import annotations

import json
from typing import Any

from langchain.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from focus_agent.prompts import get_registry

from .branch_brief import message_visible_text
from .branching import MergeMode, MergeProposal
from .merge_review_inputs import (
    artifact_lines,
    branch_local_messages,
    branch_owned_findings,
    branch_summary,
    citation_lines,
    clip_text,
    evidence_ledger_lines,
    filter_known_refs,
    finding_refs,
    finding_text,
    known_evidence_refs,
    received_import_entries,
    received_import_findings,
    render_received_imports,
    render_transcript,
    split_at_fork,
)

_MERGE_REVIEW_SYSTEM_PROMPT_ID = "merge_review.json_proposal.system"
_MERGE_REVIEW_USER_PROMPT_ID = "merge_review.proposal.user"


def _json_system_prompt() -> str:
    return get_registry().render(_MERGE_REVIEW_SYSTEM_PROMPT_ID)


def _extract_text_messages(state: dict[str, Any], limit: int = 10) -> list[str]:
    lines: list[str] = []
    for message in branch_local_messages(state)[-limit:]:
        role = message.__class__.__name__.replace("Message", "").lower()
        lines.append(f"{role}: {message_visible_text(message)}")
    return lines


def _contains_cjk(text: str) -> bool:
    return any("一" <= char <= "鿿" for char in text)


def _preferred_output_language(state: dict[str, Any]) -> str:
    samples: list[str] = []
    samples.extend(finding_text(item) for item in branch_owned_findings(state)[:6])
    samples.extend(_extract_text_messages(state, limit=6))
    if state.get("rolling_summary"):
        samples.append(str(state.get("rolling_summary")))
    joined = "\n".join(samples)
    return "Chinese" if _contains_cjk(joined) else "English"


def _local_interaction_summary(state: dict[str, Any]) -> str:
    lines: list[str] = []
    for line in _extract_text_messages(state, limit=6):
        normalized = clip_text(line, 140)
        if normalized:
            lines.append(normalized)
    if not lines:
        return "(none)"
    return "\n".join(lines[:6])


def _brief_inherited_context(state: dict[str, Any]) -> str:
    parts: list[str] = []
    inherited = split_at_fork(state, "merge_queue")[0]
    for item in inherited[-2:]:
        if not isinstance(item, dict):
            continue
        summary = clip_text(item.get("summary", ""), 80)
        branch_name = clip_text(item.get("branch_name", "branch"), 40) or "branch"
        if summary:
            parts.append(f"{branch_name}: {summary}")
    if not parts:
        return "(none)"
    return " | ".join(parts[:2])


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) or "(none)"


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _last_local_answer(state: dict[str, Any]) -> str:
    for message in reversed(branch_local_messages(state)):
        if message.__class__.__name__ == "AIMessage" or getattr(message, "type", "") == "ai":
            return clip_text(message_visible_text(message), 220)
    return ""


def fallback_merge_proposal(state: dict[str, Any]) -> MergeProposal:
    """Deterministic proposal when the model is unavailable.

    An empty branch yields an empty summary, which merge apply refuses to
    import, instead of a placeholder sentence that reads like a conclusion.
    """
    finding_items = [*branch_owned_findings(state), *received_import_findings(state)]
    findings: list[str] = []
    evidence_refs: list[str] = []
    per_finding: dict[str, list[str]] = {}
    for item in finding_items:
        text = finding_text(item)
        if not text or text in findings:
            continue
        findings.append(text)
        refs = finding_refs(item)
        if refs:
            per_finding[text] = refs
            evidence_refs.extend(ref for ref in refs if ref not in evidence_refs)
    findings = findings[:8]
    open_questions: list[str] = []
    for entry in received_import_entries(state):
        for question in entry.get("open_questions") or []:
            if str(question).strip() and question not in open_questions:
                open_questions.append(str(question).strip())
    summary = findings[0] if findings else _last_local_answer(state)
    return MergeProposal(
        summary=str(summary)[:1200],
        key_findings=findings,
        open_questions=open_questions[:6],
        evidence_refs=evidence_refs,
        artifacts=artifact_lines(state)[:8],
        recommended_import_mode=MergeMode.SUMMARY_ONLY,
        finding_evidence_refs={key: value for key, value in per_finding.items() if key in findings},
    )


def _normalize_proposal_payload(data: dict[str, Any], *, known_refs: set[str]) -> dict[str, Any]:
    """Accept per-finding refs and drop evidence refs unknown to this branch."""
    payload = dict(data)
    per_finding: dict[str, list[str]] = {}
    raw_per_finding = payload.get("finding_evidence_refs")
    if isinstance(raw_per_finding, dict):
        for key, refs in raw_per_finding.items():
            if isinstance(refs, list):
                per_finding[str(key).strip()] = list(refs)
    findings: list[str] = []
    for item in payload.get("key_findings") or []:
        if isinstance(item, dict):
            text = str(item.get("finding") or "").strip()
            refs = item.get("evidence_refs")
            if text and isinstance(refs, list):
                per_finding[text] = list(refs)
        else:
            text = str(item or "").strip()
        if text:
            findings.append(text)
    payload["key_findings"] = findings
    filtered_per_finding = {
        text: kept
        for text, refs in per_finding.items()
        if text in findings and (kept := filter_known_refs(refs, known_refs))
    }
    flat = filter_known_refs(payload.get("evidence_refs") or [], known_refs)
    for refs in filtered_per_finding.values():
        flat.extend(ref for ref in refs if ref not in flat)
    payload["evidence_refs"] = flat
    payload["finding_evidence_refs"] = filtered_per_finding
    if payload.get("summary") is None:
        payload["summary"] = ""
    return payload


def generate_merge_proposal(
    model, state: dict[str, Any], branch_meta: dict[str, Any] | None
) -> MergeProposal:
    local_messages = branch_local_messages(state)
    transcript = render_transcript(local_messages)
    finding_lines = [finding_text(item) for item in branch_owned_findings(state)]
    findings = "\n".join(f"- {item}" for item in finding_lines if item) or "- none"
    evidence = [*citation_lines(state), *evidence_ledger_lines(state)]
    branch_name = (branch_meta or {}).get("branch_name", "unnamed-branch")
    branch_role = (branch_meta or {}).get("branch_role", "explore_alternatives")

    prompt = (
        get_registry()
        .render(
            _MERGE_REVIEW_USER_PROMPT_ID,
            branch_name=branch_name,
            branch_role=branch_role,
            output_language=_preferred_output_language(state),
            inherited_context=_brief_inherited_context(state),
            branch_summary=branch_summary(state) or "(none)",
            received_imports=render_received_imports(state),
            local_interaction_summary=_local_interaction_summary(state),
            findings=findings,
            evidence=_bullets(evidence),
            artifacts=_bullets(artifact_lines(state)),
            transcript=transcript or "(empty)",
        )
        .strip()
    )

    try:
        response = model.invoke(
            [
                SystemMessage(content=_json_system_prompt()),
                HumanMessage(content=prompt),
            ]
        )
    except Exception:
        return fallback_merge_proposal(state)
    content = response.content
    if isinstance(content, list):
        content = json.dumps(content, ensure_ascii=False)

    try:
        data = _extract_json(str(content))
        if not isinstance(data, dict):
            return fallback_merge_proposal(state)
        payload = _normalize_proposal_payload(data, known_refs=known_evidence_refs(state))
        return MergeProposal.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return fallback_merge_proposal(state)
