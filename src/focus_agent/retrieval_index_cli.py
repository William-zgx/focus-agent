from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .config import Settings
from .engine.runtime import create_runtime
from .retrieval.agent_team import index_agent_team_plan
from .retrieval.artifacts import index_artifact_content
from .retrieval.branch_context import index_branch_decision_event
from .retrieval.factory import create_retrieval_index
from .retrieval.failure_cases import index_failure_case_from_trajectory
from .retrieval.governance_feedback import index_governance_feedback
from .retrieval.trajectory import index_trajectory_record
from .retrieval.workspace import index_workspace
from .storage import LocalArtifactStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="focus-agent-retrieval-index",
        description="Inspect and backfill the embedded retrieval index.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Print retrieval index health as JSON.")
    subparsers.add_parser("stats", help="Print retrieval index stats as JSON.")
    subparsers.add_parser("rebuild", help="Print safe rebuild guidance as JSON.")
    backfill = subparsers.add_parser("backfill", help="Backfill canonical data into retrieval.")
    backfill.add_argument("--limit", type=int, default=1000)
    backfill.add_argument(
        "--target",
        choices=(
            "all",
            "memory",
            "artifact",
            "skill",
            "trajectory",
            "branch-context",
            "agent-team-plans",
            "failure-cases",
            "governance-feedback",
            "workspace",
        ),
        default="all",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    if args.command in {"doctor", "stats"}:
        index, error = create_retrieval_index(
            settings,
            dimensions=int(getattr(settings, "agent_memory_embedding_dimensions", 768) or 768),
        )
        payload: dict[str, Any] = {
            "enabled": bool(getattr(settings, "agent_zvec_enabled", True)),
            "backend": getattr(settings, "agent_retrieval_backend", "zvec"),
            "fallback": getattr(settings, "agent_retrieval_fallback_backend", "postgres"),
            "ready": index is not None,
            "error": error,
        }
        if args.command == "stats" and index is not None:
            payload["stats"] = index.stats()
        _print_json(payload)
        return 0 if index is not None or payload["fallback"] else 1

    if args.command == "rebuild":
        _print_json(
            {
                "supported": False,
                "reason": "destructive zvec rebuild is intentionally manual",
                "next_step": "stop writers, remove AGENT_ZVEC_DATA_DIR, then run backfill",
            }
        )
        return 0

    if args.command == "backfill":
        runtime = create_runtime(settings)
        try:
            _print_json(_run_backfill(runtime, settings=settings, args=args))
            return 0
        finally:
            runtime.close()

    return 2


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _run_backfill(runtime: Any, *, settings: Settings, args: argparse.Namespace) -> dict[str, Any]:
    target = str(getattr(args, "target", "all") or "all")
    limit = max(1, int(getattr(args, "limit", 1000) or 1000))
    selected = (
        {
            "memory",
            "artifact",
            "skill",
            "trajectory",
            "branch-context",
            "agent-team-plans",
            "failure-cases",
            "governance-feedback",
            "workspace",
        }
        if target == "all"
        else {target}
    )
    payload: dict[str, Any] = {
        "target": target,
        "limit": limit,
        "retrieval_index_ready": getattr(runtime, "retrieval_index", None) is not None,
        "results": {},
    }
    results = payload["results"]
    if "memory" in selected:
        results["memory"] = _backfill_memory(runtime, limit=limit)
    if "artifact" in selected:
        results["artifact"] = _backfill_artifacts(runtime, settings=settings, limit=limit)
    if "skill" in selected:
        results["skill"] = _backfill_skills(runtime)
    if "trajectory" in selected:
        results["trajectory"] = _backfill_trajectory(runtime, limit=limit)
    if "branch-context" in selected:
        results["branch-context"] = _backfill_branch_context(runtime, limit=limit)
    if "agent-team-plans" in selected:
        results["agent-team-plans"] = _backfill_agent_team_plans(runtime, limit=limit)
    if "failure-cases" in selected:
        results["failure-cases"] = _backfill_failure_cases(runtime, limit=limit)
    if "governance-feedback" in selected:
        results["governance-feedback"] = _backfill_governance_feedback(runtime, limit=limit)
    if "workspace" in selected:
        results["workspace"] = _backfill_workspace(runtime, settings=settings, limit=limit)
    return payload


def _backfill_memory(runtime: Any, *, limit: int) -> dict[str, Any]:
    service = getattr(runtime, "memory_embedding_service", None)
    if service is None:
        return {"backfilled": False, "reason": "memory embedding service unavailable"}
    return {"backfilled": True, "result": service.backfill(limit=limit)}


def _backfill_artifacts(runtime: Any, *, settings: Settings, limit: int) -> dict[str, Any]:
    index = getattr(runtime, "retrieval_index", None)
    provider = getattr(getattr(runtime, "memory_embedding_service", None), "provider", None)
    if index is None or provider is None:
        return {"backfilled": False, "reason": "retrieval index or embedding provider unavailable"}
    store = LocalArtifactStore(settings.artifact_dir)
    artifacts = 0
    chunks = 0
    errors = 0
    for item in store.iter_artifacts():
        if artifacts >= limit:
            break
        try:
            content = store.load(item.artifact_id).decode("utf-8")
            chunks += index_artifact_content(
                retrieval_index=index,
                embedding_provider=provider,
                artifact_id=item.artifact_id,
                title=_artifact_title_from_id(item.artifact_id),
                content=content,
            )
            artifacts += 1
        except Exception:  # noqa: BLE001
            errors += 1
    return {
        "backfilled": True,
        "artifacts": artifacts,
        "chunks": chunks,
        "errors": errors,
    }


def _backfill_skills(runtime: Any) -> dict[str, Any]:
    registry = getattr(runtime, "skill_registry", None)
    if registry is None:
        return {"backfilled": False, "reason": "skill registry unavailable"}
    reindex = getattr(registry, "_index_skills_best_effort", None)
    if not callable(reindex):
        return {"backfilled": False, "reason": "skill registry cannot reindex"}
    reindex()
    skills = [
        skill
        for skill in registry.all_skills()
        if registry.is_skill_enabled(getattr(skill, "skill_id", ""))
    ]
    return {"backfilled": True, "skills": len(skills)}


def _backfill_trajectory(runtime: Any, *, limit: int) -> dict[str, Any]:
    repository = getattr(runtime, "trajectory_recorder", None)
    index = getattr(runtime, "retrieval_index", None)
    provider = getattr(runtime, "memory_embedding_provider", None)
    if repository is None or index is None or provider is None:
        return {"backfilled": False, "reason": "trajectory repository or retrieval unavailable"}
    export_turns = getattr(repository, "export_turns", None)
    list_turns = getattr(repository, "list_turns", None)
    if callable(export_turns):
        records = export_turns(filters={}, limit=limit, offset=0)
    elif callable(list_turns):
        records = list_turns(filters={}, limit=limit, offset=0)
    else:
        return {"backfilled": False, "reason": "trajectory repository cannot list turns"}
    indexed = 0
    errors = 0
    for record in records:
        try:
            index_trajectory_record(
                retrieval_index=index,
                embedding_provider=provider,
                record=record,
            )
            indexed += 1
        except Exception:  # noqa: BLE001
            errors += 1
    return {"backfilled": True, "turns": indexed, "errors": errors}


def _backfill_branch_context(runtime: Any, *, limit: int) -> dict[str, Any]:
    repository = getattr(runtime, "governance_repository", None)
    index = getattr(runtime, "retrieval_index", None)
    provider = getattr(runtime, "memory_embedding_provider", None)
    if repository is None or index is None or provider is None:
        return {"backfilled": False, "reason": "governance repository or retrieval unavailable"}
    list_events = getattr(repository, "list_branch_decision_events", None)
    if not callable(list_events):
        return {"backfilled": False, "reason": "governance repository cannot list branches"}
    indexed = 0
    errors = 0
    for event in list_events(limit=limit):
        try:
            indexed += int(
                index_branch_decision_event(
                    retrieval_index=index,
                    embedding_provider=provider,
                    event=event,
                )
            )
        except Exception:  # noqa: BLE001
            errors += 1
    return {"backfilled": True, "events": indexed, "errors": errors}


def _backfill_agent_team_plans(runtime: Any, *, limit: int) -> dict[str, Any]:
    service = getattr(runtime, "agent_team_service", None)
    index = getattr(runtime, "retrieval_index", None)
    provider = getattr(runtime, "memory_embedding_provider", None)
    repository = getattr(service, "repository", None)
    if repository is None or index is None or provider is None:
        return {"backfilled": False, "reason": "agent-team repository or retrieval unavailable"}
    list_sessions = getattr(repository, "list_sessions", None)
    if not callable(list_sessions):
        return {"backfilled": False, "reason": "agent-team repository cannot list sessions"}
    indexed = 0
    errors = 0
    for session in list_sessions(user_id=None)[:limit]:
        try:
            tasks = repository.list_tasks(session_id=session.session_id)
            outputs = [
                output
                for task in tasks
                for output in repository.list_task_outputs(task_id=task.task_id)
            ]
            indexed += int(
                index_agent_team_plan(
                    retrieval_index=index,
                    embedding_provider=provider,
                    session=session,
                    tasks=tasks,
                    outputs=outputs,
                )
            )
        except Exception:  # noqa: BLE001
            errors += 1
    return {"backfilled": True, "sessions": indexed, "errors": errors}


def _backfill_failure_cases(runtime: Any, *, limit: int) -> dict[str, Any]:
    repository = getattr(runtime, "trajectory_recorder", None)
    index = getattr(runtime, "retrieval_index", None)
    provider = getattr(runtime, "memory_embedding_provider", None)
    if repository is None or index is None or provider is None:
        return {"backfilled": False, "reason": "trajectory repository or retrieval unavailable"}
    records = _list_trajectory_records(repository, limit=limit)
    if records is None:
        return {"backfilled": False, "reason": "trajectory repository cannot list turns"}
    indexed = 0
    errors = 0
    for record in records:
        try:
            indexed += int(
                index_failure_case_from_trajectory(
                    retrieval_index=index,
                    embedding_provider=provider,
                    record=record,
                )
            )
        except Exception:  # noqa: BLE001
            errors += 1
    return {"backfilled": True, "cases": indexed, "errors": errors}


def _backfill_governance_feedback(runtime: Any, *, limit: int) -> dict[str, Any]:
    repository = getattr(runtime, "governance_repository", None)
    index = getattr(runtime, "retrieval_index", None)
    provider = getattr(runtime, "memory_embedding_provider", None)
    if repository is None or index is None or provider is None:
        return {"backfilled": False, "reason": "governance repository or retrieval unavailable"}
    method_names = (
        "list_context_evidence",
        "list_skill_selection_events",
        "list_feedback_events",
    )
    indexed = 0
    errors = 0
    for method_name in method_names:
        method = getattr(repository, method_name, None)
        if not callable(method):
            continue
        try:
            items = method(limit=limit)
        except Exception:  # noqa: BLE001
            errors += 1
            continue
        for item in items:
            try:
                indexed += int(
                    index_governance_feedback(
                        retrieval_index=index,
                        embedding_provider=provider,
                        item=item,
                    )
                )
            except Exception:  # noqa: BLE001
                errors += 1
    return {"backfilled": True, "items": indexed, "errors": errors}


def _backfill_workspace(runtime: Any, *, settings: Settings, limit: int) -> dict[str, Any]:
    index = getattr(runtime, "retrieval_index", None)
    provider = getattr(runtime, "memory_embedding_provider", None)
    if index is None or provider is None:
        return {"backfilled": False, "reason": "retrieval index or embedding provider unavailable"}
    result = index_workspace(
        retrieval_index=index,
        embedding_provider=provider,
        workspace_root=Path(settings.workspace_root),
        max_files=limit,
    )
    return {"backfilled": True, **result}


def _list_trajectory_records(repository: Any, *, limit: int) -> list[Any] | None:
    export_turns = getattr(repository, "export_turns", None)
    list_turns = getattr(repository, "list_turns", None)
    if callable(export_turns):
        return list(export_turns(filters={}, limit=limit, offset=0))
    if callable(list_turns):
        return list(list_turns(filters={}, limit=limit, offset=0))
    return None


def _artifact_title_from_id(artifact_id: str) -> str:
    artifact_path = Path(artifact_id)
    return artifact_path.stem.replace("-", " ").strip().title() or artifact_path.name


if __name__ == "__main__":
    raise SystemExit(main())
