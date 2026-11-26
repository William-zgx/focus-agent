# Artifact Evidence Gate Validation — 2026-11-26

## Scope

This change strengthens the real-provider `context_ui_smoke.py` acceptance gate.
It does not change model routing, global prompts, or production answer behavior.
Model-authored text is never accepted as file or artifact evidence by itself.

## Test-first regression

New deterministic coverage is in `tests/test_context_ui_smoke_evidence.py`.
Before the assertion helpers were implemented, the initial seven tests failed.
Kimi prefilter then identified a substring false pass (`300` matching `3000`),
and Opus follow-up found default-argument and response-claim edge cases; their
regressions also failed before the respective fixes. Final results:

- `tests/test_context_ui_smoke_evidence.py`: **12 passed**.
- That file plus `tests/test_ui_smoke_script.py`: **15 passed**.
- Ruff lint/format and direct script `--help`: passed.

The checks require:

- an exact `read_file` call (including the tool's default `start_line=1`) and a
  successful matching tool result whose `total_lines` supports a line-count-specific
  response claim, rejecting both `3000` and a range mention paired with a
  contradictory count; the returned artifact reference uses the verified call;
- an exact `artifact_read` call with the requested artifact ID, offset, and
  limit;
- a successful matching artifact result containing the required marker;
- a final response supported by that tool result;
- specific errors for a missing call, unsuccessful result, unsupported tool
  content, or unsupported final response.

Evidence assertions now run **before** a step can be recorded as passed. An
evidence failure records the complete failed step, including model state and
`evidence_error`, before the overall report fails.

## Real Kimi evidence boundary

The 2026-11-25 isolated real-Kimi runs used
`superrelay/kimi-k3.1-pro-1m` and failed the artifact scenario twice: the model
made no `artifact_read` call and fabricated `VF-BRIDGE-341` and `445886`.
Those runs remain valid negative evidence, not passes. Their original reports
are under `/tmp/focus-agent-kimi-validation-20261125-9nv1wlp_/`.

On 2026-11-26, the strengthened gate again passed the real first-turn
`read_file` evidence check in two fresh attempts. Both second attempts stopped
with upstream `ratelimited`; these are provider errors, not behavioral passes or
failures, and no new model-compliance claim is made from them. Evidence is under
`/tmp/focus-agent-artifact-gate-20261126-x16n_tpn/`.

The previously accepted 2580-test local baseline was not rerun for this scoped
script change. Required PR checks remain merge gates. No human pilot, external
announcement, or global model change is included.
