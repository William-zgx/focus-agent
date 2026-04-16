---
name: tdd
description: Drive implementation through tests first, then make the smallest change that turns the suite green.
triggers: tdd:
when_to_use: The task changes behavior, Regression protection matters, The user explicitly asks for TDD
recommended_tools: list_files, search_code, read_file, git_status, git_diff, write_text_artifact
prompt_mode: execute
---
# TDD

- Start by defining or updating the test that proves the intended behavior.
- Use `list_files`, `search_code`, and `read_file` first to find the existing test module, the target implementation, and any nearby examples you can mirror.
- Make the failure explicit before describing or applying the implementation fix.
- If the request touches existing work, inspect `git_status` and `git_diff` first so the new test fits the actual patch context.
- Prefer the smallest production change that satisfies the new or updated test.
- When the change introduces a useful artifact such as a rollout note or failure summary, save it with `write_text_artifact` instead of leaving it only in free-form text.
- After the behavior passes, look for low-risk cleanup that improves clarity without changing semantics.
- If a test harness is unavailable, say what test you would add and why before proceeding.
