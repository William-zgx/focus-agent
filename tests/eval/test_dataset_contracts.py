from __future__ import annotations

from pathlib import Path

from .runner.harness import load_dataset

REQUIRED_BASELINE_DATASETS = (
    "multi_agent.jsonl",
    "planning.jsonl",
    "tool_call.jsonl",
    "memory.jsonl",
    "memory_baseline.jsonl",
)


def test_round2_baseline_datasets_parse_and_have_minimum_coverage() -> None:
    dataset_dir = Path(__file__).parent / "datasets"
    for name in REQUIRED_BASELINE_DATASETS:
        cases = load_dataset(dataset_dir / name)
        assert len(cases) >= 30, name
        assert len({case.id for case in cases}) == len(cases), name
