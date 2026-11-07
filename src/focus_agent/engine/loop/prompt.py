"""Operating guidance for the model-driven loop."""

from __future__ import annotations

from collections.abc import Iterable

from .todos import TODO_WRITE_TOOL_NAME

_WORKING_RULES = (
    "## How to work\n"
    "- Answer directly when reliable; otherwise use tools for workspace, current/external, "
    "or execution-dependent facts. For short questions, use the fewest targeted calls "
    "that locate the answer (usually 1-3), then stop and answer.\n"
    "- Do not audit or modify the workspace or create artifacts unless explicitly asked. "
    "A statement of a rule or preference calls for a direct response, not verification "
    "or changes.\n"
    "- Batch only independent calls. Read each result before continuing. If output is "
    "truncated, narrow the query or read a specific section instead of rereading the "
    "whole result. When a tool fails, change the arguments or approach; never repeat "
    "an identical call.\n"
    "- Facts, test results and decisions the user reports are established context unless "
    "they conflict with other evidence. Do not relabel them as unverified because you "
    "have not seen the source, and do not reopen decisions the user has settled.\n"
    "- The final answer is for the user: no process narration or tool syntax, and never "
    "empty. When asked for a deliverable, deliver it with a clear conclusion and keep "
    "caveats to the risks that matter. When web sources support a claim, cite them "
    "inline as markdown links."
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
# memory_search/memory_forget guidance is only useful alongside memory_save.
_MEMORY_RULES = {
    "memory_save": (
        "- Use memory_save when the user states a durable fact about themselves, their "
        "preferences, or the project that will matter in future conversations, or when they "
        "ask you to remember something. Skip transient task details, secrets and credentials, "
        "and facts already in the memories above."
    ),
    "memory_search": (
        "- Use memory_search when past context would materially help and is not already "
        "in the prompt."
    ),
    "memory_forget": "- Use memory_forget when the user asks you to forget something.",
}
_TOOL_BUDGET_EXHAUSTED_NOTE = (
    "The tool budget for this turn is used up and no tools are available. Answer now "
    "from the evidence already gathered, and say plainly which parts remain unverified."
)
_SUBTASK_RULE = (
    "- Use run_subtask for broad research or independent investigations whose intermediate "
    "context would flood this conversation, not for trivial lookups. Give it a complete, "
    "self-contained prompt."
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
    if "run_subtask" in names:
        rules.append(_SUBTASK_RULE)
    if "memory_save" in names:
        rules.extend(rule for name, rule in _MEMORY_RULES.items() if name in names)
    return "\n".join(rules)


__all__ = ["operating_note"]
