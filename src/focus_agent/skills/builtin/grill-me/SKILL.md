---
name: grill-me
description: Stress-test a plan or design by interviewing the user one decision at a time until shared understanding is reached.
triggers: grill:, grill-me:, stress-test-plan:
when_to_use: The user wants to stress-test a plan before building, A design has unresolved product decisions, Ambiguous requirements need decision ownership
recommended_tools: ask_user_question, list_files, workspace_tree, search_code, read_file, web_search, web_fetch
aliases: grilling, grill
prompt_mode: explore
---

# Grill Me

Interview the user relentlessly about the plan or design until you share a clear understanding. Walk down each branch of the design tree and resolve dependencies between decisions one by one.

## Rules

1. **One question at a time.** Prefer `ask_user_question` with a single structured question when options are clear; otherwise ask in prose and wait. Multiple independent decisions in one form is fine only when they are truly parallel and non-dependent.
2. **Recommend an answer every time.** For each question, state your recommended choice and a one-line reason (in the option description or prose), then wait for the user.
3. **Facts vs decisions.**
   - If a *fact* can be found in the workspace or public docs, look it up with tools (`list_files`, `workspace_tree`, `search_code`, `read_file`, `web_search`, `web_fetch`) instead of asking the user.
   - *Decisions* (product tradeoffs, risk tolerance, scope cuts) belong to the user — put each one to them and wait.
4. **Stay in interview mode.** Do not implement, write patches, or pretend the plan is already approved.
5. **Stop only on confirmation.** Do not enact the plan until the user explicitly confirms shared understanding.

## Good question shape

- What decision is blocked?
- What are 2–4 mutually exclusive options?
- Which option do you recommend and why?
- What fact would change the recommendation?

## Exit

When the user confirms shared understanding, summarize:

- agreed decisions
- remaining open questions (if any)
- recommended next step (plan artifact, implementation, or another skill such as `writing-plans`)
