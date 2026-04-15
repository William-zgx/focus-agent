from __future__ import annotations

from typing import Any

from .core.request_context import RequestContext


def _render_lines(title: str, lines: list[str]) -> str:
    if not lines:
        return f"## {title}\n(none)"
    return "## " + title + "\n" + "\n".join(f"- {line}" for line in lines)


def build_system_prompt(
    *,
    context: RequestContext,
    branch_meta: dict[str, Any] | None,
    rolling_summary: str,
    pinned_items: list[str],
    imported_conclusions: list[dict[str, Any]],
    memories: list[str],
) -> str:
    if branch_meta:
        branch_block = (
            "## Branch scope\n"
            f"- branch_id: {branch_meta.get('branch_id')}\n"
            f"- branch_name: {branch_meta.get('branch_name')}\n"
            f"- branch_role: {branch_meta.get('branch_role')}\n"
            "- This is a child branch. Stay focused on this local exploration.\n"
            "- This branch may later be reviewed for upstream import into its return thread.\n"
            "- Do not assume any local conclusion has returned to the parent thread unless it appears in imported conclusions or the user says so."
        )
    else:
        branch_block = "## Branch scope\n- This is the main thread."

    imported_lines: list[str] = []
    for item in imported_conclusions[-5:]:
        imported_lines.append(
            f"[{item.get('branch_name', item.get('branch_id', 'branch'))}] {item.get('summary', '')}"
        )

    return "\n\n".join(
        [
            "You are Focus Agent, a concise research-oriented assistant optimized for long dialogues.",
            "Your job is to keep the conversation focused, maintain clean working context, and avoid polluting the main line with unreviewed side explorations.",
            "When you are in a branch, produce local conclusions clearly. When a merge proposal exists, wait for explicit user approval before assuming anything will be imported upstream.",
            f"## Scene\n- {context.scene}",
            branch_block,
            f"## Rolling summary\n{rolling_summary or '(empty)'}",
            _render_lines("Pinned items", pinned_items[-10:]),
            _render_lines("Imported conclusions from sibling/child branches", imported_lines),
            _render_lines("Long-term memories", memories[-10:]),
        ]
    )
