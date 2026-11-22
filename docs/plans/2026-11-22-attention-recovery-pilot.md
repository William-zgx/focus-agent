# Attention Recovery Pilot: Reviewable Protocol

Status: proposed on 2026-11-22; not approved or executed.

This document defines a future small human pilot for the existing Attention
Workbench. It does not authorize recruitment, contact with participants, model
calls, telemetry collection, or product changes. No participant has been
recruited or contacted for this proposal.

## 1. Question and boundaries

Question: after an interruption, does the existing attention projection help a
user take the first correct action sooner than the raw record view, without
hiding required evidence or reducing verification accuracy?

The experiment compares projections, not agent capability. Both arms must use
the same frozen canonical state, model configuration, available actions, and
tools. The study does not rewrite the Attention Policy, Resume Packet,
Attention Diff, or low-interruption UI.

The existing 27-to-23 review-unit result is an implementation proxy. It is not
a human-attention result and must not be used as the expected effect for this
study.

## 2. Gates before any human work

### Gate A: protocol and telemetry readiness

A separate implementation authorization is required for this gate. Before any
recruitment or participant contact:

- Freeze the task fixtures, arm assignment, exclusions, metrics, and analysis.
- Replay all fixtures in a local environment with no participants.
- Validate standard Agent/model/tool telemetry against the then-current
  OpenTelemetry GenAI semantic-convention registry with Weaver live-check.
- Keep custom `focus_agent.attention.*` events outside the standard `gen_ai.*`
  namespace.
- Demonstrate that prompt text, completions, tool arguments, tool outputs,
  thread content, raw user IDs, and source-record IDs are absent from exports.
- Complete an independent privacy and correctness review.

Do not recruit if event pairing is incomplete, a required source is hidden, or
the telemetry export contains prohibited content.

### Gate B: user decision

The user decides whether recruitment and the human pilot may proceed. Gate A
completion is not approval for Gate B.

## 3. Proposed design

- Eight voluntary, informed adult participants; each completes four matched
  task pairs.
- Arm A shows the raw record review. Arm B shows the current attention
  projection. Functionality, evidence access, and available actions remain
  equivalent.
- Use frozen, matched task variants and counterbalance arm order and task
  assignment. A participant must not repeat an identical task in the other arm.
- Insert a standardized ten-minute unrelated task between the initial work and
  the return to the thread. The unrelated task must not collect personal
  content.
- Start with the six existing deterministic canonical cases as development
  fixtures. Add one case where an early decision has left the recent-message
  window and one where a tool succeeded but the final report is still pending.
  Human-study fixtures must be reviewed separately for equivalence and
  comprehensibility.
- Participation is voluntary. A participant may stop without giving a reason.
  Do not collect screen recordings, biometric data, attention tracking, or
  background device activity.

Eight participants are a feasibility pilot, not a powered efficacy study or a
PMF test.

## 4. Preregistered measurements

Primary metric:

- Time from thread entry to the first correct action.

Hard guardrails:

- Verification accuracy.
- Required-source, approval, and current-failure visibility.
- Repeated or contradictory decisions.
- Incorrect, repeated, or stale-version side effects.

Secondary metrics:

- Active reading/checking time per accepted outcome.
- Rereading amount and rollback/correction time.
- Interruptions and decisions per accepted outcome.
- Reacquisition searches and repeated tool calls.

Collect self-reported interruptibility and annoyance separately. Do not combine
them with behavioral measurements into a single attention score. Browser dwell
time alone is not a correctness or attention measure.

Report paired task-level differences, participant-level variation, descriptive
bootstrap intervals, and negative cases. Do not report only a median or mean.

## 5. Proposed decision rules

These are experiment decision thresholds, not observed Focus Agent benefits.

Proceed to a separately authorized larger study only if:

- All eight participants produce valid paired sessions.
- Standard telemetry has no Weaver violations.
- Required-source, approval, and current-failure visibility remains 100%.
- The median paired time to first correct action improves by at least 20%.
- Verification accuracy does not fall by more than five percentage points.
- No new repeated or stale-version action occurs.

Stop immediately for hidden required information, cross-participant data
exposure, an old-run side effect, forgotten data entering the study, or a
violated accuracy guardrail.

Return to diagnosis rather than expanding the sample if the time improvement
is below 20%, if fewer than six participants produce valid paired data, if
events cannot be paired, or if one participant or task dominates the estimate.
Do not add participants until a result becomes significant.

## 6. Telemetry contract

The exact standard span and attribute names must come from the pinned
OpenTelemetry semantic-convention registry at implementation time; this plan
does not invent stable names for an evolving specification.

Custom events may contain only:

| Field | Allowed value |
|---|---|
| `schema_version` | Frozen event-schema version |
| `study_id` | Public synthetic study identifier |
| `participant_key` | Random study pseudonym, never an account or user ID |
| `session_key` | Random identifier for one study session |
| `task_case_id` | Synthetic fixture identifier |
| `arm` | `raw` or `attention` |
| `presentation_id` | Random identifier for one presented snapshot |
| `event_type` | Frozen event enum, such as snapshot presented, evidence opened, or action submitted |
| `monotonic_time_ns` | Monotonic event time used for within-session ordering |
| `source_kind` | Optional coarse type only; no source ID or content |
| `client_sequence` | Monotonic sequence used to detect missing or duplicate events |

Do not record raw thread/run/user IDs, prompts, completions, tool arguments or
outputs, message text, evidence text, file paths, URLs, cookies, IP addresses,
or free-form telemetry attributes. Correctness labels belong in a separate
manual-annotation table keyed only by study pseudonym and synthetic case ID.

Pseudonyms are not anonymous identifiers. Any participant-key mapping must be
held separately by the study coordinator, never exported with telemetry, and
destroyed when withdrawal or the approved retention policy requires it.

## 7. Data handling and consent

Before Gate B, the consent material must state the study purpose, tasks,
recorded fields, retention, withdrawal mechanism, and the fact that no model
training or production monitoring is involved.

Use synthetic task content only. Do not import existing personal threads,
memory stores, emails, chats, or other user records into the human pilot.

Keep raw events and annotations in separate access-controlled local storage.
The proposed default is to delete raw event-level data 30 days after the
aggregated report is independently checked; the user must approve or change
this period before recruitment. Publish only aggregates that cannot reasonably
re-identify a participant.

No external collector, production alert integration, participant-facing
recruitment, or external data transfer is part of this proposal.

## 8. Evidence to bring back for review

If separately authorized and completed, return:

- The frozen protocol and fixture-version identifiers.
- Telemetry schema, registry version, and Weaver result.
- Privacy review and consent text version.
- Valid and excluded session counts with preregistered exclusion reasons.
- Paired results, guardrails, negative cases, and missing-event counts.
- A clear distinction between observed measurements, uncertainty, and any
  recommendation for another study.
