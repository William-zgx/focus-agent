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
_PASS_STATUSES = {"pass", "passed", "success", "succeeded", "ok"}


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


def convert_failure_report_to_cases(
    path: str | Path,
    *,
    case_id_prefix: str = "mc_replay",
) -> list[dict[str, Any]]:
    """Convert failed trajectory/replay JSON records into deterministic eval cases."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records = _extract_failure_records(payload)
    cases: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        if not _record_failed(record):
            continue
        case = _failure_record_to_case(record, case_id_prefix=case_id_prefix, index=index)
        if case is not None:
            cases.append(case)
    return cases


def write_cases_jsonl(path: str | Path, cases: Sequence[dict[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(case, ensure_ascii=False, sort_keys=True) for case in cases]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


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
    parser.add_argument(
        "--convert-failures-json",
        help="Trajectory export or replay report JSON to convert into memory/context cases.",
    )
    parser.add_argument(
        "--converted-dataset-out",
        help="Write converted failure cases as JSONL instead of running the suite.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.convert_failures_json:
            cases = convert_failure_report_to_cases(args.convert_failures_json)
            if args.converted_dataset_out:
                target = write_cases_jsonl(args.converted_dataset_out, cases)
                print(json.dumps({"converted": len(cases), "dataset": str(target)}, indent=2))
            else:
                print(json.dumps({"converted": len(cases), "cases": cases}, ensure_ascii=False, indent=2))
            return 0
        result = run(dataset=args.dataset, report_json=args.report_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[memory-context-eval] {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "report_json": result["report_json"]}, indent=2))
    return 0 if result["status"] == "passed" else 1


def _strings(value: Any) -> list[str]:
    return [str(item) for item in list(value or []) if str(item)]


def _extract_failure_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in ("results", "comparisons", "records", "turns", "items", "data"):
            records = payload.get(key)
            if isinstance(records, list):
                return [record for record in records if isinstance(record, dict)]
        if payload:
            return [payload]
    raise ValueError("unsupported failure conversion payload")


def _record_failed(record: dict[str, Any]) -> bool:
    for key in ("passed", "replay_passed", "success"):
        if key in record:
            return not bool(record.get(key))
    if record.get("error") or record.get("replay_error"):
        return True
    status = str(record.get("status") or record.get("source_status") or "").strip().lower()
    return bool(status) and status not in _PASS_STATUSES


def _failure_record_to_case(
    record: dict[str, Any],
    *,
    case_id_prefix: str,
    index: int,
) -> dict[str, Any] | None:
    replay_case = record.get("replay_case") if isinstance(record.get("replay_case"), dict) else {}
    input_payload = _first_mapping(record.get("input"), replay_case.get("input"))
    expected = _first_mapping(record.get("expected"), replay_case.get("expected"))
    context = _first_text(
        record.get("rendered_context"),
        record.get("context"),
        record.get("memory_context"),
        input_payload.get("rendered_context"),
        input_payload.get("context"),
        input_payload.get("memory_context"),
    )
    answer = _first_text(
        record.get("answer"),
        record.get("replay_answer"),
        record.get("replay_answer_preview"),
        _nested_text(record, ("replay_result", "answer")),
        input_payload.get("answer"),
    )
    converted_expected = _convert_expected(record, expected)
    if not _has_expected_assertions(converted_expected):
        return None

    source_id = str(record.get("case_id") or record.get("id") or record.get("trajectory_id") or index)
    return {
        "id": f"{_slug(case_id_prefix)}_{_slug(source_id) or index}",
        "tags": ["memory_context", "converted_failure", "trajectory_replay"],
        "input": {"rendered_context": context, "answer": answer},
        "expected": converted_expected,
        "origin": {
            "type": "trajectory_replay_failure",
            "case_id": record.get("case_id"),
            "trajectory_id": record.get("trajectory_id") or record.get("id"),
            "source_status": record.get("source_status") or record.get("status"),
            "replay_error": record.get("replay_error") or record.get("error"),
        },
    }


def _convert_expected(record: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return {
        "required_facts": _strings(
            expected.get("required_facts")
            or expected.get("answer_contains_all")
            or record.get("required_facts")
            or record.get("missing_required_facts")
        ),
        "forbidden_facts": _strings(
            expected.get("forbidden_facts") or record.get("forbidden_facts") or record.get("leaked_facts")
        ),
        "required_context_markers": _strings(expected.get("required_context_markers")),
        "forbidden_context_markers": _strings(expected.get("forbidden_context_markers")),
        "artifact_refs": _strings(
            expected.get("artifact_refs") or record.get("artifact_refs") or record.get("missing_artifact_refs")
        ),
        "conflict_markers": _strings(expected.get("conflict_markers") or record.get("conflict_markers")),
        "answer_contains_all": _strings(expected.get("answer_contains_all") or record.get("answer_contains_all")),
    }


def _has_expected_assertions(expected: dict[str, Any]) -> bool:
    return any(_strings(value) for value in expected.values())


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value)
    return ""


def _nested_text(mapping: dict[str, Any], path: Sequence[str]) -> str:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current or "")


def _slug(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "")).strip("-").lower()


def _contains(haystack: str, needle: str) -> bool:
    normalized_haystack = _normalize_text(haystack)
    normalized_needle = _normalize_text(needle)
    return normalized_needle in normalized_haystack


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).casefold()).strip()


if __name__ == "__main__":
    raise SystemExit(main())
