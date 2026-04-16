---
name: ralph
description: Apply maximum persistence, retry strategy changes, and deeper debugging before giving up.
triggers: ralph:
when_to_use: The problem is stubborn, Previous attempts failed, The user wants maximum effort before escalation
recommended_tools: git_status, git_diff, search_code, read_file, git_log
prompt_mode: execute
---
# Ralph

- Stay persistent and keep searching for another viable angle when the first attempt fails.
- Retry intelligently: change the hypothesis, inputs, or approach instead of repeating the same failed step.
- Use the repository tools as your evidence loop: `git_status` / `git_diff` for recent changes, `search_code` / `read_file` for code path inspection, and `git_log` when you need to understand how the code reached its current state.
- Preserve a clear chain of reasoning about what was ruled out and what remains plausible.
- Escalate only after meaningful attempts, and summarize the exact blocker with the evidence you gathered.
- When you finally resolve the issue, explain the decisive insight, not just the final state.
