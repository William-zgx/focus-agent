#!/usr/bin/env python3
"""Run deterministic Memory / Context quality probes."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.memory_context_helpers import (  # noqa: E402
    _candidate_age_summary,
    _candidate_aging,
    _coerce_datetime,
    _contains,
    _dedupe_strings,
    _duplicate_reason,
    _empty_redaction_summary,
    _first_mapping,
    _first_text,
    _isoformat_z,
    _load_json_or_jsonl,
    _merge_redaction_summaries,
    _nested_text,
    _normalize_text,
    _promotion_sla_summary,
    _redaction_summary_payload,
    _sanitize_json,
    _sanitize_json_with_summary,
    _slug,
    _stable_hash,
    _strings,
    _with_privacy_summary,
)

DEFAULT_DATASET = REPO_ROOT / "tests" / "eval" / "datasets" / "memory_context_quality.jsonl"
DEFAULT_REPORT_JSON = Path("reports/release-gate/memory-context-eval.json")
DEFAULT_TREND_REPORT_JSON = Path("reports/release-gate/memory-context-trend.json")
DEFAULT_CANDIDATE_JSONL = Path("reports/nightly/memory-context-candidates.jsonl")
DEFAULT_REVIEWED_JSONL = Path("reports/nightly/memory-context-reviewed.jsonl")
DEFAULT_PROMOTED_JSONL = Path("reports/nightly/memory-context-promoted.jsonl")
DEFAULT_CANDIDATE_ID_PREFIX = "mc_candidate"
DEFAULT_PROMOTION_REVIEW_SLA_DAYS = 7
_PASS_STATUSES = {"pass", "passed", "success", "succeeded", "ok"}
_SOURCE_TYPES = {"auto", "trajectory", "replay", "memory-context"}
_CANDIDATE_TIME_KEYS = (
    "candidate_created_at",
    "created_at",
    "generated_at",
    "observed_at",
    "timestamp",
    "time",
    "started_at",
    "completed_at",
)


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
    duplicate_reasons: list[dict[str, Any]] = field(default_factory=list)
    pii_redaction_summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self, *, dataset: str | None = None) -> dict[str, Any]:
        payload = {
            "imported": len(self.cases),
            "sources": self.source_count,
            "records": self.record_count,
            "skipped_no_assertions": self.skipped_no_assertions,
            "skipped_duplicates": self.skipped_duplicates,
            "duplicate_reasons": list(self.duplicate_reasons),
            "pii_redaction_summary": _redaction_summary_payload(self.pii_redaction_summary),
            "candidate_age_summary": _candidate_age_summary(self.cases),
            "candidate_first_invariant": {
                "golden_dataset_unchanged": True,
                "requires_explicit_promotion_review": True,
            },
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
    duplicate_reasons: list[dict[str, Any]] = field(default_factory=list)
    pii_redaction_summary: dict[str, int] = field(default_factory=dict)

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
            "duplicate_reasons": list(self.duplicate_reasons),
            "pii_redaction_summary": _redaction_summary_payload(self.pii_redaction_summary),
            "promotion_sla_summary": _promotion_sla_summary(self.reviewed_cases),
            "candidate_first_invariant": {
                "golden_dataset_unchanged": True,
                "promoted_dataset_requires_explicit_approval": True,
            },
        }
        if reviewed_dataset is not None:
            payload["reviewed_dataset"] = reviewed_dataset
        if promoted_dataset is not None:
            payload["promoted_dataset"] = promoted_dataset
        return payload


@dataclass(frozen=True, slots=True)
class TrendStageSummary:
    name: str
    source_paths: list[str]
    total: int
    passed: int
    failed: int
    task_success: float
    pollution_rate: float
    context_compaction_drift_report: dict[str, Any]
    context_compaction_semantic_quality: float
    context_compaction_semantic_drift: float
    failed_case_ids: list[str]
    pollution_case_ids: list[str]
    review_status_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.name,
            "source_paths": list(self.source_paths),
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "task_success": self.task_success,
            "pollution_rate": self.pollution_rate,
            "context_compaction_drift_report": dict(self.context_compaction_drift_report),
            "context_compaction_semantic_quality": self.context_compaction_semantic_quality,
            "context_compaction_semantic_drift": self.context_compaction_semantic_drift,
            "failed_case_ids": list(self.failed_case_ids),
            "pollution_case_ids": list(self.pollution_case_ids),
            "review_status_counts": dict(self.review_status_counts),
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


def import_candidate_cases(
    sources: Sequence[str | Path],
    *,
    source_type: str = "auto",
    candidate_id_prefix: str = DEFAULT_CANDIDATE_ID_PREFIX,
    baseline_label: str = "candidate",
    baseline_marker: str | None = None,
    redact: bool = True,
    now: datetime | None = None,
    promotion_review_sla_days: int = DEFAULT_PROMOTION_REVIEW_SLA_DAYS,
) -> CandidateImportResult:
    """Import real-sample memory/context candidates from trajectory or report files."""
    if source_type not in _SOURCE_TYPES:
        raise ValueError(f"unsupported candidate source type: {source_type}")
    resolved_baseline_label = baseline_marker or baseline_label
    observed_now = _coerce_datetime(now) or datetime.now(UTC)

    cases: list[dict[str, Any]] = []
    dedupe_keys: dict[str, str] = {}
    duplicate_reasons: list[dict[str, Any]] = []
    pii_redaction_summary = _empty_redaction_summary()
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
                now=observed_now,
                promotion_review_sla_days=promotion_review_sla_days,
            )
            if case is None:
                skipped_no_assertions += 1
                continue
            if redact:
                case, redactions = _sanitize_json_with_summary(case)
            else:
                redactions = _empty_redaction_summary()
            pii_redaction_summary = _merge_redaction_summaries(pii_redaction_summary, redactions)
            case = _with_privacy_summary(case, redactions)
            dedupe_key = _candidate_dedupe_key(case)
            if dedupe_key in dedupe_keys:
                skipped_duplicates += 1
                duplicate_reasons.append(
                    _duplicate_reason(
                        case,
                        duplicate_of=dedupe_keys[dedupe_key],
                        dedupe_key=dedupe_key,
                        operation="candidate_import",
                    )
                )
                continue
            dedupe_keys[dedupe_key] = str(case.get("id") or f"candidate-{len(cases) + 1}")
            cases.append(case)

    return CandidateImportResult(
        cases=cases,
        source_count=len(sources),
        record_count=record_count,
        skipped_no_assertions=skipped_no_assertions,
        skipped_duplicates=skipped_duplicates,
        duplicate_reasons=duplicate_reasons,
        pii_redaction_summary=pii_redaction_summary,
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
    now: datetime | None = None,
    promotion_review_sla_days: int = DEFAULT_PROMOTION_REVIEW_SLA_DAYS,
) -> CandidatePromotionReviewResult:
    """Review imported candidates and return explicitly approved promotion cases."""
    approved_set = {str(case_id) for case_id in approved_ids if str(case_id)}
    rejected_set = {str(case_id) for case_id in rejected_ids if str(case_id)}
    conflicts = sorted(approved_set & rejected_set)
    if conflicts:
        raise ValueError(f"candidate ids cannot be both approved and rejected: {conflicts!r}")

    reviewed_cases: list[dict[str, Any]] = []
    promoted_cases: list[dict[str, Any]] = []
    dedupe_keys: dict[str, str] = {}
    duplicate_reasons: list[dict[str, Any]] = []
    pii_redaction_summary = _empty_redaction_summary()
    observed_now = _coerce_datetime(now) or datetime.now(UTC)
    record_count = 0
    skipped_no_assertions = 0
    skipped_duplicates = 0
    approved_count = 0
    rejected_count = 0
    pending_count = 0

    for source in candidate_jsonl:
        for case in load_dataset(source):
            record_count += 1
            if redact:
                candidate, redactions = _sanitize_json_with_summary(case)
            else:
                candidate = dict(case)
                redactions = _empty_redaction_summary()
            pii_redaction_summary = _merge_redaction_summaries(pii_redaction_summary, redactions)
            candidate = _with_privacy_summary(candidate, redactions)
            expected = (
                candidate.get("expected") if isinstance(candidate.get("expected"), dict) else {}
            )
            if not _has_expected_assertions(expected):
                skipped_no_assertions += 1
                continue
            dedupe_key = _candidate_dedupe_key(candidate)
            if dedupe_key in dedupe_keys:
                skipped_duplicates += 1
                duplicate_reasons.append(
                    _duplicate_reason(
                        candidate,
                        duplicate_of=dedupe_keys[dedupe_key],
                        dedupe_key=dedupe_key,
                        operation="candidate_review",
                    )
                )
                continue
            dedupe_keys[dedupe_key] = str(candidate.get("id") or f"candidate-{record_count}")

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

            if redact and (reviewer or note):
                _review_meta, review_redactions = _sanitize_json_with_summary(
                    {"reviewer": reviewer, "note": note}
                )
                pii_redaction_summary = _merge_redaction_summaries(
                    pii_redaction_summary,
                    review_redactions,
                )
            reviewed_case = _with_promotion_review(
                candidate,
                status=status,
                reason=reason,
                reviewer=reviewer,
                note=note,
                now=observed_now,
                promotion_review_sla_days=promotion_review_sla_days,
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
        duplicate_reasons=duplicate_reasons,
        pii_redaction_summary=pii_redaction_summary,
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
    context_grounding = 0.0 if missing_context or missing_artifacts else 1.0
    semantic_precision = 0.0 if polluted or stale_context else 1.0
    metrics = {
        "fact_fidelity": 0.0 if polluted else 1.0,
        "key_fact_recall": round(recall, 4),
        "irrelevant_memory_pollution": 1.0 if polluted or stale_context else 0.0,
        "conflict_memory_marked": 1.0 if conflict_markers and not missing_conflicts else 0.0,
        "compaction_answerable": 0.0 if missing_answer else 1.0,
        "artifact_refs_present": 0.0 if missing_artifacts else 1.0,
    }
    if _is_compaction_case(case_id=case_id, tags=tags, context=context):
        semantic_answerability = 0.0 if missing_answer or missing_facts else 1.0
        semantic_quality = (
            recall + semantic_precision + context_grounding + semantic_answerability
        ) / 4
        semantic_drift = 1.0 - semantic_quality
        metrics.update(
            {
                "context_compaction_semantic_recall": round(recall, 4),
                "context_compaction_semantic_precision": round(semantic_precision, 4),
                "context_compaction_semantic_grounding": round(context_grounding, 4),
                "context_compaction_semantic_answerability": round(semantic_answerability, 4),
                "context_compaction_semantic_quality": round(semantic_quality, 4),
                "context_compaction_semantic_drift": round(semantic_drift, 4),
                "context_compaction_drift_report": {
                    "recall": round(recall, 4),
                    "precision": round(semantic_precision, 4),
                    "grounding": round(context_grounding, 4),
                    "answerability": round(semantic_answerability, 4),
                    "overall_drift": round(semantic_drift, 4),
                    "drift_risk": _drift_risk(semantic_drift),
                },
            }
        )
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
        "context_compaction_semantic_recall",
        "context_compaction_semantic_precision",
        "context_compaction_semantic_grounding",
        "context_compaction_semantic_answerability",
        "context_compaction_semantic_quality",
        "context_compaction_semantic_drift",
    )
    averages = {name: _average_metric(results, name) for name in metric_names}
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
        "context_compaction_drift_report": _aggregate_compaction_drift_reports(results),
        "failed_case_ids": [result.case_id for result in results if not result.passed],
    }


def build_memory_regression_trend_report(
    *,
    candidate_jsonl: Sequence[str | Path] = (),
    reviewed_jsonl: Sequence[str | Path] = (),
    promoted_jsonl: Sequence[str | Path] = (),
    golden_jsonl: Sequence[str | Path] = (DEFAULT_DATASET,),
) -> dict[str, Any]:
    """Summarize candidate/reviewed/promoted/golden quality without mutating datasets."""
    stages = [
        _build_trend_stage_summary("candidate", candidate_jsonl),
        _build_trend_stage_summary("reviewed", reviewed_jsonl),
        _build_trend_stage_summary("promoted", promoted_jsonl),
        _build_trend_stage_summary("golden", golden_jsonl),
    ]
    alerts = _build_pollution_alerts(stages)
    return {
        "meta": {
            "suite": "memory_context_regression_trend",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "golden_dataset": str(Path(golden_jsonl[0])) if golden_jsonl else None,
        },
        "stages": {stage.name: stage.to_dict() for stage in stages},
        "trend": [
            {
                "stage": stage.name,
                "total": stage.total,
                "task_success": stage.task_success,
                "pollution_rate": stage.pollution_rate,
                "context_compaction_drift_report": dict(stage.context_compaction_drift_report),
                "context_compaction_semantic_quality": stage.context_compaction_semantic_quality,
                "context_compaction_semantic_drift": stage.context_compaction_semantic_drift,
            }
            for stage in stages
        ],
        "promotion_history": {
            "candidate_total": stages[0].total,
            "reviewed_total": stages[1].total,
            "promoted_total": stages[2].total,
            "golden_total": stages[3].total,
            "review_status_counts": dict(stages[1].review_status_counts),
            "promoted_case_ids": _load_stage_case_ids(promoted_jsonl),
        },
        "pollution_alerts": alerts,
        "status": "alert" if alerts else "ok",
    }


def write_trend_report(
    path: str | Path,
    *,
    candidate_jsonl: Sequence[str | Path] = (),
    reviewed_jsonl: Sequence[str | Path] = (),
    promoted_jsonl: Sequence[str | Path] = (),
    golden_jsonl: Sequence[str | Path] = (DEFAULT_DATASET,),
) -> Path:
    _reject_golden_dataset_output(path, operation="trend reports")
    target = Path(path)
    if not target.is_absolute():
        target = REPO_ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_memory_regression_trend_report(
        candidate_jsonl=candidate_jsonl,
        reviewed_jsonl=reviewed_jsonl,
        promoted_jsonl=promoted_jsonl,
        golden_jsonl=golden_jsonl,
    )
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def existing_default_pipeline_jsonl() -> dict[str, list[Path]]:
    """Return default nightly candidate pipeline JSONL artifacts that exist."""
    return {
        "candidate": _existing_paths(DEFAULT_CANDIDATE_JSONL),
        "reviewed": _existing_paths(DEFAULT_REVIEWED_JSONL),
        "promoted": _existing_paths(DEFAULT_PROMOTED_JSONL),
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
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def run(
    dataset: str | Path = DEFAULT_DATASET, *, report_json: str | Path = DEFAULT_REPORT_JSON
) -> dict[str, Any]:
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
    parser.add_argument(
        "--dataset", default=str(DEFAULT_DATASET), help="Memory/context quality JSONL dataset."
    )
    parser.add_argument(
        "--report-json", default=str(DEFAULT_REPORT_JSON), help="Structured JSON report path."
    )
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
        help=(
            "Write imported candidate cases to this JSONL path. Defaults to "
            f"{DEFAULT_CANDIDATE_JSONL}. This never updates the golden dataset."
        ),
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
        help=(
            "Write reviewed candidate JSONL with explicit approval status metadata. "
            f"Defaults to {DEFAULT_REVIEWED_JSONL}."
        ),
    )
    parser.add_argument(
        "--candidate-promoted-out",
        help=(
            "Write approved candidate cases to this JSONL path. Defaults to "
            f"{DEFAULT_PROMOTED_JSONL}; without explicit approvals this is an empty JSONL. "
            "Never updates the golden dataset."
        ),
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
    parser.add_argument(
        "--candidate-review-sla-days",
        type=int,
        default=DEFAULT_PROMOTION_REVIEW_SLA_DAYS,
        help="Review SLA, in days, for candidate promotion metadata.",
    )
    parser.add_argument(
        "--trend-report-json",
        help="Write Memory Regression Dashboard trend JSON to this path.",
    )
    parser.add_argument(
        "--trend-candidate-jsonl",
        action="append",
        default=[],
        help="Candidate JSONL dataset for trend reporting. Repeatable.",
    )
    parser.add_argument(
        "--trend-reviewed-jsonl",
        action="append",
        default=[],
        help="Reviewed candidate JSONL dataset for trend reporting. Repeatable.",
    )
    parser.add_argument(
        "--trend-promoted-jsonl",
        action="append",
        default=[],
        help="Promoted candidate JSONL dataset for trend reporting. Repeatable.",
    )
    parser.add_argument(
        "--trend-golden-jsonl",
        action="append",
        default=[],
        help="Golden Memory/Context JSONL dataset for trend reporting. Defaults to --dataset.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.candidate_source_json and args.candidate_review_jsonl:
            raise ValueError(
                "--candidate-source-json and --candidate-review-jsonl cannot be combined"
            )
        if (
            args.trend_report_json
            or args.trend_candidate_jsonl
            or args.trend_reviewed_jsonl
            or args.trend_promoted_jsonl
            or args.trend_golden_jsonl
        ):
            default_pipeline = existing_default_pipeline_jsonl()
            target = write_trend_report(
                args.trend_report_json or DEFAULT_TREND_REPORT_JSON,
                candidate_jsonl=args.trend_candidate_jsonl or default_pipeline["candidate"],
                reviewed_jsonl=args.trend_reviewed_jsonl or default_pipeline["reviewed"],
                promoted_jsonl=args.trend_promoted_jsonl or default_pipeline["promoted"],
                golden_jsonl=args.trend_golden_jsonl or (args.dataset,),
            )
            payload = json.loads(Path(target).read_text(encoding="utf-8"))
            print(
                json.dumps(
                    {
                        "status": payload["status"],
                        "trend_report_json": str(target),
                        "pollution_alerts": len(payload["pollution_alerts"]),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if payload["status"] == "ok" else 1
        if args.candidate_review_jsonl:
            result = review_candidate_cases(
                args.candidate_review_jsonl,
                approved_ids=args.candidate_approve_id,
                rejected_ids=args.candidate_reject_id,
                approve_all=args.candidate_approve_all,
                reviewer=args.candidate_reviewer,
                note=args.candidate_review_note,
                promotion_review_sla_days=args.candidate_review_sla_days,
            )
            reviewed_out = args.candidate_reviewed_out or DEFAULT_REVIEWED_JSONL
            promoted_out = args.candidate_promoted_out or DEFAULT_PROMOTED_JSONL
            _reject_golden_dataset_output(reviewed_out, golden_dataset=args.dataset)
            _reject_golden_dataset_output(promoted_out, golden_dataset=args.dataset)
            reviewed_target = write_cases_jsonl(reviewed_out, result.reviewed_cases)
            promoted_target = write_cases_jsonl(promoted_out, result.promoted_cases)
            print(
                json.dumps(
                    result.to_dict(
                        reviewed_dataset=str(reviewed_target),
                        promoted_dataset=str(promoted_target),
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.candidate_source_json:
            result = import_candidate_cases(
                args.candidate_source_json,
                source_type=args.candidate_source_type,
                candidate_id_prefix=args.candidate_id_prefix,
                baseline_label=args.candidate_baseline_label,
                promotion_review_sla_days=args.candidate_review_sla_days,
            )
            candidate_out = args.candidate_dataset_out or DEFAULT_CANDIDATE_JSONL
            _reject_golden_dataset_output(candidate_out, golden_dataset=args.dataset)
            target = write_cases_jsonl(candidate_out, result.cases)
            print(json.dumps(result.to_dict(dataset=str(target)), ensure_ascii=False, indent=2))
            return 0
        if args.convert_failures_json:
            cases = convert_failure_report_to_cases(args.convert_failures_json)
            if args.converted_dataset_out:
                target = write_cases_jsonl(args.converted_dataset_out, cases)
                print(json.dumps({"converted": len(cases), "dataset": str(target)}, indent=2))
            else:
                print(
                    json.dumps(
                        {"converted": len(cases), "cases": cases}, ensure_ascii=False, indent=2
                    )
                )
            return 0
        result = run(dataset=args.dataset, report_json=args.report_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[memory-context-eval] {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "report_json": result["report_json"]}, indent=2))
    return 0 if result["status"] == "passed" else 1


def _existing_paths(*paths: str | Path) -> list[Path]:
    existing: list[Path] = []
    for path in paths:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = REPO_ROOT / target
        if target.exists():
            existing.append(target)
    return existing


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
    now: datetime,
    promotion_review_sla_days: int,
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
    case_payload = {
        "input": {"rendered_context": context, "answer": answer},
        "expected": converted_expected,
    }
    content_hash = _stable_hash(case_payload)[:12]
    source_slug = f"{_slug(source_type) or 'source'}-{source_index}-{_stable_hash(source_id)[:8]}"
    baseline_slug = _slug(baseline_label) or "candidate"
    source_observed_at = _candidate_source_observed_at(record, source_path=source_path, now=now)
    aging = _candidate_aging(
        source_observed_at,
        now=now,
        promotion_review_sla_days=promotion_review_sla_days,
    )
    source_explanation = _candidate_source_explanation(
        source_type=source_type,
        source_name=source_path.name,
        source_record_id=source_id,
        bucket=bucket,
        expected=converted_expected,
    )
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
            "source_explanation": source_explanation,
        },
        "candidate_ops": {
            "candidate_age_days": aging["age_days"],
            "candidate_age_bucket": aging["age_bucket"],
            "candidate_created_at": _isoformat_z(source_observed_at),
            "source_explanation": source_explanation,
            "promotion_review_sla": aging["promotion_review_sla"],
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


def _candidate_source_explanation(
    *,
    source_type: str,
    source_name: str,
    source_record_id: str,
    bucket: str,
    expected: dict[str, Any],
) -> dict[str, Any]:
    assertion_fields = [key for key, value in expected.items() if _strings(value)]
    return {
        "summary": (
            f"Imported {source_type} record {source_record_id} from {source_name} "
            f"as a {bucket} memory/context candidate."
        ),
        "reason": "record contains explicit memory/context assertions and remains candidate-only until review",
        "assertion_fields": assertion_fields,
        "selected_bucket": bucket,
    }


def _candidate_source_observed_at(
    record: dict[str, Any],
    *,
    source_path: Path,
    now: datetime,
) -> datetime:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for key in _CANDIDATE_TIME_KEYS:
        parsed = _coerce_datetime(record.get(key))
        if parsed is not None:
            return parsed
        parsed = _coerce_datetime(metadata.get(key))
        if parsed is not None:
            return parsed
    try:
        return datetime.fromtimestamp(source_path.stat().st_mtime, tz=UTC)
    except OSError:
        return now


def _candidate_dedupe_key(case: dict[str, Any]) -> str:
    return _stable_hash({"input": case.get("input"), "expected": case.get("expected")})


def _with_promotion_review(
    case: dict[str, Any],
    *,
    status: str,
    reason: str,
    reviewer: str | None,
    note: str | None,
    now: datetime,
    promotion_review_sla_days: int,
) -> dict[str, Any]:
    reviewed_case = dict(case)
    sla = _promotion_review_sla_for_case(
        reviewed_case,
        now=now,
        promotion_review_sla_days=promotion_review_sla_days,
    )
    review = {
        "status": status,
        "approved": status == "approved",
        "reason": reason,
        "reviewed_at": _isoformat_z(now),
        "sla": sla,
    }
    if reviewer:
        review["reviewer"] = reviewer
    if note:
        review["note"] = note
    reviewed_case["promotion_review"] = _sanitize_json(review)
    return reviewed_case


def _promotion_review_sla_for_case(
    case: dict[str, Any],
    *,
    now: datetime,
    promotion_review_sla_days: int,
) -> dict[str, Any]:
    candidate_ops = case.get("candidate_ops") if isinstance(case.get("candidate_ops"), dict) else {}
    existing_sla = (
        candidate_ops.get("promotion_review_sla")
        if isinstance(candidate_ops.get("promotion_review_sla"), dict)
        else {}
    )
    candidate_created_at = _coerce_datetime(
        existing_sla.get("candidate_created_at")
        or candidate_ops.get("candidate_created_at")
        or _nested_text(case, ("origin", "candidate_created_at"))
    )
    if candidate_created_at is None:
        candidate_created_at = now
    sla_days = int(existing_sla.get("sla_days") or promotion_review_sla_days)
    aging = _candidate_aging(candidate_created_at, now=now, promotion_review_sla_days=sla_days)
    sla = dict(aging["promotion_review_sla"])
    sla["reviewed_at"] = _isoformat_z(now)
    sla["reviewed_after_due"] = bool(sla["overdue"])
    return sla


def _reject_golden_dataset_output(
    path: str | Path,
    *,
    operation: str = "candidate outputs",
    golden_dataset: str | Path = DEFAULT_DATASET,
) -> None:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = REPO_ROOT / target
    golden = Path(golden_dataset).expanduser()
    if not golden.is_absolute():
        golden = REPO_ROOT / golden
    if target.resolve(strict=False) in {
        DEFAULT_DATASET.resolve(strict=False),
        golden.resolve(strict=False),
    }:
        raise ValueError(f"{operation} must not target the golden memory/context dataset")


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

    source_id = str(
        record.get("case_id") or record.get("id") or record.get("trajectory_id") or index
    )
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
            expected.get("forbidden_facts")
            or record.get("forbidden_facts")
            or record.get("leaked_facts")
        ),
        "required_context_markers": _strings(expected.get("required_context_markers")),
        "forbidden_context_markers": _strings(expected.get("forbidden_context_markers")),
        "artifact_refs": _strings(
            expected.get("artifact_refs")
            or record.get("artifact_refs")
            or record.get("missing_artifact_refs")
        ),
        "conflict_markers": _strings(
            expected.get("conflict_markers") or record.get("conflict_markers")
        ),
        "answer_contains_all": _strings(
            expected.get("answer_contains_all") or record.get("answer_contains_all")
        ),
    }


def _has_expected_assertions(expected: dict[str, Any]) -> bool:
    return any(_strings(value) for value in expected.values())


def _average_metric(results: Sequence[ProbeResult], name: str) -> float:
    values = [float(result.metrics[name]) for result in results if name in result.metrics]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _aggregate_compaction_drift_reports(results: Sequence[ProbeResult]) -> dict[str, Any]:
    reports = [
        result.metrics["context_compaction_drift_report"]
        for result in results
        if isinstance(result.metrics.get("context_compaction_drift_report"), dict)
    ]
    if not reports:
        return {
            "recall": 1.0,
            "precision": 1.0,
            "grounding": 1.0,
            "answerability": 1.0,
            "overall_drift": 0.0,
            "drift_risk": "low",
            "case_count": 0,
        }
    averaged = {
        key: round(sum(float(report.get(key) or 0.0) for report in reports) / len(reports), 4)
        for key in ("recall", "precision", "grounding", "answerability", "overall_drift")
    }
    return {
        **averaged,
        "drift_risk": _drift_risk(float(averaged["overall_drift"])),
        "case_count": len(reports),
    }


def _drift_risk(overall_drift: float) -> str:
    if overall_drift >= 0.34:
        return "high"
    if overall_drift > 0.0:
        return "medium"
    return "low"


def _is_compaction_case(*, case_id: str, tags: Sequence[str], context: str) -> bool:
    normalized_tags = {_slug(tag) for tag in tags}
    normalized_id = _slug(case_id)
    return (
        "compaction" in normalized_id
        or "context-compaction" in normalized_tags
        or "compaction" in normalized_tags
        or "context_compaction" in normalized_tags
        or "rolling_summary" in _normalize_text(context)
    )


def _build_trend_stage_summary(
    name: str,
    source_paths: Sequence[str | Path],
) -> TrendStageSummary:
    cases: list[dict[str, Any]] = []
    resolved_paths = [str(Path(path)) for path in source_paths]
    for path in source_paths:
        cases.extend(load_dataset(path))

    results = [evaluate_case(case) for case in cases]
    summary = build_summary(results)
    pollution_case_ids = [
        result.case_id
        for result in results
        if float(result.metrics.get("irrelevant_memory_pollution", 0.0)) > 0.0
    ]
    review_status_counts: dict[str, int] = {}
    for case in cases:
        review = case.get("promotion_review")
        if not isinstance(review, dict):
            continue
        status = str(review.get("status") or "unknown")
        review_status_counts[status] = review_status_counts.get(status, 0) + 1

    return TrendStageSummary(
        name=name,
        source_paths=resolved_paths,
        total=summary["total"],
        passed=summary["passed"],
        failed=summary["failed"],
        task_success=summary["task_success"],
        pollution_rate=summary["irrelevant_memory_pollution"],
        context_compaction_drift_report=summary["context_compaction_drift_report"],
        context_compaction_semantic_quality=summary["context_compaction_semantic_quality"],
        context_compaction_semantic_drift=summary["context_compaction_semantic_drift"],
        failed_case_ids=summary["failed_case_ids"],
        pollution_case_ids=pollution_case_ids,
        review_status_counts=review_status_counts,
    )


def _build_pollution_alerts(stages: Sequence[TrendStageSummary]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for stage in stages:
        if stage.pollution_case_ids:
            alerts.append(
                {
                    "stage": stage.name,
                    "kind": "irrelevant_memory_pollution",
                    "severity": "error",
                    "rate": stage.pollution_rate,
                    "case_ids": list(stage.pollution_case_ids),
                }
            )
        if stage.context_compaction_semantic_drift > 0.0:
            alerts.append(
                {
                    "stage": stage.name,
                    "kind": "context_compaction_semantic_drift",
                    "severity": "warning",
                    "rate": stage.context_compaction_semantic_drift,
                    "case_ids": list(stage.failed_case_ids),
                }
            )
    return alerts


def _load_stage_case_ids(source_paths: Sequence[str | Path]) -> list[str]:
    case_ids: list[str] = []
    for path in source_paths:
        for case in load_dataset(path):
            case_ids.append(str(case.get("id") or "unknown"))
    return case_ids


if __name__ == "__main__":
    raise SystemExit(main())
