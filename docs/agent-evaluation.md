# Agent Evaluation

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
| Golden multi-agent | `golden_multi_agent` | Blocking release gate | Stable contracts for delegation, governance, memory/context, and model routing. |
| Trajectory failures | `trajectory_failures` | Non-blocking nightly | Production failure skeletons that should be hardened or promoted. |
| Model matrix | `model_matrix` | Non-blocking nightly | Compare labeled model roles on the same task inputs. |
| Stress | future suite | Manual or nightly | Retries, concurrency, long context, and flaky behavior. |

## Case Taxonomy

Eval cases remain JSONL and stay backward-compatible. New fields are optional:

- `capability`: behavior area such as `delegation`, `governance`,
  `memory_context`, or `model_routing`.
- `risk_level`: `low`, `medium`, or `high`.
- `agent_topology`: expected multi-agent mode, roles, handoff requirement, and
  critic requirement.
- `environment.assertions`: deterministic final-state checks. Assertions can
  fall back to `input.initial_state` when the graph does not preserve a field.
- `model_matrix`: labeled model variants for cross-model comparison.
- `retries`: additional attempts for flaky-case detection.
- `acceptance`: policy targets such as minimum success rate or maximum latency.

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
uv run python -m tests.eval --suite golden_multi_agent --concurrency 1

# Governance-specific suites.
uv run python -m tests.eval --suite agent_arch --concurrency 1
uv run python -m tests.eval --suite agent_governance --concurrency 1
uv run python -m tests.eval --suite agent_delegation --concurrency 1
uv run python -m tests.eval --suite agent_context --concurrency 1
uv run python -m tests.eval --suite agent_task_ledger --concurrency 1

# Nightly/non-blocking signals.
uv run python -m tests.eval --suite model_matrix --concurrency 1
uv run python -m tests.eval --suite trajectory_failures --concurrency 1

# Filter, retry, and emit a follow-up dataset.
uv run python -m tests.eval --suite golden_multi_agent \
  --only-capability governance \
  --risk-level medium \
  --retries 1 \
  --emit-failures-dataset reports/eval/failed-golden.jsonl
```

## Reports

JSON and HTML reports include:

- task success, failed cases, error count, latency, token, and cost metrics
- per-tag, per-capability, and per-risk success
- collaboration metrics for delegation, handoff, critic gate, fallback, and
  parallel tool use
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
case into `golden_multi_agent` only after the assertion is deterministic enough
to block release.

## Ownership

When several agents or engineers expand the eval system, keep write scopes
separate:

- Dataset owner: `tests/eval/datasets/**`
- Harness owner: `tests/eval/schema.py` and `tests/eval/runner/**`
- Judge owner: `tests/eval/judges/**`
- Metrics/report owner: `tests/eval/metrics/**` and `tests/eval/reporting.py`
- Gate/CI owner: `scripts/*eval*`, `scripts/release_gate.py`, and workflows
- Verification owner: read-only review and test execution
