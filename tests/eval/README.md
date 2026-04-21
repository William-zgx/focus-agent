# Agent Eval Framework

Tests *behavior* of the Focus Agent, not its Python units. Drops the agent
into scripted tasks, scores each trajectory against rule / LLM / trajectory
judges, then aggregates suite-level metrics for CI gating.

## Quickstart

```bash
# Run the smoke suite (7 cases, no external API keys required if using a fake model).
uv run python -m tests.eval --suite smoke

# Full run with HTML + JSON reports.
uv run python -m tests.eval --suite all \
  --report-html reports/eval.html \
  --report-json reports/eval.json

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
    "trajectory_tolerance": 1
  },
  "judge": {
    "rule": true,
    "llm": {"enabled": false, "rubric": "<rubric text>"}
  }
}
```

Only `id`, `input.user_message`, and `expected` are required. Everything
else has sane defaults (`judge.rule = true`, `judge.llm.enabled = false`).

## Adding cases

1. Drop a JSON line into the suite file.
2. Run `uv run python -m tests.eval --suite smoke`.
3. If it should pass but doesn't, fix the agent (or the rubric) and re-run.
4. Commit the dataset together with the code change that makes it pass.

Smoke cases should include regression coverage for tool selection policy:
direct writing/no-tools requests, explicit no-web requests, and workspace
lookup requests that must not expose web tools.

## Judges

| Judge             | When it runs                                        | Cost   |
|-------------------|-----------------------------------------------------|--------|
| `RuleJudge`       | Always unless `judge.rule == false`                 | Free   |
| `LLMJudge`        | When `judge.llm.enabled == true` and model wired up | Small  |
| `TrajectoryJudge` | When `max_tool_calls` or `optimal_tool_sequence` set| Free   |

All three must pass for a case to be marked `passed`. `LLMJudge` supports
an escalation path: if the cheap model returns confidence below
`escalate_below` (default 0.7) and an `escalator` model is wired, the big
model re-judges and its verdict wins.

## Metrics

`aggregate_metrics` produces a `MetricSummary` with:

- `task_success`, `passed`, `failed`, `errors`
- `avg_tool_calls`, `avg_llm_calls`, `avg_input_tokens`, `avg_output_tokens`
- `p50_latency_ms`, `p95_latency_ms`, `avg_cost_usd`
- `forbidden_tool_violation_rate`
- `per_tag_success` and `failed_case_ids`

Token + cost accounting only works when the underlying chat model exposes
`usage_metadata` (OpenAI / Anthropic SDKs do). Set `cost_per_1k_input` /
`cost_per_1k_output` on `EvalRuntime` for dollar estimates.

## Regression gate

`compare_baselines` flags:

- `task_success` drop > 2 percentage points
- any new forbidden-tool violation
- any efficiency metric (tool_calls / llm_calls / tokens / latency / cost)
  growing > 20% vs baseline

Use `--fail-if-regression` in CI when comparing against a baseline. Store
baselines as JSON (produced by `--report-json`) under `eval-baselines/` and
bump them intentionally when you accept a trade-off. Without a baseline, the
CLI still fails when any case fails; the regression comparison simply has no
prior metrics to diff against.

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
