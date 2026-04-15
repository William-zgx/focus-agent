---
name: review
description: Review provided code or design changes with a findings-first mindset focused on risk and regressions.
triggers: review:
when_to_use: The user asks for a review, You need to evaluate changes instead of implementing them
prompt_mode: synthesize
---
# Review

- Lead with concrete findings, ordered by severity and user impact.
- Start by grounding the review with `git_status` and `git_diff`; use `read_file` when a changed file needs full-file context beyond the patch.
- Focus on bugs, behavioral regressions, missing validation, unsafe assumptions, and testing gaps.
- Use `git_log` when recent commit intent matters and `search_code` when you need to compare a changed path with nearby implementations.
- Keep summaries brief; the review output should spend most of its space on actionable issues.
- If no material issues are found, say that explicitly and then mention residual risks or missing coverage.
- Stay evidence-based: do not invent problems that are not supported by the provided context.
