"""Operating guidance for the model-driven loop."""

from __future__ import annotations

from collections.abc import Iterable

from .todos import TODO_WRITE_TOOL_NAME

_WORKING_RULES = (
    "## How to work\n"
    "- Decide for yourself whether tools are needed. Answer directly when you can "
    "answer reliably; use tools when the answer depends on the workspace, on current "
    "or external information, or on running something.\n"
    "- Call independent tools together in one step so they run in parallel. Read each "
    "result before deciding the next step, and stop once the evidence is sufficient.\n"
    "- When a tool fails, change the arguments or the approach; never repeat an "
    "identical call.\n"
    "- The final answer is for the user: no process narration, no tool syntax. When "
    "web sources support a claim, cite them inline as markdown links."
)
_TIME_RULE = (
    "- For anything time-sensitive (latest, today, recent releases, current versions), "
    "call current_utc_time first and anchor searches and the answer to that date "
    "instead of your training data."
)
_WEB_RULE = (
    "- For external facts, search with focused queries, then open the most relevant "
    "pages with web_fetch before relying on them; search snippets alone are weak evidence."
)
_TODO_RULE = (
    "- For multi-step work with three or more distinct steps, track progress with "
    "todo_write: list the steps before starting, keep one item in_progress, and mark each "
    "completed as soon as it is done. Send the update together with your next tool calls "
    "instead of as a separate step. Skip it for simple questions and single-step tasks."
)
_TOOL_BUDGET_EXHAUSTED_NOTE = (
    "The tool budget for this turn is used up and no tools are available. Answer now "
    "from the evidence already gathered, and say plainly which parts remain unverified."
)


def operating_note(tool_names: Iterable[str], *, tool_budget_exhausted: bool) -> str:
    if tool_budget_exhausted:
        return _TOOL_BUDGET_EXHAUSTED_NOTE
    names = set(tool_names)
    if not names:
        return ""
    rules = [_WORKING_RULES]
    if "current_utc_time" in names:
        rules.append(_TIME_RULE)
    if {"web_search", "web_fetch"} <= names:
        rules.append(_WEB_RULE)
    if TODO_WRITE_TOOL_NAME in names:
        rules.append(_TODO_RULE)
    return "\n".join(rules)


__all__ = ["operating_note"]
