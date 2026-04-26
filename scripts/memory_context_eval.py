#!/usr/bin/env python3
"""Run deterministic Memory / Context quality probes."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "tests" / "eval" / "datasets" / "memory_context_quality.jsonl"
DEFAULT_REPORT_JSON = Path("reports/release-gate/memory-context-eval.json")
DEFAULT_CANDIDATE_ID_PREFIX = "mc_candidate"
_PASS_STATUSES = {"pass", "passed", "success", "succeeded", "ok"}
_SOURCE_TYPES = {"auto", "trajectory", "replay", "memory-context"}

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{10,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_TOKEN_LITERAL_RE = re.compile(
    r"\b(?:sk|pk|rk|ghp|gho|github_pat|xoxb|xoxp|ya29|pat|tok)[-_A-Za-z0-9.]{10,}\b"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?P<key>api[_-]?key|secret|access[_-]?token|refresh[_-]?token|token|"
    r"password|passwd|pwd)(?P<sep>\s*[:=]\s*)(?P<quote>[\"']?)(?P<value>[^\s\"',;)}\]]+)"
)
_PHONE_CANDIDATE_RE = re.compile(r"(?<![\w/])(?:\+?\d[\d .()/-]{8,}\d)(?![\w/])")


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


@dataclass(frozen=True, slots=True)
class CandidateImportResult:
    cases: list[dict[str, Any]]
    source_count: int
    record_count: int
    skipped_no_assertions: int
    skipped_duplicates: int

    def to_dict(self, *, dataset: str | None = None) -> dict[str, Any]:
        payload = {
            "imported": len(self.cases),
            "sources": self.source_count,
            "records": self.record_count,
            "skipped_no_assertions": self.skipped_no_assertions,
            "skipped_duplicates": self.skipped_duplicates,
        }
        if dataset is not None:
            payload["dataset"] = dataset
        return payload


@dataclass(frozen=True, slots=True)
class CandidatePromotionReviewResult:
    reviewed_cases: list[dict[str, Any]]
    promoted_cases: list[dict[str, Any]]
    source_count: int
    record_count: int
    skipped_no_assertions: int
    skipped_duplicates: int
    approved_count: int
    rejected_count: int
    pending_count: int

    def to_dict(
        self,
        *,
        reviewed_dataset: str | None = None,
        promoted_dataset: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "reviewed": len(self.reviewed_cases),
            "promoted": len(self.promoted_cases),
            "sources": self.source_count,
            "records": self.record_count,
            "skipped_no_assertions": self.skipped_no_assertions,
            "skipped_duplicates": self.skipped_duplicates,
            "approved": self.approved_count,
            "rejected": self.rejected_count,
            "pending": self.pending_count,
        }
        if reviewed_dataset is not None:
            payload["reviewed_dataset"] = reviewed_dataset
        if promoted_dataset is not None:
            payload["promoted_dataset"] = promoted_dataset
        return payload


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


def import_candidate_cases(
    sources: Sequence[str | Path],
    *,
    source_type: str = "auto",
    candidate_id_prefix: str = DEFAULT_CANDIDATE_ID_PREFIX,
    baseline_label: str = "candidate",
    baseline_marker: str | None = None,
    redact: bool = True,
) -> CandidateImportResult:
    """Import real-sample memory/context candidates from trajectory or report files."""
    if source_type not in _SOURCE_TYPES:
        raise ValueError(f"unsupported candidate source type: {source_type}")
    resolved_baseline_label = baseline_marker or baseline_label

    cases: list[dict[str, Any]] = []
    dedupe_keys: set[str] = set()
    record_count = 0
    skipped_no_assertions = 0
    skipped_duplicates = 0

    for source in sources:
        source_path = Path(source).expanduser()
        payload = _load_json_or_jsonl(source_path)
        resolved_type = _resolve_candidate_source_type(payload, source_type=source_type)
        records = _extract_candidate_records(payload, source_type=resolved_type)
        for index, record in enumerate(records, start=1):
            record_count += 1
            case = _candidate_record_to_case(
                record,
                source_path=source_path,
                source_type=resolved_type,
                source_index=index,
                candidate_id_prefix=candidate_id_prefix,
                baseline_label=resolved_baseline_label,
            )
            if case is None:
                skipped_no_assertions += 1
                continue
            if redact:
                case = _sanitize_json(case)
            dedupe_key = _candidate_dedupe_key(case)
            if dedupe_key in dedupe_keys:
                skipped_duplicates += 1
                continue
            dedupe_keys.add(dedupe_key)
            cases.append(case)

    return CandidateImportResult(
        cases=cases,
        source_count=len(sources),
        record_count=record_count,
        skipped_no_assertions=skipped_no_assertions,
        skipped_duplicates=skipped_duplicates,
    )


def review_candidate_cases(
    candidate_jsonl: Sequence[str | Path],
    *,
    approved_ids: Sequence[str] = (),
    rejected_ids: Sequence[str] = (),
    approve_all: bool = False,
    reviewer: str | None = None,
    note: str | None = None,
    redact: bool = True,
) -> CandidatePromotionReviewResult:
    """Review imported candidates and return explicitly approved promotion cases."""
    approved_set = {str(case_id) for case_id in approved_ids if str(case_id)}
    rejected_set = {str(case_id) for case_id in rejected_ids if str(case_id)}
    conflicts = sorted(approved_set & rejected_set)
    if conflicts:
        raise ValueError(f"candidate ids cannot be both approved and rejected: {conflicts!r}")

    reviewed_cases: list[dict[str, Any]] = []
    promoted_cases: list[dict[str, Any]] = []
    dedupe_keys: set[str] = set()
    record_count = 0
    skipped_no_assertions = 0
    skipped_duplicates = 0
    approved_count = 0
    rejected_count = 0
    pending_count = 0

    for source in candidate_jsonl:
        for case in load_dataset(source):
            record_count += 1
            candidate = _sanitize_json(case) if redact else dict(case)
            expected = candidate.get("expected") if isinstance(candidate.get("expected"), dict) else {}
            if not _has_expected_assertions(expected):
                skipped_no_assertions += 1
                continue
            dedupe_key = _candidate_dedupe_key(candidate)
            if dedupe_key in dedupe_keys:
                skipped_duplicates += 1
                continue
            dedupe_keys.add(dedupe_key)

            candidate_id = str(candidate.get("id") or "")
            if candidate_id in rejected_set:
                status = "rejected"
                reason = "explicit_rejection"
                rejected_count += 1
            elif approve_all or candidate_id in approved_set:
                status = "approved"
                reason = "explicit_approval"
                approved_count += 1
            else:
                status = "pending"
                reason = "awaiting_explicit_approval"
                pending_count += 1

            reviewed_case = _with_promotion_review(
                candidate,
                status=status,
                reason=reason,
                reviewer=reviewer,
                note=note,
            )
            reviewed_cases.append(reviewed_case)
            if status == "approved":
                promoted_cases.append(reviewed_case)

    return CandidatePromotionReviewResult(
        reviewed_cases=reviewed_cases,
        promoted_cases=promoted_cases,
        source_count=len(candidate_jsonl),
        record_count=record_count,
        skipped_no_assertions=skipped_no_assertions,
        skipped_duplicates=skipped_duplicates,
        approved_count=approved_count,
        rejected_count=rejected_count,
        pending_count=pending_count,
    )


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
    parser.add_argument(
        "--candidate-source-json",
        "--candidate-source",
        dest="candidate_source_json",
        action="append",
        default=[],
        help="Trajectory export, replay report, or memory-context report to import candidates from. Repeatable.",
    )
    parser.add_argument(
        "--candidate-source-type",
        choices=sorted(_SOURCE_TYPES),
        default="auto",
        help="Type for --candidate-source files; auto detects each source by default.",
    )
    parser.add_argument(
        "--candidate-dataset-out",
        "--candidate-out",
        dest="candidate_dataset_out",
        help="Write imported candidate cases to this JSONL path. This never updates the golden dataset.",
    )
    parser.add_argument(
        "--candidate-id-prefix",
        default=DEFAULT_CANDIDATE_ID_PREFIX,
        help="Stable prefix for imported candidate ids.",
    )
    parser.add_argument(
        "--candidate-baseline-label",
        "--baseline-marker",
        dest="candidate_baseline_label",
        default="candidate",
        help="Stable baseline label stored in candidate origin metadata.",
    )
    parser.add_argument(
        "--candidate-review-jsonl",
        action="append",
        default=[],
        help="Candidate JSONL to review for explicit promotion. Repeatable.",
    )
    parser.add_argument(
        "--candidate-reviewed-out",
        help="Write reviewed candidate JSONL with explicit approval status metadata.",
    )
    parser.add_argument(
        "--candidate-promoted-out",
        help="Write approved candidate cases to this JSONL path. Never updates the golden dataset.",
    )
    parser.add_argument(
        "--candidate-approve-id",
        action="append",
        default=[],
        help="Candidate id to explicitly approve for promotion. Repeatable.",
    )
    parser.add_argument(
        "--candidate-reject-id",
        action="append",
        default=[],
        help="Candidate id to explicitly reject during review. Repeatable.",
    )
    parser.add_argument(
        "--candidate-approve-all",
        action="store_true",
        help="Explicitly approve every non-duplicate candidate that still has assertions.",
    )
    parser.add_argument(
        "--candidate-reviewer",
        help="Optional reviewer identifier stored in promotion_review metadata.",
    )
    parser.add_argument(
        "--candidate-review-note",
        help="Optional review note stored in promotion_review metadata.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.candidate_source_json and args.candidate_review_jsonl:
            raise ValueError("--candidate-source-json and --candidate-review-jsonl cannot be combined")
        if args.candidate_review_jsonl:
            if not args.candidate_reviewed_out and not args.candidate_promoted_out:
                raise ValueError(
                    "--candidate-reviewed-out or --candidate-promoted-out is required "
                    "when --candidate-review-jsonl is used"
                )
            if args.candidate_promoted_out and not (
                args.candidate_approve_all or args.candidate_approve_id
            ):
                raise ValueError(
                    "--candidate-promoted-out requires --candidate-approve-id "
                    "or --candidate-approve-all"
                )
            result = review_candidate_cases(
                args.candidate_review_jsonl,
                approved_ids=args.candidate_approve_id,
                rejected_ids=args.candidate_reject_id,
                approve_all=args.candidate_approve_all,
                reviewer=args.candidate_reviewer,
                note=args.candidate_review_note,
            )
            reviewed_target = None
            promoted_target = None
            if args.candidate_reviewed_out:
                _reject_golden_dataset_output(args.candidate_reviewed_out)
                reviewed_target = write_cases_jsonl(args.candidate_reviewed_out, result.reviewed_cases)
            if args.candidate_promoted_out:
                _reject_golden_dataset_output(args.candidate_promoted_out)
                promoted_target = write_cases_jsonl(args.candidate_promoted_out, result.promoted_cases)
            print(
                json.dumps(
                    result.to_dict(
                        reviewed_dataset=str(reviewed_target) if reviewed_target else None,
                        promoted_dataset=str(promoted_target) if promoted_target else None,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.candidate_source_json:
            if not args.candidate_dataset_out:
                raise ValueError(
                    "--candidate-dataset-out is required when --candidate-source-json is used"
                )
            result = import_candidate_cases(
                args.candidate_source_json,
                source_type=args.candidate_source_type,
                candidate_id_prefix=args.candidate_id_prefix,
                baseline_label=args.candidate_baseline_label,
            )
            _reject_golden_dataset_output(args.candidate_dataset_out)
            target = write_cases_jsonl(args.candidate_dataset_out, result.cases)
            print(json.dumps(result.to_dict(dataset=str(target)), ensure_ascii=False, indent=2))
            return 0
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
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _load_json_or_jsonl(path: Path) -> Any:
    source = path.expanduser()
    text = source.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        records: list[Any] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            candidate = line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            try:
                records.append(json.loads(candidate))
            except json.JSONDecodeError:
                try:
                    records.append(ast.literal_eval(candidate))
                except (SyntaxError, ValueError) as exc:
                    raise ValueError(f"{source}:{line_no} invalid JSON/JSONL: {exc}") from exc
        return records


def _resolve_candidate_source_type(payload: Any, *, source_type: str) -> str:
    if source_type != "auto":
        return source_type
    if isinstance(payload, dict):
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        suite = str(meta.get("suite") or payload.get("suite") or "").strip().lower()
        if "memory_context" in suite or "memory-context" in suite:
            return "memory-context"
        if "replay" in suite:
            return "replay"
        records = payload.get("results")
        if isinstance(records, list) and any(
            isinstance(record, dict) and "verdicts" in record for record in records
        ):
            return "memory-context"
        if any(key in payload for key in ("trajectory_id", "turns", "events", "messages")):
            return "trajectory"
    return "trajectory"


def _extract_candidate_records(payload: Any, *, source_type: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        preferred_keys = (
            ("results", "records", "items", "data", "candidates")
            if source_type in {"memory-context", "replay"}
            else ("turns", "events", "records", "items", "data", "results", "candidates")
        )
        for key in preferred_keys:
            records = payload.get(key)
            if isinstance(records, list):
                return [record for record in records if isinstance(record, dict)]
        if payload:
            return [payload]
    raise ValueError("unsupported candidate source payload")


def _candidate_record_to_case(
    record: dict[str, Any],
    *,
    source_path: Path,
    source_type: str,
    source_index: int,
    candidate_id_prefix: str,
    baseline_label: str,
) -> dict[str, Any] | None:
    replay_case = record.get("replay_case") if isinstance(record.get("replay_case"), dict) else {}
    eval_case = _first_mapping(record.get("case"), record.get("eval_case"), replay_case)
    input_payload = _first_mapping(record.get("input"), eval_case.get("input"))
    expected = _first_mapping(record.get("expected"), eval_case.get("expected"))
    context = _first_text(
        record.get("rendered_context"),
        record.get("context"),
        record.get("memory_context"),
        record.get("prompt_context"),
        record.get("selected_context"),
        input_payload.get("rendered_context"),
        input_payload.get("context"),
        input_payload.get("memory_context"),
        _nested_text(record, ("context_result", "rendered_context")),
    )
    answer = _first_text(
        record.get("answer"),
        record.get("output"),
        record.get("actual_answer"),
        record.get("replay_answer"),
        record.get("replay_answer_preview"),
        input_payload.get("answer"),
        _nested_text(record, ("replay_result", "answer")),
        _nested_text(record, ("response", "answer")),
        _nested_text(record, ("response", "content")),
    )
    converted_expected = _convert_expected(record, expected)
    if not _has_expected_assertions(converted_expected):
        return None

    bucket = _candidate_bucket(record, converted_expected)
    source_id = _first_text(
        record.get("case_id"),
        record.get("id"),
        record.get("candidate_id"),
        record.get("trajectory_id"),
        record.get("thread_id"),
        record.get("turn_id"),
        eval_case.get("id"),
        source_index,
    )
    case_payload = {"input": {"rendered_context": context, "answer": answer}, "expected": converted_expected}
    content_hash = _stable_hash(case_payload)[:12]
    source_slug = f"{_slug(source_type) or 'source'}-{source_index}-{_stable_hash(source_id)[:8]}"
    baseline_slug = _slug(baseline_label) or "candidate"
    tags = _dedupe_strings(
        [
            "memory_context",
            "candidate_import",
            f"source:{_slug(source_type)}",
            f"bucket:{_slug(bucket)}",
            f"baseline:{baseline_slug}",
            *_strings(record.get("tags") or eval_case.get("tags")),
        ]
    )
    return {
        "id": f"{_slug(candidate_id_prefix)}_{source_slug}_{content_hash}",
        "tags": tags,
        "input": case_payload["input"],
        "expected": converted_expected,
        "origin": {
            "type": "candidate_import",
            "baseline_label": baseline_label,
            "baseline_marker": f"baseline:{baseline_slug}",
            "source_type": source_type,
            "source_name": source_path.name,
            "source_record_id": source_id,
            "source_index": source_index,
            "bucket": bucket,
        },
    }


def _candidate_bucket(record: dict[str, Any], expected: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    explicit = _first_text(
        record.get("bucket"),
        record.get("bucket_name"),
        record.get("category"),
        record.get("kind"),
        metadata.get("bucket"),
    )
    if explicit:
        return _slug(explicit) or "general"
    if _strings(expected.get("artifact_refs")):
        return "artifact_ref"
    if _strings(expected.get("conflict_markers")):
        return "conflict"
    if _strings(expected.get("forbidden_facts")) or _strings(
        expected.get("forbidden_context_markers")
    ):
        return "pollution"
    if _strings(expected.get("required_context_markers")):
        return "context"
    if _strings(expected.get("answer_contains_all")):
        return "answerability"
    return "fact_recall"


def _candidate_dedupe_key(case: dict[str, Any]) -> str:
    return _stable_hash({"input": case.get("input"), "expected": case.get("expected")})


def _with_promotion_review(
    case: dict[str, Any],
    *,
    status: str,
    reason: str,
    reviewer: str | None,
    note: str | None,
) -> dict[str, Any]:
    reviewed_case = dict(case)
    review = {
        "status": status,
        "approved": status == "approved",
        "reason": reason,
    }
    if reviewer:
        review["reviewer"] = reviewer
    if note:
        review["note"] = note
    reviewed_case["promotion_review"] = _sanitize_json(review)
    return reviewed_case


def _reject_golden_dataset_output(path: str | Path) -> None:
    target = Path(path).expanduser()
    if target.resolve(strict=False) == DEFAULT_DATASET.resolve(strict=False):
        raise ValueError("candidate outputs must not target the golden memory/context dataset")


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(value: str) -> str:
    sanitized = _BEARER_TOKEN_RE.sub("Bearer [REDACTED_TOKEN]", value)
    sanitized = _JWT_RE.sub("[REDACTED_TOKEN]", sanitized)
    sanitized = _SECRET_ASSIGNMENT_RE.sub(_redact_secret_assignment, sanitized)
    sanitized = _TOKEN_LITERAL_RE.sub("[REDACTED_TOKEN]", sanitized)
    sanitized = _EMAIL_RE.sub("[REDACTED_EMAIL]", sanitized)
    return _PHONE_CANDIDATE_RE.sub(_redact_phone_like, sanitized)


def _redact_secret_assignment(match: re.Match[str]) -> str:
    quote = match.group("quote") or ""
    return f"{match.group('key')}{match.group('sep')}{quote}[REDACTED_SECRET]{quote}"


def _redact_phone_like(match: re.Match[str]) -> str:
    value = match.group(0)
    digits = re.sub(r"\D", "", value)
    if 10 <= len(digits) <= 15:
        return "[REDACTED_PHONE]"
    return value


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


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
