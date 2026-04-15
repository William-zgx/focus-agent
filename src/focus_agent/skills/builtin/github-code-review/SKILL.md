---
name: github-code-review
description: Review local changes or GitHub pull requests with a findings-first workflow grounded in git diff, targeted validation, and clear severity-based feedback.
triggers: gh-review:, pr-review:
when_to_use: A pull request needs review, Local git changes should be reviewed before push, GitHub-hosted code review is the task
prompt_mode: synthesize
---

# GitHub Code Review

Use the simplest review surface that fits the task.

## Local Review First

When the user wants a review of current work, prefer the local repository tools:

- `git_status` for branch and changed-file overview
- `git_diff` for the patch itself
- `git_log` for recent commit context
- `read_file` when a changed file needs full-file review beyond the diff

Read changed files in full when the diff is not enough, then run the smallest useful tests or lint checks if execution tools are available.

## PR Review

If the user explicitly references a GitHub PR but only local repository tools are available, review the local patch that corresponds to that work or explain the exact blocker.

## Review Standard

Lead with findings and prioritize:

1. correctness or regression risk
2. security or data-safety issues
3. missing validation or missing tests
4. maintainability problems that are likely to cause future bugs

## Output

- findings first, ordered by severity
- file and line references when possible
- brief summary only after the findings

If no material issue is found, say that explicitly and mention residual risks or test gaps.
