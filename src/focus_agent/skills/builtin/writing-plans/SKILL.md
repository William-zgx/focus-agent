---
name: writing-plans
description: Turn a feature request or spec into an implementation plan with exact files, ordered tasks, validation steps, and explicit risks.
triggers: write-plan:, implementation-plan:
when_to_use: The work is multi-step, A design or execution plan is needed before coding, The task should be decomposed into precise implementation steps
prompt_mode: explore
---

# Writing Plans

Write plans that another engineer could execute without guessing.

## Workflow

1. Restate the objective, assumptions, and constraints.
2. Inspect the current repository structure with `list_files`, `search_code`, and `read_file` before proposing file changes.
3. Break the work into ordered tasks with clear success criteria.
4. Name the exact files, commands, and tests involved.
5. Call out risks, decision points, and dependencies early.

## Good Plan Shape

- objective and scope
- current-state observations
- implementation phases
- task list with exact paths
- verification commands
- rollout or migration notes if behavior changes

## Granularity

Prefer tasks that are small enough to review and verify independently. A good task usually maps to one concrete edit plus one concrete check.

## Plan Quality Bar

- no hand-wavy "update the config" language when a file path is knowable
- no pretending implementation already happened
- no missing verification step for behavior changes
- no unexamined dependency or migration risk

## Output

Return a plan that is ready to execute directly. If the user only asked for planning, stop at the plan and do not implement.
