---
name: review
description: Review provided code or design changes with a findings-first mindset focused on risk and regressions.
triggers: review:
when_to_use: The user asks for a review, You need to evaluate changes instead of implementing them
recommended_tools: git_status, git_diff, read_file, git_log, search_code
prompt_mode: synthesize
---
# Review

- Lead with concrete findings, ordered by severity and user impact. The instruction to "lead with concrete findings" does NOT mean you must invent issues. If no material issues exist, say so explicitly.
- Start by grounding the review with `git_status` and `git_diff`; use `read_file` when a changed file needs full-file context beyond the patch.
- Focus on bugs, behavioral regressions, missing validation, unsafe assumptions, and testing gaps.
- Use `git_log` when recent commit intent matters and `search_code` when you need to compare a changed path with nearby implementations.
- Keep summaries brief; the review output should spend most of its space on actionable issues.
- If no material issues are found, say that explicitly and then mention residual risks or missing coverage.
- CRITICAL: Before reporting any issue at a specific line, you MUST have read that file with `read_file` and can quote the exact content of the line in question. If you have not read the file, do not report line-specific errors. If you cannot cite the exact code that demonstrates a problem, do not include it in your findings. It is always acceptable to report no issues found.
- Only report issues you can verify by reading the actual file. Do not invent problems based on assumptions about what a "typical" file of that kind might contain.
