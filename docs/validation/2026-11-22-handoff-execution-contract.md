# Handoff Execution Contract Validation — 2026-11-22

## Scope

This slice adds canonical operation identity and execution-version projections to
ToolOutcome and Resume Packet. It does not connect Resume Packet to production
prompt assembly and does not claim durable process recovery or external
exactly-once side effects.

## Implemented contract

- `operation_fingerprint` is a full SHA-256 over canonical JSON of the tool name
  and **pre-invocation, redacted arguments**. It is not an idempotency key.
  Argument cycles/depth beyond the guard, non-JSON shapes, unknown tools, and
  `redaction_policy=none` produce no fingerprint. Tuples retain their order, as
  lists do; nested object order is canonicalized.
- The executor overwrites the fingerprint field, so tool-provided values cannot
  spoof it. Optional `operation_id`, `execution_version`, and `superseded_by`
  come only from an explicit runtime metadata allowlist, not arbitrary tool
  output or `runtime_info`.
- ToolOutcome also carries `deduplicated` and `side_effect_serialized`; the
  reverse runtime projection preserves those fields and operation metadata.
- Resume `completed_operations` includes only successful/recovered side-effect
  or explicitly identified operations. Entries are coalesced by logical
  operation/version/fingerprint, newest first, capped at 32. This prevents read
  and cache traffic from evicting a completed write while preserving its latest
  state and total distinct count.
- `ResumeExecution` appears only when an explicit execution contract provides
  `operation_id`, `execution_version`, and optional superseded versions. Missing
  producer metadata remains `None`.
- SDK and OpenAPI artifacts were regenerated and contract checks pass.

## Deterministic evidence

The targeted operation, runtime-outcome, Resume, and handoff suites total **68
passed**. The original Attention Workbench representative suite remains at its
previous **27→23** review-unit result; completed-operation projection does not
inflate that metric.

Covered regressions include:

- nested ordering, tuples, cycles, deep nesting, wide argument lists, non-JSON
  arguments, NaN and infinity, redaction-policy opt-out, and in-place tool
  argument mutation;
- restricted metadata supplied by a tool or `runtime_info` being rejected, with
  only declared runtime metadata accepted;
- recovered/deduplicated executions retaining their flags and side-effect state;
- newest logical completion coalescing, total counts, and no duplicate evidence
  fanout;
- NULL execution metadata, overlong identifiers being rejected instead of
  silently truncated, and string `false` no longer becoming `true` in Resume.

## Provider comparison

The same three synthetic cases and four arms used for the earlier diagnostic
were rerun with the new contracts:

| Model | recent (negative control) | ideal narrative | Resume Packet | full history |
|---|---:|---:|---:|---:|
| DeepSeek V4.1 Flash | 0/3 | 3/3 | **3/3** | 3/3 |
| Kimi K3.1 Pro | 0/3 | 3/3 | **3/3** | 2/3 |

Earlier Resume results were **1/3 for both models**. The completed-operation and
execution-version cases now have the required canonical state, rather than a
correct-looking answer being marked as an ungrounded guess.

Provider evidence boundary:

- DeepSeek had one timeout in the recent negative-control arm.
- Kimi had one upstream `429` in the full-history superseded-version arm.
- No provider error is counted as a behavioral success, and no significance or
  production-quality claim is made from three one-run cases.
- Narrative remains an ideal hand-written upper bound, recent remains a negative
  control, and full history is not assumed infallible.

## Remaining boundaries

- Resume Packet is still an eval-only prompt projection, not a production prompt
  integration or a side-effect fence.
- Declared runtime metadata is optional; ordinary executions without an explicit
  producer continue to return `None` for business operation/version fields.
- The real Postgres lease/restart test is a separate next slice and is not
  claimed here.
- Operation fingerprint is not a secret-management mechanism or an idempotency
  guarantee. Consumers must use the authoritative operation/version records for
  duplicate prevention.
- No human recovery-pilot recruitment, contact, or data collection is included.
