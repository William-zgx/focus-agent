#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

"${PYTHON:-.venv/bin/python}" -m tests.eval \
  --suite "${FOCUS_AGENT_EVAL_SUITE:-harness_stability}" \
  --concurrency "${FOCUS_AGENT_EVAL_CONCURRENCY:-1}" \
  --baseline "${FOCUS_AGENT_EVAL_BASELINE:-docs/eval/baseline.json}" \
  --threshold "${FOCUS_AGENT_EVAL_THRESHOLD:-0.95}" \
  --fail-if-regression \
  --report-json "${FOCUS_AGENT_EVAL_REPORT_JSON:-reports/eval/latest.json}" \
  --report-jsonl "${FOCUS_AGENT_EVAL_REPORT_JSONL:-reports/eval/latest.jsonl}"
