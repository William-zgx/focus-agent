# Attention Workbench

Status: implemented for the server-backed Web path, 2026-11-14.

This document defines the first complete attention-centric product slice. It combines
adaptive interruption with resumable branches; it does not claim that token savings,
short summaries, or fewer confirmations prove reduced human attention cost.

## 1. Product invariant

Focus Agent should spend user attention only when user judgment can change the
outcome. Routine execution remains available for audit but does not compete with
the current goal. Returning to work must not require reconstructing it from a raw
transcript.

The primary evaluation quantity is **verified progress per unit of active user
attention**, measured through paired tasks rather than a global synthetic score.
Task quality, safety, evidence access, and verification accuracy are guardrails.

The existing branch-routing **Focus Score** remains a branch recommendation
signal. It is not a human-attention metric.

## 2. First delivered scope

1. **Deterministic Attention Policy**
   - `quiet`: ordinary running/success states; no additional interruption.
   - `notify`: a current failure, degraded result, or unknown outcome deserves review.
   - `ask`: a pending Branch Action, interrupt, approval, or merge decision can
     be acted on now.
   - Reasons and source IDs are returned with the policy. Failure and actionable
     states cannot be suppressed by the low-interruption presentation.
   - Rules are application-owned and deterministic. No LLM controller, learned
     autonomy, OS push notification, or automatic approval is introduced.

2. **Resume Packet**
   - Goal from the branch brief, durable active goal/task brief, or earliest
     retained user message. A long-thread payload may not contain the original
     root message, so the fallback is not presented as that original message.
   - Decisions only from authoritative executed/approved records, never inferred
     from assistant prose.
   - Open items from pending actions, interrupts, and current failure states.
   - Next action with a stable source ID where one exists.
   - Evidence references back to the owning thread/action/run. Fields that cannot
     be derived reliably remain empty.

3. **Attention Diff**
   - A persisted per-principal, per-thread cursor records the reviewed message
     frontier, tool outcomes, and Branch Action statuses.
   - Reading the snapshot has no side effects. An explicit reviewed action moves
     the cursor only to the frontier that was actually presented to the user.
   - First visits and missing frontiers are identified honestly; neither produces
     a fabricated diff.
   - New messages, completed/failed outcomes, and action status transitions are
     counted independently. No unvalidated "attention saved" estimate is shown.

4. **Low-interruption Web projection**
   - Routine branch-routing diagnostics can be hidden without removing their
     audit data.
   - Pending decisions and failures remain visible and are aggregated in one
     resume/attention surface.
   - The resume surface appears on thread entry only when it contains useful
     context, changes, or actionable work; it is not another always-visible feed.

## 3. Data and trust boundaries

- Canonical thread messages, branch metadata, Branch Actions, merge state,
  interrupts, task/tool outcomes, and run records are the only sources.
- Assistant prose and rolling summaries are not treated as user decisions.
- Cursor state uses the existing LangGraph store under an attention-specific
  tenant/user/thread namespace with non-empty escaped labels, so missing tenants
  and IDs containing periods or slashes remain valid and isolated. No database
  migration is required.
- Every read and cursor update uses the authenticated principal and the existing
  thread ownership path. One principal cannot read or advance another principal's
  cursor.
- Attention endpoints perform no model calls and add no background jobs. The
  canonical thread read used for ownership and projection may backfill imported
  records, as it did before this feature; the attention cursor itself is only
  changed by the explicit reviewed action.
- Cursor and highlight payloads are bounded. Raw tool arguments and chain-of-thought
  are not copied into the attention surface.

## 4. API contract

The Web path uses a thread-scoped attention resource:

- `GET /v1/threads/{thread_id}/attention`
  returns policy, resume packet, diff, and a versioned current cursor.
- `POST /v1/threads/{thread_id}/attention/reviewed`
  accepts the cursor from the snapshot that was actually presented, validates its
  message/outcome/action IDs against current canonical state, stores that
  presented frontier, and returns it.

The GET is read-only except for the canonical thread backfill noted above. POST
is idempotent for an unchanged presented cursor. Work arriving after that
snapshot remains unread and appears in the next diff. A stale frontier that no
longer exists is rejected with `409` instead of silently losing review history.
The server never advances a review past work the client has not presented.
Concurrent reviews are serialized within one API process; this is not a claim of
distributed exactly-once behavior across independent workers.

## 5. Presentation rules

- The default Web presentation is low interruption, with a user-controlled switch
  to reveal routine diagnostics.
- The attention surface is not shown for a quiet root thread with no resume value.
- `ask` outranks `notify`, which outranks `quiet`.
- Historical tool failures remain diff evidence but do not create a current alert
  after the turn has recovered or completed successfully.
- A dismissed/resumed surface can be reopened without losing the underlying audit
  history.
- English and Chinese labels share stable policy/reason codes; localization does
  not change policy behavior.

## 6. Acceptance and evaluation

### Functional acceptance

- Ordinary progress creates no new interruption.
- Pending actions and current failures remain visible in low-interruption mode.
- A first visit reports no fabricated changes.
- Reviewing a snapshot clears its diff; subsequent changes appear exactly once.
- Cursor state survives an API restart and is isolated by principal and thread.
- Resume goal, open items, and next action match canonical records.
- Existing stream, branch, merge, approval, and SDK contracts remain compatible.

### Paired product experiment

Compare the existing projection with the attention projection on the same tasks,
models, tools, and initial state. Report separately:

- active reading/checking time per accepted outcome;
- interruptions and decisions per accepted outcome;
- time from thread entry to the first correct action;
- re-read amount and repeated/contradictory decisions;
- rollback/correction time and verification accuracy.

Browser dwell time is only a proxy and must be calibrated with a small human
study. A shorter review with worse correctness is a failure, not a win.

### Offline paired projection evaluation

`python -m tests.eval.test_attention_workbench_suite` replays canonical states
through the real attention projection and compares them with raw record review
units. The current six-case report reduces review units from 27 to 23 (14.8%)
while retaining policy and evidence visibility for all three required sources.
The resumed-branch case has a negative reduction and remains in the report.

These are deterministic implementation proxies, not human-attention or task
quality measurements. They guard against hidden failures and fabricated diffs;
they do not replace the paired human study described above.

## 7. Explicit non-goals for this slice

- No learned attention model or LLM-selected notification policy.
- No silent branch creation, automatic merge, or automatic approval.
- No claim that a branch snapshots the filesystem or external side effects.
- No OS notification, cross-device push, or cognitive-attention surveillance.
- The server-backed Web path is delivered first. Android local-runtime clients
  without the attention routes keep their existing thread experience and do not
  display a misleading resume error or a second, divergent local policy.
- No replacement orchestration platform, new agent role, or MCTS/search runtime.
- No single Focus Score claiming to measure human attention.

## 8. Implementation and validation

- `src/focus_agent/core/attention.py` defines the versioned public contract.
- `src/focus_agent/services/attention.py` projects canonical thread state and
  merges review cursors without moving them backwards.
- `src/focus_agent/api/routers/attention.py` provides the ownership-checked GET
  and presented-cursor review endpoints.
- `frontend-sdk/src/types/attention.ts` and the thread client expose the typed
  Web contract.
- `apps/web/src/features/attention/` provides the low-interruption resume view.
- `tests/unit/attention/` covers policy precedence, cursor persistence, missing
  frontiers, presented-snapshot review, out-of-order reviews, ownership, and
  SQLite restart behavior.
- `src/focus_agent/eval/attention.py` and
  `tests/eval/test_attention_workbench_suite.py` provide the repeatable offline
  paired projection evaluation and its review-unit/recall guardrails.
- Validation includes the full Python suite, frontend stream regressions,
  OpenAPI/SDK contract checks, Web typecheck/build, CSS and architecture gates,
  and a real isolated Chromium flow covering root resume, new-work diff,
  presented-cursor review, actionable policy, evidence navigation, branch resume,
  and API restart.

The dated evidence report is [2026-11-15-attention-workbench.md](validation/2026-11-15-attention-workbench.md).

## 9. External design evidence

- Leroy and Glomb, ready-to-resume plans and attention residue:
  https://pubsonline.informs.org/doi/10.1287/orsc.2017.1184
- Altmann and Trafton, resumption lag and cues:
  https://escholarship.org/uc/item/18b4r661
- Confirmation frequency and its confirmation/rollback trade-off:
  https://arxiv.org/html/2510.05307v4
- Oversight interfaces can raise confidence without matching accuracy gains:
  https://arxiv.org/html/2602.16844v1
- OpenHands compact activity and actionable notifications:
  https://docs.openhands.dev/openhands/usage/agent-canvas/conversations
- LangGraph event projections and durable interrupts:
  https://docs.langchain.com/oss/python/langgraph/event-streaming
  https://docs.langchain.com/oss/python/langgraph/interrupts
- OpenHands event-sourced persistence and forks:
  https://docs.openhands.dev/sdk/guides/convo-persistence
  https://docs.openhands.dev/sdk/guides/convo-fork
