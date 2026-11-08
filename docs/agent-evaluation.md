# Agent Evaluation

Updated: 2026-11-01
Harness policy baseline: `81f7a6f` plus context-quality changes; paired branch-workflow evidence added for the current experiment.

Focus Agent evaluates agent behavior end to end: the graph receives a scripted
task, the runner records the final answer and tool trajectory, judges score the
run, and reports aggregate quality, cost, latency, and collaboration signals.
The implementation guide for the harness lives in
[`tests/eval/README.md`](../tests/eval/README.md); this document records the
project-level policy for when and how to run it.

## Evaluation Layers

| Layer | Dataset | Release policy | Purpose |
|-------|---------|----------------|---------|
| Smoke | `smoke` | Blocking release gate | Fast coverage for core behavior and tool-policy regressions. |
| Observability | `observability` | Blocking release gate | Stable trajectory, streaming, and observability contracts. |
| Harness stability | `harness_stability` | Blocking release gate | Regression coverage for v2 harness run lifecycle, streaming, replay, and terminal-state behavior. |
| Trajectory failures | `trajectory_failures` | Non-blocking nightly | Production failure skeletons that should be hardened or promoted. |
| Model matrix | `model_matrix` | Non-blocking nightly | Compare labeled model roles on the same task inputs. |
| Stress | future suite | Manual or nightly | Retries, concurrency, long context, and flaky behavior. |
| Branch vs. linear A/B | `branch_ab` (frozen, 32 tasks) | Manual, real model | Paired experiment for the branch-workflow thesis: the same user messages run in one linear thread and through fork / merge; two blind LLM judges score the final answer. Runs outside `tests.eval` via `scripts/branch_ab/`; see the [dataset README](../tests/eval/datasets/branch_ab/README.md) and [results](plans/2026-10-31-branch-ab/status.md). |

## Case Taxonomy

Eval cases remain JSONL and stay backward-compatible. New fields are optional:

- `capability`: behavior area such as `delegation`, `governance`,
  `memory_context`, or `model_routing`.
- `risk_level`: `low`, `medium`, or `high`.
- `agent_topology`: expected multi-agent mode, roles, handoff requirement, and
  critic requirement.
- `environment.assertions`: final-state checks by default, with no implicit
  fallback to initial state. Use `source: "input"` for explicit input-context
  checks or `source: "trajectory"` for recorded execution evidence. Mutation
  cases still need operation-specific final values or receipts.
- `model_matrix`: labeled model variants for cross-model comparison.
- `retries`: additional attempts for flaky-case detection.
- `acceptance`: enforced by the runner. Cost is checked per attempt; p95
  latency and minimum success rate include all case attempts, including
  failures and timeouts.

## Judges

- `RuleJudge` checks answer text and required or forbidden tools.
- `TrajectoryJudge` checks tool count, optimal path, runtime metadata, delegated
  roles, handoffs, duplicate tool calls, and repeated role runs.
- `EnvironmentJudge` checks final state using `exists`, `equals`, `contains`,
  `not_contains`, `min_len`, and `max_len`.
- `LLMJudge` is optional and should not be the only passing condition for
  release-blocking suites.

## Common Commands

```bash
# Fast deterministic framework checks.
uv run pytest tests/eval/test_framework_self.py

# Blocking release-gate suites.
uv run python -m tests.eval --suite smoke --concurrency 1
uv run python -m tests.eval --suite observability --concurrency 1
uv run python -m tests.eval --suite harness_stability --concurrency 1

# Retained governance and context suites.
uv run python -m tests.eval --suite agent_governance --concurrency 1
uv run python -m tests.eval --suite agent_context --concurrency 1

# Nightly/non-blocking signals.
uv run python -m tests.eval --suite model_matrix --concurrency 1
uv run python -m tests.eval --suite trajectory_failures --concurrency 1

# Filter, retry, and emit a follow-up dataset.
uv run python -m tests.eval --suite smoke \
  --risk-level low \
  --retries 1 \
  --emit-failures-dataset reports/eval/failed-smoke.jsonl
```

## Reports

JSON and HTML reports include:

- task success, failed cases, error count, latency, token, and cost metrics.
  Token/cost values are measured only when model usage metadata and runtime
  pricing are available; otherwise `cost_status` is `unknown`, not zero cost.
  `runtime_kind` and `eval_layer` distinguish provider quality from fake or
  offline harness evidence.
- per-tag, per-capability, and per-risk success
- collaboration metrics for delegation, handoff, review/verification outcomes,
  model fallback, and parallel tool use
- environment assertion failure rate
- flaky case ids when retries are used
- failure clusters grouped by capability, risk, and reason
- model matrix summaries by label and base case

## Production Trace Loop

Trajectory exports can be converted into eval cases or replayed directly:

```bash
uv run python -m tests.eval replay \
  --from /tmp/focus-agent-trajectory.jsonl \
  --trajectory-input \
  --failed-only \
  --copy-tool-trajectory \
  --run \
  --report-json reports/eval/trajectory-replay.json
```

Promote stable, human-reviewed failures into `trajectory_failures` first. Move a
case into `smoke` or `observability` only after the assertion is deterministic
enough to block release.

## Ownership

When several agents or engineers expand the eval system, keep write scopes
separate:

- Dataset owner: `tests/eval/datasets/**`
- Harness owner: `tests/eval/schema.py` and `tests/eval/runner/**`
- Judge owner: `tests/eval/judges/**`
- Metrics/report owner: `tests/eval/metrics/**` and `tests/eval/reporting.py`
- Gate/CI owner: `scripts/*eval*`, `scripts/release_gate.py`, and workflows
- Verification owner: read-only review and test execution
