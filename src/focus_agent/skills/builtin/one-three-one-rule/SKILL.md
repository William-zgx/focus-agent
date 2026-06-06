---
name: one-three-one-rule
description: Structure a technical decision as one problem, three viable options, and one concrete recommendation.
triggers: one-three-one:, 1-3-1:, options:, tradeoff:
when_to_use: The user asks for a 1-3-1, A technical choice has multiple viable approaches, A proposal needs concise trade-off analysis, A recommendation should be forwardable to stakeholders
recommended_tools: search_code, read_file, web_search, web_fetch, write_text_artifact
capability_requirements: decision framing, trade-off analysis, technical communication, recommendation synthesis
prompt_mode: synthesize
---
# 1-3-1 Rule

Use this when a decision has meaningful alternatives and the user needs a crisp recommendation.

Do not use it for simple questions with one obvious answer, active debugging, or work where the user already chose the path.

## Format

1. Problem: one sentence describing the decision or outcome.
2. Options: exactly three distinct approaches labeled A, B, and C.
3. Recommendation: pick one option and state why.
4. Definition of Done: concrete outcomes that prove the recommendation worked.
5. Implementation Plan: ordered steps to execute the recommendation.

## Rules

- Options must be genuinely different strategies, not minor variants.
- Each option includes concise pros and cons.
- The Recommendation is decisive; name the trade-off you are accepting.
- If evidence is missing, state what would change the recommendation.
- If the user selects a different option, rewrite the DoD and plan for that option.

## Verification

- Exactly one Problem sentence.
- Exactly three options.
- One recommendation, not a tie.
- DoD and plan align with the recommended option.
- The response is short enough to forward without cleanup.
