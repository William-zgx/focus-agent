---
name: systematic-debugging
description: Investigate bugs and failing tests in a disciplined order: reproduce, isolate, compare, then fix the root cause.
triggers: debug:, systematic-debugging:
when_to_use: A bug or failing test needs root-cause analysis, Quick patches are tempting but risky, The issue has resisted a first attempt
recommended_tools: git_status, git_diff, git_log, search_code, read_file
prompt_mode: execute
---

# Systematic Debugging

Do not guess. Establish the cause before changing code.

## Phase 1: Reproduce

- read the full error or failing behavior carefully
- run the smallest command that reproduces it
- capture the exact files, inputs, and environment involved

## Phase 2: Isolate

- inspect recent changes with `git_status`, `git_diff`, and `git_log`
- trace the failing code path with `search_code`, targeted `read_file` calls, and logs
- identify where the bad state first appears

## Phase 3: Compare

- find nearby code or tests that already work
- compare working and broken paths for missing setup, assumptions, or invariants
- write down a single concrete hypothesis before editing

## Phase 4: Fix and Verify

- add or update the regression test first when feasible
- make the smallest change that addresses the root cause
- rerun the focused reproduction, then the relevant broader checks

## Rules

- one hypothesis at a time
- no stack of speculative fixes
- if the root cause is still unclear, keep gathering evidence instead of patching symptoms

## Output

Explain:

- what was failing
- what the root cause was
- how it was verified
- any remaining uncertainty or follow-up risk
