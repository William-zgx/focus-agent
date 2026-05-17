# AGENTS.md

Repository-level instructions for agents working in this tree.

Bias: cautious over fast, verifiable over speculative.

## Scope And Priority

- This file applies to the entire repository unless a deeper `AGENTS.md` overrides it.
- Follow system, developer, and user instructions first when they conflict with this file.
- Preserve existing repository conventions, architecture, dependencies, and style.

## Design Philosophy

- Simplicity first: make only the necessary change and avoid over-engineering.
- Root-cause oriented: fix the underlying cause, not only the visible symptom.
- Minimal impact: keep the change scoped to the relevant behavior and avoid breaking existing functionality.

## Workflow

Use `Plan -> Execute -> Verify -> Learn`.

| Step | Expectations |
|------|--------------|
| Plan | Clarify goals, constraints, assumptions, and the smallest verifiable path. Ask when uncertainty would make the change risky. |
| Execute | Make focused changes step by step. Maintain existing style, dependencies, and architecture. |
| Verify | Tie every change to an automated test, build, lint, or a clear manual check. Prefer automated tests when practical. |
| Learn | Note edge cases, repeated pitfalls, or process lessons in the final summary or in the appropriate project documentation when requested. |

## Delegation And Parallel Work

- Before executing any non-trivial task, first ask: can this be split into independent investigation, implementation, review, or verification slices?
- When the active runtime supports Codex native subagents and independent slices exist, prefer a multi-agent workflow by default.
- When subagent tools are available, use parallel subagents for any task with independent investigation, implementation, or verification slices unless doing so would create write conflicts or block the critical path.
- Use solo execution only when the task is trivial, tightly coupled, sequentially blocked, or when delegation would add overhead without improving speed, quality, or safety.
- Treat tasks as strong multi-agent candidates when they involve multiple files or modules, investigation plus implementation, frontend or browser verification, review or regression testing, conflict resolution, docs plus code, or long-running validation.
- When the user explicitly asks for multi-agent work, multiple agents, delegation, subagents, or concurrent agent execution, use subagents where practical and safe.
- Keep the lead agent responsible for planning, user alignment, shared state, integration, conflict resolution, final verification, and the final response.
- Delegate only concrete, bounded, independent slices with clear ownership and expected output. Prefer read-only exploration, isolated implementation areas, review, and verification slices.
- Do not delegate tightly coupled critical-path work, ambiguous product decisions, or overlapping write scopes that would create coordination risk.
- If subagents are unavailable or blocked by higher-priority instructions, fall back to concurrent local tool calls for independent read-only discovery and verification.
- If a non-trivial task does not use subagents, state the reason briefly in the final response, such as higher-priority policy, missing tool support, task size, unsafe coupling, overlapping write scope, or no independent slice worth delegating.
- Synchronize at critical steps so shared state, assumptions, and outputs stay consistent.

## Code Quality

- Minimal code: implement only what is required for the task.
- Consistency: follow local naming, formatting, testing, and architectural patterns.
- Verifiable behavior: prefer checks that produce repeatable, reviewable output.
- Maintainability: add comments only where they explain non-obvious intent or complexity.
- Surgical changes: modify only relevant files, clean up temporary artifacts, and do not touch unrelated legacy code.

## Git

- Use task-level branches for commit workflows when branch changes are requested or appropriate.
- Keep commits small, focused, and directly tied to the change.
- Do not combine unrelated changes in one commit.
- Do not overwrite or revert unrelated user changes.
- Merge only after the relevant verification has passed or after explicitly documenting any verification gap.

## Output

- Keep responses, logs, and documentation clear, structured, and reusable.
- Include enough information for the result to be checked manually or automatically.
- Avoid duplicate or redundant detail.
- State relevant dependencies, inputs, preconditions, and assumptions.

## Example Execution Pattern

Task: fix a boundary error in function `X`.

| Step | Verification |
|------|--------------|
| Add tests covering boundary values | Tests fail before the fix. |
| Fix function `X` | Tests pass after the fix. |
| Clean up temporary variables or debug code | No residual artifacts remain. |
| Commit the change when requested | Commit message clearly describes the fix. |
