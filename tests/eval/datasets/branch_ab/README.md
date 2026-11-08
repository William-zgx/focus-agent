# branch_ab: linear vs. branch workflow, frozen task set

Frozen on 2026-10-31. `tasks.jsonl` sha256:
`a42e82ecd2ef1eff86a6f6d4ac07420fc85a1a981c33f5f1e28c9b234b351931`.
Do not edit this set after the baseline runs; add a new versioned set instead.

## What it measures

Each task is a long work session: a main line of work with hard constraints,
then a detour (side question) that explores, rejects some material and settles
a decision, then a return turn asking for the final deliverable. The same user
messages run in two arms (see `scripts/branch_ab/run_experiment.py`):

- `linear`: every turn goes into one thread.
- `branch`: detour turns go into a child branch forked from main; the merge
  proposal is approved and imported; the return turn is sent on main.

Only the answer to the return turn is scored:

- `must_include` (`main_constraint` / `detour_detail`): regexes, any match passes.
- `must_not_include`: regexes for rejected or superseded material (contamination).
- `rubric`: criteria for a blind LLM judge (`scripts/branch_ab/score.py`).

## Composition

32 tasks: research, debugging, writing and review, 8 each (4 Simplified Chinese,
4 English). 246 `must_include` items, 93 of them detour details; 82
`must_not_include` items; 5.0 detour turns per task on average. All decisive
facts are fictional and stated by the user; the tasks require no external tools.
The runtime's residual tool exposure is described below. User
messages never use 分支, 支线, branch, fork, 分叉, merge or 合并, because those
words trigger branch actions and would break the linear arm.

## How it was produced

1. Authoring: four DeepSeek V4 Pro agents (one per category) wrote the tasks
   from a fixed brief, in empty directories, without access to this repository.
2. Adversarial review: four separate DeepSeek V4 Pro agents fixed grading
   defects (false contamination, false pass, false fail). Each wrote one
   realistic correct answer and one wrong answer per task and asserted that
   the correct answer passes and the wrong one is caught. Their changes and
   scripts are under `evidence/<category>/` (`review.md`, `check_answers.py`,
   and the category slice of `tasks.jsonl` they verified).
3. Structural validation by the lead: counts, forbidden words, regex
   compilation, every required token present in user text, detour details
   present in detour turns, no answer tokens leaked into the return turn.

## Running conditions (both arms identical)

Set in `scripts/branch_ab/run_experiment.py::_isolated_env`:

- One fresh process and temporary state directory per (task, arm, repeat).
- Catalog-controlled tools disabled (`scripts/branch_ab/tools.disabled.toml`)
  and skills off (`FOCUS_AGENT_SKILLS_ENABLED=false`): every fact is in the
  conversation. Until 2026-11-07 the runtime registered `run_skill_entrypoint`
  regardless of these switches, so planners in the earlier baseline and fix-1
  runs could see it (both arms alike). It is now registered only when skills are
  enabled.
- Branch recommendation, branch decision, web search and memory
  embeddings off; `MODEL_REQUEST_TIMEOUT_SECONDS=600` for slow relay endpoints.
- Before each turn, before fork and before the merge proposal, the runner waits
  for background work (compaction, titles) to drain, as a pausing user would.

## Scoring rules

- A run whose approved merge the product refuses is recorded as
  `product_failure` and scored as an undelivered answer (judge overall 1); it
  stays in the pairs. Infrastructure errors (`error`: 429, timeouts) are retried
  by rerunning the same command; finished runs are skipped.
- Pass (pass^1 / pass^k) uses the judge only: overall >= 4 and no adopted
  rejected material. Regex contamination is diagnostic: it also fires when an
  answer correctly says "X was ruled out".
- Judges: report each judge separately (they differ in strictness), and accept a
  conclusion only when both judges agree on the direction of the paired
  difference. The model under test must not be the only judge.

Commands and current results: [experiment record](../../../../docs/plans/2026-10-31-branch-ab/status.md).
Use a new output directory when changing model, runtime configuration or code;
resume checks the run status, not configuration identity. Keep judges' score
files separate when analyzing them. Report pass^3 only after all three repeats
per task have valid scores.

Known limitations:

- The correct/wrong answers in `evidence/` were written by the tested model's
  family. They show internal consistency, not coverage of every valid phrasing.
- The primary judge is also DeepSeek V4.1 Flash; Sonnet 5.5 supplies a separate
  model family for cross-checking. Blind grading does not remove self-preference.
- The judge prompt does not enforce exactly one response criterion per rubric
  item. Some responses split or add criteria, so `rubric_rate` has variable
  denominators and is descriptive. Overall-score comparisons are also checked
  after excluding pairs with a mismatched criterion count; this does not prove
  that the remaining criterion wording maps perfectly to the rubric.
- These synthetic, text-only sessions do not establish performance on real
  tool tasks, nested branches or arbitrary conversation lengths.
- A confidence interval crossing zero does not establish equivalence or
  non-inferiority. Neither a non-inferiority margin nor a separate holdout set
  was specified; repeated development on this set may overfit it.

Re-run the evidence checks:

```bash
for c in research debugging writing review; do (cd tests/eval/datasets/branch_ab/evidence/$c && python3 check_answers.py | tail -1); done
```
