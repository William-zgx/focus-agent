# Agent Eval Framework

Tests *behavior* of the Focus Agent, not its Python units. Drops the agent
into scripted tasks, scores each trajectory against rule / LLM / trajectory
judges, then aggregates suite-level metrics for CI gating.

## Quickstart

```bash
# Run the smoke suite (7 cases, no external API keys required if using a fake model).
uv run python -m tests.eval --suite smoke

# Run the Agent architecture / role-routing gate.
uv run python -m tests.eval --suite agent_arch --concurrency 1
uv run python -m tests.eval --suite agent_delegation --concurrency 1
uv run python -m tests.eval --suite agent_task_ledger --concurrency 1
uv run python -m tests.eval --suite golden_multi_agent --concurrency 1

# Full run with HTML + JSON reports.
uv run python -m tests.eval --suite all \
  --report-html reports/eval.html \
  --report-json reports/eval.json

# Run a cross-model matrix from per-case model_matrix metadata.
uv run python -m tests.eval --suite model_matrix \
  --report-json reports/eval-model-matrix.json

# Filter by taxonomy and emit failed cases as a follow-up dataset.
uv run python -m tests.eval --suite golden_multi_agent \
  --only-capability governance \
  --risk-level medium \
  --emit-failures-dataset reports/failed-golden.jsonl

# Compare against a stored baseline and fail CI on regression.
uv run python -m tests.eval --suite smoke \
  --baseline eval-baselines/main.json \
  --fail-if-regression \
  --report-json reports/current.json
# (exit code 2 signals regressions; 1 signals case failures.)

# Replay an earlier run's JSONL or JSON report.
uv run python -m tests.eval replay --from reports/current.jsonl --failed-only

# Convert a trajectory export into replayable eval cases.
uv run python -m tests.eval replay \
  --from /tmp/focus-agent-trajectory.jsonl \
  --trajectory-input \
  --write-dataset tests/eval/datasets/trajectory-replay.jsonl

# Promote failed trajectory turns into a dataset skeleton.
uv run python -m tests.eval promote \
  --from /tmp/focus-agent-trajectory.jsonl \
  --failed-only \
  --copy-tool-trajectory \
  --out tests/eval/datasets/promoted-trajectory.jsonl
```

## Pytest integration

```bash
uv run pytest tests/eval/test_framework_self.py
```

The self-tests use `conftest.py::eval_runtime_factory` to inject a scripted
fake model via the `model_factory` field on `EvalRuntime` — no network, no
provider keys. Add suite-specific pytest modules (e.g. `test_golden_suite.py`)
that parametrize over `load_dataset(...)` and assert `run_case(...).passed`.

## Dataset format

One JSONL file per suite under `tests/eval/datasets/`. The CLI resolves
`--suite smoke` to `datasets/smoke.jsonl`. Schema:

```json
{
  "id": "gt_smoke_search_code",
  "tags": ["smoke", "workspace"],
  "scene": "long_dialog_research",
  "skill_hints": ["code_reader"],
  "capability": "delegation",
  "risk_level": "medium",
  "agent_topology": {
    "mode": "orchestrator_planner_executor_critic",
    "roles": ["orchestrator", "planner", "executor", "critic"],
    "handoff_required": true,
    "critic_required": true
  },
  "setup": [{"user": "optional multi-turn warm-up"}],
  "input": {"user_message": "...", "initial_state": {}},
  "expected": {
    "answer_contains_any": ["..."],
    "answer_contains_all": ["..."],
    "answer_must_not_contain": ["..."],
    "answer_regex": "...",
    "answer_must_not_contain_regex": "...",
    "must_call_tools_any_order": ["search_code"],
    "must_call_tools_sequence": ["search_code", "read_file"],
    "must_not_call_tools": ["web_search"],
    "max_tool_calls": 3,
    "optimal_tool_sequence": ["search_code"],
    "trajectory_tolerance": 1,
    "must_delegate_to_roles_sequence": ["planner", "executor", "critic"],
    "must_record_handoffs_any_order": ["planner->executor"]
  },
  "environment": {
    "assertions": [
      {"path": "agent_team_tasks", "min_len": 2},
      {"path": "model_route_decision.effective_model", "equals": "openai:deepseek-chat"}
    ]
  },
  "model_matrix": [
    {"label": "low_cost", "model": "openai:deepseek-chat", "role": "summarizer"},
    {"label": "strong_reasoning", "model": "openai:deepseek-reasoner", "role": "planner"}
  ],
  "retries": 1,
  "acceptance": {
    "min_success_rate": 0.98,
    "max_cost_usd": 0.003,
    "max_p95_latency_ms": 2500
  },
  "judge": {
    "rule": true,
    "llm": {"enabled": false, "rubric": "<rubric text>"}
  }
}
```

Only `id`, `input.user_message`, and `expected` are required. Everything
else has sane defaults (`judge.rule = true`, `judge.llm.enabled = false`).
Extended fields are optional and backward-compatible:

- `capability` / `risk_level` classify cases for dashboards and filtering.
- `agent_topology` seeds multi-agent roles and governance expectations.
- `environment.assertions` checks final state with fallback to `input.initial_state`.
- `model_matrix` runs the same case across labeled model variants.
- `retries` emits multiple attempts so flaky cases can be detected.
- `acceptance` records suite policy targets for reports and review.

## Adding cases

1. Drop a JSON line into the suite file.
2. Run `uv run python -m tests.eval --suite smoke`.
3. If it should pass but doesn't, fix the agent (or the rubric) and re-run.
4. Commit the dataset together with the code change that makes it pass.

Smoke cases should include regression coverage for tool selection policy:
direct writing/no-tools requests, explicit no-web requests, and workspace
lookup requests that must not expose web tools.

Agent architecture cases live in `datasets/agent_arch.jsonl` and cover the
role-routing contract: default off behavior, no-web workspace lookup, memory
preview isolation, and helper-model fallback expectations.

Agent governance cases live in `datasets/agent_governance.jsonl` and cover
Memory Curator branch promotion boundaries plus Skill Scout / Tool Router
allow/deny expectations.

Agent delegation cases live in `datasets/agent_delegation.jsonl` and cover
default-off behavior, role run paths, Model Router decisions, self-repair
preview, and Review Queue expectations.

Agent task ledger cases live in `datasets/agent_task_ledger.jsonl` and cover
default-off behavior, delegated task paths, artifact synthesis, critic gate
blocking, and governance artifacts.

Golden multi-agent cases live in `datasets/golden_multi_agent.jsonl` and cover
stable delegation, governance, memory/context, and model-routing contracts. The
release gate runs this suite as a blocking check.

Model matrix cases live in `datasets/model_matrix.jsonl` and compare labeled
model roles against the same task inputs. Nightly runs this suite and uploads
reports without blocking release.

Trajectory failure skeletons live in `datasets/trajectory_failures.jsonl` and
capture production replay failures ready for hardening. Nightly runs this suite
as a non-blocking signal until cases are promoted into golden coverage.

## Judges

| Judge             | When it runs                                        | Cost   |
|-------------------|-----------------------------------------------------|--------|
| `RuleJudge`       | Always unless `judge.rule == false`                 | Free   |
| `LLMJudge`        | When `judge.llm.enabled == true` and model wired up | Small  |
| `TrajectoryJudge` | When `max_tool_calls` or `optimal_tool_sequence` set| Free   |
| `EnvironmentJudge`| When `environment.assertions` are present           | Free   |

All enabled judges must pass for a case to be marked `passed`. `LLMJudge` supports
an escalation path: if the cheap model returns confidence below
`escalate_below` (default 0.7) and an `escalator` model is wired, the big
model re-judges and its verdict wins.

`TrajectoryJudge` also supports multi-agent collaboration checks:
`must_delegate_to_roles_any_order`, `must_delegate_to_roles_sequence`,
`must_not_delegate_to_roles`, `must_record_handoffs_any_order`,
`max_duplicate_tool_calls`, and `max_repeated_role_runs`.

`EnvironmentJudge` supports `path`, `exists`, `equals`, `contains`,
`not_contains`, `min_len`, and `max_len`. Paths use dot notation and list
indexes, for example `agent_team_tasks.0.role`.

## Metrics

`aggregate_metrics` produces a `MetricSummary` with:

- `task_success`, `passed`, `failed`, `errors`
- `avg_tool_calls`, `avg_llm_calls`, `avg_input_tokens`, `avg_output_tokens`
- `p50_latency_ms`, `p95_latency_ms`, `avg_cost_usd`
- `forbidden_tool_violation_rate`
- `per_tag_success`, `per_capability_success`, `per_risk_level_success`
- `failed_case_ids`, `flaky_case_ids`, and `failure_clusters`
- `model_matrix`
- collaboration metrics: delegation, handoff, critic gate, fallback, parallel,
  and environment assertion rates

Token + cost accounting only works when the underlying chat model exposes
`usage_metadata` (OpenAI / Anthropic SDKs do). Set `cost_per_1k_input` /
`cost_per_1k_output` on `EvalRuntime` for dollar estimates.

## Regression gate

`compare_baselines` flags:

- `task_success` drop > 2 percentage points
- any new forbidden-tool violation
- any efficiency metric (tool_calls / llm_calls / tokens / latency / cost)
  growing > 20% vs baseline; `p95_latency_ms` also needs to exceed a 100ms
  absolute delta so small deterministic suites do not fail on runner jitter

Use `--fail-if-regression` in CI when comparing against a baseline. Store
baselines as JSON (produced by `--report-json`) under `eval-baselines/` and
bump them intentionally when you accept a trade-off. Without a baseline, the
CLI still fails when any case fails; the regression comparison simply has no
prior metrics to diff against.

## Eval layers

Use these layers for ownership and CI policy:

- `smoke`: fast release gate for core regressions.
- `golden_multi_agent`: blocking release gate for stable multi-agent contracts.
- `trajectory_failures`: non-blocking nightly replay hardening queue.
- `stress`: reserved for retries, context pressure, and concurrency stress.
- `model_matrix`: non-blocking nightly model stability/cost comparison.

## Multi-agent implementation ownership

When expanding this framework with multiple coding agents, keep write scopes
separate:

- Dataset owner: `tests/eval/datasets/**`
- Harness owner: `tests/eval/schema.py` and `tests/eval/runner/**`
- Judge owner: `tests/eval/judges/**`
- Metrics/report owner: `tests/eval/metrics/**` and `tests/eval/reporting.py`
- Gate/CI owner: `scripts/*eval*`, `scripts/release_gate.py`, and workflows
- Verification owner: read-only review and test execution

## Trajectory replay and promotion

Production trajectory exports can be inspected through `focus-agent-trajectory`
or the Web console at `/app/observability/trajectory`, then converted into eval
cases with `python -m tests.eval replay --trajectory-input` or
`python -m tests.eval promote`.

Use `--copy-tool-trajectory` when you want the generated case to preserve the
observed tool path as an expectation. Use `--copy-answer-substring` only when
the source answer is stable enough to become a useful assertion.

## Extending

- New judge: implement a `.evaluate(*, case, answer, trajectory) -> JudgeVerdict`
  and register it in `runner/harness.py::_run_judges`.
- New metric: add a field to `MetricSummary` and populate it in
  `aggregate_metrics`.
- New suite: drop `datasets/<name>.jsonl` and run `--suite <name>`.
