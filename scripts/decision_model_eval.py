#!/usr/bin/env python3
"""Run isolated, provider-backed branch recommendation evaluation.

The runner deliberately exercises ``BranchDecisionService.recommend_for_message``
with an in-memory graph and governance repository. It does not create or navigate
real branches. Provider failures, fallback attempts, raw classifier output, and
the final business-gated action are recorded separately.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain.messages import AIMessage, HumanMessage

from focus_agent.branch_decision import BranchDecisionService
from focus_agent.branch_decision.scorers import score_branch_recommendation
from focus_agent.branch_decision.service_helpers import _should_run_semantic_topic_relation
from focus_agent.branch_decision.signals import collect_branch_recommendation_signals
from focus_agent.config import (
    ConfiguredModel,
    ProviderConfig,
    Settings,
    load_local_env_file,
)
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.services.coordination import create_in_memory_coordination_backend

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "tests" / "eval" / "datasets" / "branch_decision_models.json"
DEFAULT_OUTPUT = Path("decision-model-eval.json")
PRIMARY_FAILURE_BASE_URL = "http://127.0.0.1:1/v1"
CODIV_BASE_URL = "https://api.codiv.ai/v1"
GATE_CONFIDENCE = 0.9
STANDARD_MODEL_IDS = ("deepseek:deepseek-v4-pro", "codiv:openjev-0.1")


class _Graph:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = copy.deepcopy(values)

    def get_state(self, _config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(values=copy.deepcopy(self.values), interrupts=[])

    def update_state(
        self,
        _config: dict[str, Any],
        values: dict[str, Any],
        as_node: str | None = None,
    ) -> None:
        del as_node
        self.values.update(copy.deepcopy(values))


class _BranchRepo:
    def assert_thread_owner(self, *, thread_id: str, owner_user_id: str) -> None:
        del thread_id, owner_user_id


class _BranchService:
    def __init__(self) -> None:
        self.repo = _BranchRepo()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DATASET_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--progress-log",
        help="Optional JSONL file receiving one sanitized record per completed case.",
    )
    parser.add_argument("--local-env-file", default=".focus_agent/local.env")
    parser.add_argument("--model-catalog", default=".focus_agent/models.toml")
    parser.add_argument(
        "--codiv-key-file",
        default="~/.config/focus-agent/codiv-api-key",
    )
    parser.add_argument("--max-cases", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--only-model", choices=STANDARD_MODEL_IDS)
    parser.add_argument(
        "--include-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the two dataset cases that inject a local primary endpoint failure.",
    )
    return parser.parse_args(argv)


@contextmanager
def _isolated_environment(values: dict[str, str]) -> Iterator[None]:
    original = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(values)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"branch decision dataset must be a non-empty list: {path}")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("branch decision dataset entries must be objects")
        case_id = str(raw.get("id") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError(f"duplicate or missing case id: {case_id!r}")
        for field in ("history", "incoming", "expected_action", "expected_model_action"):
            if field not in raw:
                raise ValueError(f"{case_id}: missing {field}")
        if raw["expected_action"] not in {
            "continue_current",
            "fork_child_branch",
            "fork_sibling_branch",
        }:
            raise ValueError(f"{case_id}: invalid expected_action")
        if raw.get("expected_classifier") not in {"run", "bypass"}:
            raise ValueError(f"{case_id}: expected_classifier must be run or bypass")
        seen.add(case_id)
        cases.append(dict(raw))
    return cases


def _read_provider_environment(
    *,
    local_env_path: Path,
    model_catalog_path: Path,
    codiv_key_path: Path,
) -> dict[str, str]:
    if not local_env_path.is_file():
        raise FileNotFoundError(f"local environment file is missing: {local_env_path}")
    environment: dict[str, str] = {}
    load_local_env_file(local_env_path, environ=environment)
    if not model_catalog_path.is_file():
        raise FileNotFoundError(f"model catalog is missing: {model_catalog_path}")
    if not codiv_key_path.is_file():
        raise FileNotFoundError(f"Codiv key file is missing: {codiv_key_path}")
    codiv_key = codiv_key_path.read_text(encoding="utf-8").strip()
    if not codiv_key:
        raise ValueError("Codiv key file is empty")
    environment.update(
        {
            "FOCUS_AGENT_LOCAL_ENV_FILE": str(local_env_path.resolve()),
            "FOCUS_AGENT_MODEL_CATALOG_DOC": str(model_catalog_path.resolve()),
            "CODIV_API_KEY": codiv_key,
        }
    )
    return environment


def _settings_for_run(
    *,
    primary_model: str,
    fallback_model: str | None,
    timeout_seconds: float,
    failure_injection: bool,
    local_env_path: Path,
    model_catalog_path: Path,
    codiv_key_path: Path,
) -> Settings:
    environment = _read_provider_environment(
        local_env_path=local_env_path,
        model_catalog_path=model_catalog_path,
        codiv_key_path=codiv_key_path,
    )
    if failure_injection:
        provider_id = primary_model.partition(":")[0]
        environment[f"{provider_id.upper()}_BASE_URL"] = PRIMARY_FAILURE_BASE_URL
    with _isolated_environment(environment):
        settings = Settings.from_env()

    catalog = settings.model_catalog
    providers = list(catalog.providers)
    models = list(catalog.models)
    if not any(provider.id == "codiv" for provider in providers):
        providers.append(
            ProviderConfig(
                id="codiv",
                label="Codiv",
                backend_provider="openai",
                base_url_env="CODIV_BASE_URL",
                base_url_default=CODIV_BASE_URL,
                api_key_env="CODIV_API_KEY",
            )
        )
    if not any(model.id == "codiv:openjev-0.1" for model in models):
        models.append(
            ConfiguredModel(id="codiv:openjev-0.1", label="OpenJev", protocol="system_one")
        )
    settings.model_catalog = replace(
        catalog,
        providers=tuple(providers),
        models=tuple(models),
    )
    settings.model = primary_model
    settings.agent_branch_recommendation_enabled = True
    settings.agent_branch_recommendation_semantic_enabled = True
    settings.agent_branch_recommendation_mode = "suggest"
    settings.agent_branch_recommendation_min_confidence = 0.72
    settings.agent_branch_recommendation_semantic_model = primary_model
    settings.agent_branch_recommendation_semantic_fallback_model = fallback_model
    settings.agent_branch_recommendation_semantic_decision_min_confidence = GATE_CONFIDENCE
    settings.agent_branch_recommendation_timeout_seconds = timeout_seconds
    settings.resolved_env = environment
    return settings


def _message_history(case: dict[str, Any]) -> list[Any]:
    messages: list[Any] = []
    for raw in list(case.get("history") or []):
        if not isinstance(raw, dict):
            raise ValueError(f"{case['id']}: history entries must be objects")
        role = str(raw.get("role") or "user").strip().lower()
        content = str(raw.get("content") or "")
        messages.append(
            AIMessage(content=content)
            if role in {"assistant", "ai"}
            else HumanMessage(content=content)
        )
    return messages


def _initial_values(case: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {"messages": _message_history(case)}
    branch_context = case.get("branch_context")
    if isinstance(branch_context, dict):
        values["branch_meta"] = copy.deepcopy(branch_context)
    return values


def _pre_rule_observation(
    *,
    case: dict[str, Any],
) -> tuple[dict[str, Any], str, bool]:
    branch_context = case.get("branch_context")
    values = _initial_values(case)
    signals = collect_branch_recommendation_signals(
        message=str(case["incoming"]),
        values=values,
        branch_meta=None if branch_context is None else _branch_meta_from_dict(branch_context),
    )
    score = score_branch_recommendation(signals=signals, min_confidence=0.72)
    should_run = _should_run_semantic_topic_relation(signals=signals, action=score.action)
    signal_map = {signal.name: signal.value for signal in signals}
    return signal_map, score.action.value, should_run


def _branch_meta_from_dict(raw: dict[str, Any]) -> Any:
    from focus_agent.core.branching import BranchMeta

    return BranchMeta.model_validate(raw)


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _event_signal(event: Any, name: str) -> dict[str, Any]:
    for signal in list(getattr(event, "signals", []) or []):
        if getattr(signal, "name", None) == name:
            value = getattr(signal, "value", {})
            return dict(value) if isinstance(value, dict) else {}
    return {}


def _attempt_ok(attempt: dict[str, Any]) -> bool:
    return str(attempt.get("status") or "").strip().lower() in {
        "ok",
        "success",
        "disabled",
    }


def _attempt_failure(attempt: dict[str, Any]) -> bool:
    return not _attempt_ok(attempt)


def _attempt_error_records(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "model": attempt.get("model"),
            "protocol": attempt.get("protocol"),
            "status": attempt.get("status"),
            "error_type": attempt.get("error_type"),
            "http_status": attempt.get("http_status"),
        }
        for attempt in attempts
        if _attempt_failure(attempt)
    ]


def _run_case(
    *,
    case: dict[str, Any],
    primary_model: str,
    fallback_model: str | None,
    timeout_seconds: float,
    failure_injection: bool,
    local_env_path: Path,
    model_catalog_path: Path,
    codiv_key_path: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    pre_signals, pre_rule_action, should_run = _pre_rule_observation(case=case)
    record: dict[str, Any] = {
        "case_id": case["id"],
        "category": case.get("category"),
        "primary_model": primary_model,
        "fallback_model": fallback_model,
        "failure_injection": failure_injection,
        "expected_action": case["expected_action"],
        "expected_model_action": case["expected_model_action"],
        "expected_classifier": case["expected_classifier"],
        "pre_rule_action": pre_rule_action,
        "pre_rule_signals": {
            "explicit_source": pre_signals.get("recommendation_explicit_source"),
            "topic_drift": pre_signals.get("recommendation_topic_drift"),
            "has_history_context": (pre_signals.get("pre_turn_message_shape") or {}).get(
                "has_history_context"
            ),
        },
        "semantic_expected_to_run": should_run,
        "classifier_bypassed": not should_run,
        "classifier_bypass_matches_expected": (not should_run)
        == (case["expected_classifier"] == "bypass"),
    }
    try:
        settings = _settings_for_run(
            primary_model=primary_model,
            fallback_model=fallback_model,
            timeout_seconds=timeout_seconds,
            failure_injection=failure_injection,
            local_env_path=local_env_path,
            model_catalog_path=model_catalog_path,
            codiv_key_path=codiv_key_path,
        )
        graph = _Graph(_initial_values(case))
        repository = InMemoryGovernanceRepository()
        service = BranchDecisionService(
            settings=settings,
            graph=graph,
            governance_repository=repository,
            branch_service=_BranchService(),
            coordination_backend=create_in_memory_coordination_backend(),
        )
        service.recommend_for_message(
            thread_id="eval-thread",
            root_thread_id="eval-root",
            user_id="eval-user",
            message=str(case["incoming"]),
            request_id=f"decision-eval:{case['id']}:{primary_model}",
        )
        events = repository.list_branch_decision_events(source_thread_id="eval-thread")
        if not events:
            raise RuntimeError("recommendation did not persist an event")
        event = events[0]
        semantic = _event_signal(event, "semantic_topic_relation")
        diagnostics = semantic.get("diagnostics") if isinstance(semantic, dict) else {}
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        attempts = [
            item for item in list(diagnostics.get("attempts") or []) if isinstance(item, dict)
        ]
        attempt_errors = _attempt_error_records(attempts)
        raw_action = str(semantic.get("recommended_action") or "continue_current")
        raw_confidence = _float_or_none(semantic.get("confidence")) or 0.0
        semantic_status = str(semantic.get("status") or "not_run")
        final_action = getattr(event.action, "value", str(event.action))
        gate_positive = (
            semantic_status in {"ok", "success"}
            and raw_action != "continue_current"
            and raw_confidence >= GATE_CONFIDENCE
        )
        expected_positive = case["expected_model_action"] != "continue_current"
        final_attempt_ok = bool(attempts) and _attempt_ok(attempts[-1])
        request_failure = semantic_status in {"error", "request_failed"} or bool(
            attempts and not final_attempt_ok
        )
        record.update(
            {
                "semantic_status": semantic_status,
                "raw_classifier_action": raw_action,
                "raw_classifier_confidence": raw_confidence,
                "raw_classifier_probabilities": diagnostics.get("probabilities"),
                "response_model": diagnostics.get("response_model"),
                "attempts": attempts,
                "fallback_used": bool(diagnostics.get("fallback_used")),
                "request_failure": request_failure,
                "attempt_failures": len(attempt_errors),
                "first_attempt_errors": attempt_errors[:1],
                "fallback_recovered": bool(attempt_errors and final_attempt_ok),
                "final_business_action": final_action,
                "event_status": getattr(event.status, "value", str(event.status)),
                "event_score": float(event.score),
                "event_gate_reason": (event.metadata.get("diagnostic") or {}).get("gate_reason"),
                "business_action_match": final_action == case["expected_action"],
                "raw_semantic_match": (
                    semantic_status in {"ok", "success"}
                    and raw_action == case["expected_model_action"]
                ),
                "gate_positive": gate_positive,
                "expected_positive": expected_positive,
                "gated_prediction_match": gate_positive == expected_positive,
            }
        )
    except Exception as exc:  # noqa: BLE001 - report provider/config failures without secrets.
        record.update(
            {
                "semantic_status": "request_failed",
                "request_failure": True,
                "error_type": type(exc).__name__,
                "error_status": getattr(exc, "status_code", None),
                "attempt_failures": 1,
                "first_attempt_errors": [
                    {
                        "model": primary_model,
                        "protocol": None,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "http_status": getattr(exc, "status_code", None),
                    }
                ],
                "fallback_recovered": False,
                "business_action_match": False,
                "raw_semantic_match": False,
                "gate_positive": False,
                "expected_positive": case["expected_model_action"] != "continue_current",
                "gated_prediction_match": False,
            }
        )
    record["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    return record


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    population = list(records)
    semantic_attempts = [record for record in population if record.get("semantic_expected_to_run")]
    semantic = [
        record for record in semantic_attempts if record.get("semantic_status") in {"ok", "success"}
    ]
    gate_records = [
        record for record in semantic if record.get("semantic_status") in {"ok", "success"}
    ]
    true_positive = sum(bool(r["expected_positive"] and r["gate_positive"]) for r in gate_records)
    false_positive = sum(
        bool(not r["expected_positive"] and r["gate_positive"]) for r in gate_records
    )
    false_negative = sum(
        bool(r["expected_positive"] and not r["gate_positive"]) for r in gate_records
    )
    true_negative = sum(
        bool(not r["expected_positive"] and not r["gate_positive"]) for r in gate_records
    )
    request_failures = sum(bool(record.get("request_failure")) for record in records)
    attempt_failures = sum(int(record.get("attempt_failures") or 0) for record in records)
    fallback_recoveries = sum(bool(record.get("fallback_recovered")) for record in records)
    return {
        "cases": len(records),
        "semantic_attempted": len(semantic_attempts),
        "semantic_cases": len(semantic),
        "semantic_failures": len(semantic_attempts) - len(semantic),
        "classifier_bypassed": sum(
            bool(record.get("classifier_bypassed")) for record in population
        ),
        "classifier_bypass_mismatches": sum(
            not bool(record.get("classifier_bypass_matches_expected")) for record in population
        ),
        "request_failures": request_failures,
        "attempt_failures": attempt_failures,
        "fallback_recoveries": fallback_recoveries,
        "business_action_accuracy": _ratio(
            sum(bool(record.get("business_action_match")) for record in population), len(population)
        ),
        "raw_semantic_accuracy": _ratio(
            sum(bool(record.get("raw_semantic_match")) for record in semantic), len(semantic)
        ),
        "gate_0_9": {
            "tp": true_positive,
            "fp": false_positive,
            "fn": false_negative,
            "tn": true_negative,
            "precision": _ratio(true_positive, true_positive + false_positive),
            "recall": _ratio(true_positive, true_positive + false_negative),
        },
        "avg_latency_ms": round(
            sum(float(record.get("latency_ms") or 0.0) for record in records) / len(records), 1
        )
        if records
        else 0.0,
    }


def _write_progress(record: dict[str, Any], path: Path | None) -> None:
    progress = {
        key: record.get(key)
        for key in (
            "case_id",
            "primary_model",
            "fallback_model",
            "failure_injection",
            "semantic_status",
            "raw_classifier_action",
            "raw_classifier_confidence",
            "final_business_action",
            "request_failure",
            "attempt_failures",
            "fallback_recovered",
            "latency_ms",
            "error_type",
            "error_status",
        )
    }
    line = json.dumps(progress, ensure_ascii=False)
    print(f"[decision-eval] case={line}")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    cases = _load_dataset(Path(args.dataset))
    progress_path = Path(args.progress_log).expanduser() if args.progress_log else None
    if progress_path is not None:
        progress_path.unlink(missing_ok=True)
    local_env_path = Path(args.local_env_file).expanduser()
    model_catalog_path = Path(args.model_catalog).expanduser()
    codiv_key_path = Path(args.codiv_key_file).expanduser()
    standard_cases = [case for case in cases if not case.get("failure_injection")]
    fallback_cases = [case for case in cases if case.get("failure_injection")]
    if args.max_cases > 0:
        standard_cases = standard_cases[: args.max_cases]
    model_ids = (args.only_model,) if args.only_model else STANDARD_MODEL_IDS
    report: dict[str, Any] = {
        "dataset": str(Path(args.dataset).resolve()),
        "evidence_policy": {
            "live_provider_calls": True,
            "concurrency": 1,
            "credential_values_recorded": False,
            "failure_endpoint": PRIMARY_FAILURE_BASE_URL,
            "gate_confidence": GATE_CONFIDENCE,
        },
        "models": {},
    }
    for model_id in model_ids:
        records: list[dict[str, Any]] = []
        for case in standard_cases:
            record = _run_case(
                case=case,
                primary_model=model_id,
                fallback_model=None,
                timeout_seconds=args.timeout_seconds,
                failure_injection=False,
                local_env_path=local_env_path,
                model_catalog_path=model_catalog_path,
                codiv_key_path=codiv_key_path,
            )
            records.append(record)
            _write_progress(record, progress_path)
        report["models"][model_id] = {
            "primary_runs": records,
            "summary": _summary(records),
        }

    if args.include_fallback:
        fallback_records: list[dict[str, Any]] = []
        for case in fallback_cases:
            primary = str(case["primary_model"])
            fallback = str(case["fallback_model"])
            record = _run_case(
                case=case,
                primary_model=primary,
                fallback_model=fallback,
                timeout_seconds=args.timeout_seconds,
                failure_injection=True,
                local_env_path=local_env_path,
                model_catalog_path=model_catalog_path,
                codiv_key_path=codiv_key_path,
            )
            fallback_records.append(record)
            _write_progress(record, progress_path)
        report["fallback_runs"] = {
            "cases": fallback_records,
            "summary": _summary(fallback_records),
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[decision-eval] wrote {output}")
    for model_id, details in report["models"].items():
        summary = details["summary"]
        print(
            f"[decision-eval] model={model_id} cases={summary['cases']} "
            f"business_accuracy={summary['business_action_accuracy']} "
            f"raw_accuracy={summary['raw_semantic_accuracy']} "
            f"request_failures={summary['request_failures']} "
            f"attempt_failures={summary['attempt_failures']} "
            f"classifier_bypassed={summary['classifier_bypassed']}"
        )
    if "fallback_runs" in report:
        summary = report["fallback_runs"]["summary"]
        print(
            f"[decision-eval] fallback_cases={summary['cases']} "
            f"request_failures={summary['request_failures']} "
            f"attempt_failures={summary['attempt_failures']} "
            f"fallback_recoveries={summary['fallback_recoveries']} "
            f"business_accuracy={summary['business_action_accuracy']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
