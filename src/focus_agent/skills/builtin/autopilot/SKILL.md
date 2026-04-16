---
name: autopilot
description: Execute a task end-to-end with strong ownership, verification, and concise progress reporting.
triggers: autopilot:
when_to_use: The user wants autonomous execution, The task should be carried through without repeated confirmation
recommended_tools: list_files, search_code, read_file, git_status, git_diff, write_text_artifact
prompt_mode: execute
---
# Autopilot

- Drive the task to a concrete outcome instead of stopping at analysis.
- Gather the minimum context needed with the repo tools first: `list_files` for structure, `search_code` for entry points, `read_file` for exact local context, and `git_status` when current worktree state matters.
- Act, then verify the result before finishing; use `git_diff` and focused re-reads to confirm that the change matches the intended scope.
- Make reasonable assumptions when they are low risk, and surface them clearly in the final answer.
- When the task benefits from a saved deliverable, write it explicitly with `write_text_artifact` instead of only mentioning it in prose.
- Keep updates short and momentum-oriented; do not stall on unnecessary check-ins.
- If something is blocked, explain the blocker, the attempts you made, and the smallest next decision needed.
