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

- Run independent read-only discovery and verification tasks concurrently when the tooling supports it.
- Delegate work only when allowed by higher-priority instructions and when the task is concrete, bounded, and independent.
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
