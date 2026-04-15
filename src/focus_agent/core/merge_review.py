from __future__ import annotations

import json
from typing import Any

from langchain.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from .branching import MergeMode, MergeProposal


JSON_SYSTEM_PROMPT = """You generate a JSON merge proposal for a branch conversation.
Return valid JSON only. No markdown fences. No prose outside JSON.
Schema:
{
  "summary": str,
  "key_findings": [str],
  "open_questions": [str],
  "evidence_refs": [str],
  "artifacts": [str],
  "recommended_import_mode": "none" | "summary_only" | "summary_plus_evidence" | "selected_artifacts"
}
"""


def _extract_text_messages(state: dict[str, Any], limit: int = 10) -> list[str]:
    lines: list[str] = []
    for message in state.get("messages", [])[-limit:]:
        role = message.__class__.__name__.replace("Message", "").lower()
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        lines.append(f"{role}: {content}")
    return lines


def _coerce_finding_text(item: Any) -> str:
    if hasattr(item, "finding"):
        return str(getattr(item, "finding") or "").strip()
    if isinstance(item, dict):
        return str(item.get("finding") or "").strip()
    return str(item or "").strip()


def _normalize_inline_text(value: Any, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _preferred_output_language(state: dict[str, Any]) -> str:
    samples: list[str] = []
    samples.extend(_coerce_finding_text(item) for item in state.get("branch_local_findings", [])[:6])
    samples.extend(_extract_text_messages(state, limit=6))
    if state.get("rolling_summary"):
        samples.append(str(state.get("rolling_summary")))
    joined = "\n".join(samples)
    return "Chinese" if _contains_cjk(joined) else "English"


def _local_interaction_summary(state: dict[str, Any]) -> str:
    lines: list[str] = []
    for line in _extract_text_messages(state, limit=6):
        normalized = _normalize_inline_text(line, max_chars=140)
        if normalized:
            lines.append(normalized)
    if not lines:
        return "(none)"
    return "\n".join(lines[:6])


def _brief_inherited_context(state: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in list(state.get("merge_queue", []))[:2]:
        if not isinstance(item, dict):
            continue
        summary = _normalize_inline_text(item.get("summary", ""), max_chars=80)
        branch_name = _normalize_inline_text(item.get("branch_name", "branch"), max_chars=40) or "branch"
        if summary:
            parts.append(f"{branch_name}: {summary}")
    if not parts:
        return "(none)"
    return " | ".join(parts[:2])


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


def fallback_merge_proposal(state: dict[str, Any]) -> MergeProposal:
    output_language = _preferred_output_language(state)
    findings = [_coerce_finding_text(item) for item in list(state.get("branch_local_findings", []))[:8]]
    findings = [item for item in findings if item]
    artifacts = [str(item) for item in state.get("artifacts", [])[:8]]
    if not findings:
        findings = ["暂无明确的分支交互结论记录。"] if output_language == "Chinese" else ["No explicit branch interaction conclusions were recorded yet."]
    summary = findings[0] if findings else _normalize_inline_text(_local_interaction_summary(state), max_chars=220)
    return MergeProposal(
        summary=str(summary)[:1200],
        key_findings=findings,
        open_questions=[],
        evidence_refs=[],
        artifacts=artifacts,
        recommended_import_mode=MergeMode.SUMMARY_ONLY,
    )


def generate_merge_proposal(model, state: dict[str, Any], branch_meta: dict[str, Any] | None) -> MergeProposal:
    transcript = "\n".join(_extract_text_messages(state))
    finding_lines = [_coerce_finding_text(item) for item in state.get("branch_local_findings", [])]
    findings = "\n".join(f"- {item}" for item in finding_lines if item) or "- none"
    inherited_context = _brief_inherited_context(state)
    branch_name = (branch_meta or {}).get("branch_name", "unnamed-branch")
    branch_role = (branch_meta or {}).get("branch_role", "explore_alternatives")
    output_language = _preferred_output_language(state)

    prompt = f"""
Branch name: {branch_name}
Branch role: {branch_role}
Output language: {output_language}

Instructions:
- Generate the conclusion mainly from this branch's own interaction history.
- Summarize only what this branch newly discovered, verified, decided, or clarified.
- Do not restate parent-thread context unless this branch materially changed or challenged it.
- If inherited context is mentioned at all, keep it to a very short orienting phrase.

Inherited upstream context (brief):
{inherited_context}

This branch's recent interaction history:
{_local_interaction_summary(state)}

Recorded findings:
{findings}

Recent transcript:
{transcript or '(empty)'}
""".strip()

    response = model.invoke(
        [
            SystemMessage(content=JSON_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
    )
    content = response.content
    if isinstance(content, list):
        content = json.dumps(content, ensure_ascii=False)

    try:
        data = _extract_json(str(content))
        return MergeProposal.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return fallback_merge_proposal(state)
