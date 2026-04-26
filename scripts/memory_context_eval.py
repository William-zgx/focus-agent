#!/usr/bin/env python3
"""Run deterministic Memory / Context quality probes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "tests" / "eval" / "datasets" / "memory_context_quality.jsonl"
DEFAULT_REPORT_JSON = Path("reports/release-gate/memory-context-eval.json")


@dataclass(frozen=True, slots=True)
class ProbeResult:
    case_id: str
    passed: bool
    tags: list[str] = field(default_factory=list)
    answer: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "answer": self.answer,
            "verdicts": [
                {
                    "kind": "memory_context",
                    "passed": self.passed,
                    "reasoning": "; ".join(self.failures) if self.failures else "all probes passed",
                    "confidence": 1.0,
                    "details": {"failures": list(self.failures)},
                }
            ],
            "trajectory": [],
            "metrics": dict(self.metrics),
            "error": None,
            "tags": list(self.tags),
        }


def load_dataset(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source}:{line_no} invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{source}:{line_no} must be a JSON object")
        cases.append(payload)
    return cases


def evaluate_case(case: dict[str, Any]) -> ProbeResult:
    case_id = str(case.get("id") or "unknown")
    tags = [str(tag) for tag in list(case.get("tags") or [])]
    input_payload = case.get("input") if isinstance(case.get("input"), dict) else {}
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    context = str(input_payload.get("rendered_context") or "")
    answer = str(input_payload.get("answer") or "")
    combined = f"{context}\n{answer}"
    failures: list[str] = []

    required_facts = _strings(expected.get("required_facts"))
    recalled_facts = [fact for fact in required_facts if _contains(answer, fact)]
    missing_facts = [fact for fact in required_facts if fact not in recalled_facts]
    if missing_facts:
        failures.append(f"missing required facts: {missing_facts!r}")

    forbidden_facts = _strings(expected.get("forbidden_facts"))
    polluted = [fact for fact in forbidden_facts if _contains(combined, fact)]
    if polluted:
        failures.append(f"forbidden facts leaked: {polluted!r}")

    required_context = _strings(expected.get("required_context_markers"))
    missing_context = [marker for marker in required_context if not _contains(context, marker)]
    if missing_context:
        failures.append(f"missing context markers: {missing_context!r}")

    forbidden_context = _strings(expected.get("forbidden_context_markers"))
    stale_context = [marker for marker in forbidden_context if _contains(context, marker)]
    if stale_context:
        failures.append(f"stale context markers present: {stale_context!r}")

    artifact_refs = _strings(expected.get("artifact_refs"))
    missing_artifacts = [ref for ref in artifact_refs if not _contains(context, ref)]
    if missing_artifacts:
        failures.append(f"missing artifact refs: {missing_artifacts!r}")

    conflict_markers = _strings(expected.get("conflict_markers"))
    missing_conflicts = [marker for marker in conflict_markers if not _contains(combined, marker)]
    if missing_conflicts:
        failures.append(f"missing conflict markers: {missing_conflicts!r}")

    answer_contains = _strings(expected.get("answer_contains_all"))
    missing_answer = [marker for marker in answer_contains if not _contains(answer, marker)]
    if missing_answer:
        failures.append(f"answer missing markers: {missing_answer!r}")

    recall = len(recalled_facts) / len(required_facts) if required_facts else 1.0
    metrics = {
        "fact_fidelity": 0.0 if polluted else 1.0,
        "key_fact_recall": round(recall, 4),
        "irrelevant_memory_pollution": 1.0 if polluted or stale_context else 0.0,
        "conflict_memory_marked": 1.0 if conflict_markers and not missing_conflicts else 0.0,
        "compaction_answerable": 0.0 if missing_answer else 1.0,
        "artifact_refs_present": 0.0 if missing_artifacts else 1.0,
    }
    return ProbeResult(
        case_id=case_id,
        passed=not failures,
        tags=tags,
        answer=answer,
        metrics=metrics,
        failures=failures,
    )


def build_summary(results: Sequence[ProbeResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    metric_names = (
        "fact_fidelity",
        "key_fact_recall",
        "irrelevant_memory_pollution",
        "conflict_memory_marked",
        "compaction_answerable",
        "artifact_refs_present",
    )
    averages = {
        name: round(
            sum(float(result.metrics.get(name, 0.0)) for result in results) / total,
            4,
        )
        if total
        else 0.0
        for name in metric_names
    }
    per_tag_success: dict[str, float] = {}
    tag_buckets: dict[str, list[bool]] = {}
    for result in results:
        for tag in result.tags:
            tag_buckets.setdefault(tag, []).append(result.passed)
    for tag, values in tag_buckets.items():
        per_tag_success[tag] = round(sum(1 for value in values if value) / len(values), 4)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": 0,
        "task_success": round(passed / total, 4) if total else 0.0,
        **averages,
        "per_tag_success": per_tag_success,
        "failed_case_ids": [result.case_id for result in results if not result.passed],
    }


def write_report(path: str | Path, *, dataset: Path, results: Sequence[ProbeResult]) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = REPO_ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "dataset": str(dataset),
            "suite": "memory_context_quality",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
        "summary": build_summary(results),
        "comparison": {"regressions": []},
        "results": [result.to_dict() for result in results],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def run(dataset: str | Path = DEFAULT_DATASET, *, report_json: str | Path = DEFAULT_REPORT_JSON) -> dict[str, Any]:
    dataset_path = Path(dataset)
    cases = load_dataset(dataset_path)
    results = [evaluate_case(case) for case in cases]
    report_path = write_report(report_json, dataset=dataset_path, results=results)
    summary = build_summary(results)
    return {
        "status": "passed" if summary["failed"] == 0 else "failed",
        "report_json": str(report_path),
        "summary": summary,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Memory/context quality JSONL dataset.")
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON), help="Structured JSON report path.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(dataset=args.dataset, report_json=args.report_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[memory-context-eval] {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "report_json": result["report_json"]}, indent=2))
    return 0 if result["status"] == "passed" else 1


def _strings(value: Any) -> list[str]:
    return [str(item) for item in list(value or []) if str(item)]


def _contains(haystack: str, needle: str) -> bool:
    normalized_haystack = _normalize_text(haystack)
    normalized_needle = _normalize_text(needle)
    return normalized_needle in normalized_haystack


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


if __name__ == "__main__":
    raise SystemExit(main())
