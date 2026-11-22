# Continuity Diagnostics Validation — 2026-11-22

## Scope and authorization

This validation covers synthetic, non-human handoff and Memory diagnostics. No
participants were recruited or contacted, no personal threads were used, and no
human attention claim is made. The human recovery-pilot document is a proposal
only.

Design and reproduction commands: [../eval/continuity-diagnostics.md](../eval/continuity-diagnostics.md).

## Local verification

- Branch: `feat/handoff-memory-diagnostics` against main `9911ae5`.
- Complete `make ci`: **2540 passed, 11 skipped**, plus frontend lint/format,
  TypeScript, SDK/Web builds, API/SDK contracts, architecture and compatibility
  gates.
- Deterministic Eval workflow selection, including the two new continuity
  suites, passed locally.
- Strict Ruff lint and `git diff --check` passed.

## Memory layered results

Synthetic probes cover three replacements of one explicit decision identity,
forgotten records with a stale retrieval index, cross-owner/root injection,
legacy tombstone hydration, malformed observations, and an explicit new
assertion after forget. The final suite passes with:

- only the newest decision active and present in scoped use;
- no forgotten ID selected or rendered;
- no foreign owner/root ID or marker selected or rendered;
- a new post-forget assertion reported under a new ID, distinct from old-ID
  resurrection;
- active legacy controls retained while invalid or forgotten records are
  skipped before top-k selection.

The initial failing tests confirmed the semantic-key, legacy hydration, and
scoped-owner defects before their fixes. Additional review regressions confirmed
deleted-at rendering, foreign namespace fallback, top-k starvation, malformed
tombstones, scoped-use false green, and reasoning-block answer contamination.

## Final provider matrix

Each cell is one synthetic run. `passed` additionally requires the necessary
state to be present, so a correct-looking guess cannot hide a Resume Packet
contract gap. The narrative is an ideal hand-written upper bound, recent is a
negative control by construction, and the Resume outcomes primarily expose
missing source contracts rather than scoring model quality. These per-arm
results are not aggregate release-gate metrics.

| Model | recent | narrative | Resume Packet | full history | Provider errors |
|---|---:|---:|---:|---:|---:|
| DeepSeek V4.1 Flash | 0/3 | 3/3 | 1/3 | 3/3 | 0 |
| Kimi K3.1 Pro | 0/3 | 3/3 | 1/3 | 2/3 | 1 timeout |

Detailed findings:

- Both models passed all three narrative cases without repeated, stale, or
  superseded-version attempts.
- Both Resume Packet arms passed only the current-decision case. The completed
  operation and execution-version cases lack required canonical state.
- Kimi repeated the completed operation once even with full history. Full
  history is therefore a reference arm, not an infallible oracle.
- DeepSeek produced no repeated/stale/superseded effect in the final matrix.
- Kimi's superseded-version Resume arm timed out after 240 seconds. The original
  failure is retained. A separate single retry completed without a provider
  error, but still failed the required-state check; it does not replace the
  original result or turn the Resume contract gap into a pass.
- Kimi uses the provider-required `temperature=1`; DeepSeek used the explicit
  CLI default `temperature=0`. Comparisons are within each model, not a claim
  that the two model configurations are equivalent.

These are three diagnostic cases with one run per cell. They do not establish
statistical significance, production task-quality improvements, or human
attention savings.

## Process-isolated continuation

For the completed-operation case, every arm was also launched as a separate
Python process. This checks fresh-process continuation rather than relying on a
single process's runtime state. It is not a durable checkpoint-restart test.

DeepSeek process-isolated results matched its same-process arm outcomes:

| Arm | Result | Required-state result |
|---|---|---|
| recent | failed | operation/version/status markers missing |
| narrative | passed | complete |
| Resume Packet | failed | operation/version/status markers missing |
| full history | passed | complete |

Kimi process-isolated results also matched its same-process outcomes, including
a second observed repetition of the completed operation under full history:

| Arm | Result | Required-state / behavior result |
|---|---|---|
| recent | failed | operation/version/status markers missing |
| narrative | passed | complete |
| Resume Packet | failed | operation/version/status markers missing |
| full history | failed | one repeated completed-operation attempt |

The Kimi full-history repetition was therefore observed in both the main matrix
and the separate-process run. This remains a two-run diagnostic observation, not
a rate estimate.

## Remaining boundaries and next work

- Resume Packet is not currently injected into production agent context. The
  suite renders it only for controlled comparison.
- A canonical completed-operation/argument identity and execution-version
  contract is still absent. Raw tool arguments or outputs must not be copied
  into Resume Packet as a shortcut.
- Brand-new keyless writes after an explicitly keyed record remain outside the
  three-update regression; no new content-based repository lookup is claimed.
- Process-isolated continuation is not persistent checkpoint recovery. A real
  restart/lease/revision test requires a separate implementation and gate.
- The human pilot remains unapproved and unexecuted. Its protocol, telemetry
  allowlist, privacy boundaries, and two authorization gates are documented in
  [../plans/2026-11-22-attention-recovery-pilot.md](../plans/2026-11-22-attention-recovery-pilot.md).
