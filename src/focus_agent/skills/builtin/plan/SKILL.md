---
name: plan
description: Planning-only mode for decomposing work, surfacing risks, and sequencing execution without performing it.
triggers: plan:
when_to_use: The user wants a plan first, The scope is ambiguous, The work has multiple phases or dependencies
prompt_mode: explore
---
# Plan

- Do planning work only; do not pretend the implementation already happened.
- Restate the objective, major assumptions, and the key constraints that shape the plan.
- Break the work into concrete phases with clear ordering and success criteria.
- Call out the risky or high-uncertainty steps so the user can make decisions earlier.
- Keep the plan actionable: someone should be able to execute it directly from your output.
