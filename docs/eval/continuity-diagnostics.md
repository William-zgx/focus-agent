# Handoff And Memory Continuity Diagnostics

Status: implemented for synthetic, non-human evaluation on 2026-11-22.

Validation evidence: [2026-11-22-continuity-diagnostics.md](../validation/2026-11-22-continuity-diagnostics.md).

These diagnostics test information continuity after a handoff. They do not
recruit participants, import personal threads, or measure human attention.
Provider-backed results are exploratory measurements, not product-quality or
statistical-superiority claims.

## 1. Four-arm handoff comparison

`src/focus_agent/eval/handoff.py` derives every arm from one synthetic episode:

| Arm | Raw messages | `rolling_summary` |
|---|---|---|
| `recent` | Recent complete-turn window | Empty |
| `narrative` | Same recent window | Ideal hand-written narrative written from the same episode |
| `resume_packet` | Same recent window | JSON rendering of the production `build_attention_snapshot(...).resume` |
| `full_history` | Complete episode, subject to explicit size guards | Empty |

The narrative is an idealized upper bound, not a measurement of generated-summary
quality. The recent arm is a negative control whose small window deliberately
retains only filler context, so its 0/3 outcome is by design. Resume failures
primarily identify missing source contracts; they are not a model-quality score.
The aggregate CLI result is therefore diagnostic and exits nonzero for these
expected failures; it is not a release-gate metric.

The Resume Packet arm is an **eval-only information projection**. Production
prompt assembly does not currently inject Resume Packet into agent context;
this suite must not be cited as evidence that such integration works.

Each case is one resumed turn. `initial_state.messages` includes the final user
continuation because the generic eval runner replaces, rather than appends to,
the default message list. No `case.setup` history or checkpoint persistence is
assumed. Context engineering v2 is disabled for the provider CLI, and no
`context_compaction` value is seeded.

The full-history arm fails loudly when count or token limits would truncate the
seeded episode. The suite records raw-message and model-prompt sizes so context
length remains a visible confound.

## 2. Synthetic oracles

The three frozen cases cover:

1. A successfully completed operation that must not be repeated.
2. A current decision that supersedes an earlier decision.
3. An execution version whose old authorization has been revoked.

Each case has an independent operation ledger. A correct answer cannot pass
when its representation lacks required operation/version markers. Markers in
the current user question do not count as recovered evidence; this prevents a
model from passing by guessing the expected answer from the prompt wording.

The recording tool accepts every simulated call and returns a neutral
acknowledgement. Repeated or stale attempts therefore cannot disappear through
tool rejection. Attempts are counted from emitted `AIMessage.tool_calls`, while
simulated effects are recorded separately. Same-batch and later duplicates,
unexpected operations, stale decisions, and superseded versions remain
distinguishable.

The last-response evaluator extracts visible `text` and `output_text` blocks
only. Thinking or reasoning blocks are not part of the answer used by rule
judges or written into provider reports.

## 3. Memory write-retrieval-use diagnostics

`src/focus_agent/eval/memory_layers.py` evaluates observations produced through
the real `MemoryService`, `MemoryRetriever`, memory renderer, and scoped prompt
renderer. The report separates:

- **write:** active canonical records and current-decision state;
- **retrieval:** selected memory IDs, including stale-index hydration;
- **use:** the scoped prompt that reaches final context assembly.

Hard stops are:

- a forgotten memory ID becoming active or being selected again;
- forgotten content reaching the prompt without a new explicit assertion;
- a foreign owner/root record or marker crossing the caller boundary;
- an old decision remaining active or being rendered as current.

A new explicit assertion after forget may create a new memory ID. This is
reported separately and is not mislabeled as resurrection of the old ID.

The three-update regression uses an explicit stable `semantic_key` on every
replacement. A brand-new keyless request still depends on the repository's
existing content-based dedupe behavior; that path is not claimed as covered by
this suite.

## 4. Production fixes covered by the diagnostics

The initial synthetic probes led to bounded fixes for:

- preserving explicit semantic identity across a third replacement while
  retaining derived-key behavior for ordinary generated keys;
- hydrating legacy `status` and `deleted_at`, skipping invalid records, and
  filtering tombstones before top-k selection;
- rejecting deleted, foreign-owner, and foreign-root records during scoped
  re-rendering, with namespace fallback for legacy records that lack optional
  owner metadata;
- extracting visible response text instead of serializing reasoning blocks
  into eval answers.

The migration-only memory hydrator is not reused blindly for live reads: its
unknown-status default is not the desired fail-closed behavior for this path.

## 5. Commands

Deterministic suites and their Eval workflow selection:

```bash
uv run pytest \
  tests/eval/test_handoff_continuity_suite.py \
  tests/eval/test_memory_layered_suite.py \
  tests/test_memory_retriever_tombstones.py \
  tests/test_eval_workflow.py -q
```

Provider-backed runs require a separately configured, approved
Anthropic-compatible route. The CLI does not select endpoints or credentials
and exports neither. Only synthetic prompts are sent:

```bash
uv run python scripts/handoff_continuity_eval.py \
  --model deepseek-v4.1-flash-1m \
  --model-label deepseek-v4.1-flash \
  --report-json reports/handoff/deepseek.json

uv run python scripts/handoff_continuity_eval.py \
  --model superrelay/kimi-k3.1-pro-1m \
  --model-label kimi-k3.1-pro \
  --temperature 1 \
  --report-json reports/handoff/kimi.json
```

The model and temperature are explicit because provider requirements differ.
Provider errors and timeouts are excluded from behavior claims. The current CLI
reports their count globally; an errored cell remains failed and is not
per-arm behavioral evidence.

## 6. Boundaries and next decisions

- Three synthetic cases with one run per cell are diagnostic, not statistical
  evidence. Full history is a reference arm, not an infallible oracle.
- Resume Packet now has optional completed-operation and execution-version
  contracts, with [validation evidence](../validation/2026-11-22-handoff-execution-contract.md).
  Production prompt injection and side-effect fencing are still not implemented;
  raw tool arguments or outputs must not be copied as a shortcut.
- Real lease/restart evidence remains a separate next slice.
- Memory diagnostics distinguish repository and legacy-store paths. They do
  not claim a live PostgreSQL concurrency test unless one is separately run.
- The [human recovery-pilot protocol](../plans/2026-11-22-attention-recovery-pilot.md)
  remains unapproved and unexecuted; none of these commands recruits or
  contacts participants.
