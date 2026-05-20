"""Candidate import and promotion helpers for memory/context eval."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "tests" / "eval" / "datasets" / "memory_context_quality.jsonl"
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

from scripts.memory_context_helpers import (  # noqa: E402
    _candidate_age_summary,
    _candidate_aging,
    _coerce_datetime,
    _dedupe_strings,
    _duplicate_reason,
    _empty_redaction_summary,
    _first_mapping,
    _first_text,
    _isoformat_z,
    _load_json_or_jsonl,
    _merge_redaction_summaries,
    _nested_text,
    _promotion_sla_summary,
    _redaction_summary_payload,
    _sanitize_json,
    _sanitize_json_with_summary,
    _slug,
    _stable_hash,
    _strings,
    _with_privacy_summary,
)


def _load_dataset(path: str | Path) -> list[dict[str, Any]]:
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
        for case in _load_dataset(source):
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
