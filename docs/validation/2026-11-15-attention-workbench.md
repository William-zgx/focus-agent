# Attention Workbench Validation — 2026-11-15

## Scope

Implemented for the server-backed Web path on `feat/attention-workbench`.
No commit or remote merge is implied by this report.

Delivered:

- deterministic `quiet` / `notify` / `ask` policy with source reasons;
- low-interruption Web projection that preserves failures, timeouts, approvals,
  and evidence access;
- Resume Packet with goal, authoritative decisions, open items, next action, and
  evidence;
- Attention Diff with tenant/user/thread-scoped persistent cursors;
- presented-snapshot review, monotonic out-of-order merging, conflict recovery,
  and API-restart persistence;
- typed SDK/OpenAPI contracts and Android local-runtime capability fallback.

Canonical design: `docs/attention-workbench.md`.

## Automated verification

- Full Python suite: **2495 passed, 11 skipped**.
- Frontend stream/state regressions: **70 passed**.
- Attention service/API tests: **15 passed**.
- Offline attention projection evaluation: **17 passed**.
- Web and SDK typechecks, Web production build, CSS governance, architecture,
  and API/SDK contract checks passed.
- Android local-runtime smoke passed.
- Final correctness and simplify reviews: clean.

`make ci` completed its Python/Ruff/architecture/compat/SDK stages but did not
finish green: `web:format:check:full` still rejects the unchanged pre-existing
`apps/web/src/pages/auth/login-intro.tsx` formatting. The full frontend lint also
reports three unused variables and one pre-existing CSS specificity warning.
These files were not rewritten to hide that unrelated boundary in this feature
branch.

## Real isolated Chromium acceptance

The isolated fixture-backed run used separate model, data, API, and browser
processes. It verified:

1. root-thread goal resume and explicit review;
2. new-message Diff after review;
3. presented-cursor review while newer work arrives concurrently;
4. actionable policy and evidence navigation;
5. branch Resume Packet after a terminal handoff run;
6. attention cursor persistence after API restart;
7. no browser errors.

Evidence: `/tmp/focus-agent-attention-smoke-1b_h9mr1/result.json` and screenshots
in the same temporary directory. The screenshot review confirmed that the goal,
actionable item, evidence control, and branch response were visible and that no
empty resume overlay or perpetual processing state remained.

## Offline paired projection report

Command:

```bash
.venv/bin/python -m tests.eval.test_attention_workbench_suite
```

Current result:

| Metric | Value |
|---|---:|
| Cases | 6 |
| Baseline review units | 27 |
| Attention review units | 23 |
| Review-unit reduction | 14.8% |
| Required sources | 3 |
| Sources retaining policy visibility | 3 |
| Sources retaining evidence access | 3 |
| Suite result | pass |

The resumed-branch case has a **negative** reduction and remains in the report.
Ordinary success and recovered-history cases have larger reductions; failure and
pending-action cases do not force a reduction at the expense of visibility.
Additional negative tests reject `ask`/`notify` without canonically required
sources, required work hidden behind `quiet`, cross-kind evidence/reason ID
collisions, and an empty suite. Parameterized cases verify nested `values`,
ID-keyed record mappings, `__interrupt__`, ID-less actions, and case-insensitive
merge states against the production normalization helpers.

### Metric boundary

Review units are deterministic implementation proxies based on canonical record
counts. They are not human attention, reading time, task quality, or proof of PMF.
The evaluation reuses the production snapshot builder but independently computes
required sources from canonical state to avoid policy self-validation.

## Remaining evidence required before attention claims

- A paired human study measuring time to first correct action after an
  interruption, active reading/checking time, repeated decisions, rollback time,
  and verification accuracy.
- Real-use segmentation by task type, branch depth, run duration, and user
  preference; no single global attention score.
- Long-running real-provider behavior and multi-device cursor behavior. Existing
  tests establish single-process monotonic merging, not a distributed transaction
  or exactly-once guarantee across independent API workers.
- Android local-runtime attention support is not implemented; those clients keep
  their existing thread experience rather than a second divergent policy.
