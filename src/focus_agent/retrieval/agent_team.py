from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .index import RetrievalDocument, RetrievalIndex


@dataclass(frozen=True, slots=True)
class AgentTeamPlanHit:
    source_id: str
    score: float
    text: str
    fields: dict[str, Any]
    context_refs: list[dict[str, Any]] = field(default_factory=list)


def index_agent_team_plan(
    *,
    retrieval_index: RetrievalIndex | None,
    embedding_provider: Any | None,
    session: Any,
    tasks: list[Any],
    outputs: list[Any] | None = None,
) -> bool:
    if retrieval_index is None or embedding_provider is None:
        return False
    session_id = str(getattr(session, "session_id", "") or "")
    if not session_id:
        return False
    text = _plan_text(session=session, tasks=tasks, outputs=outputs or [])
    retrieval_index.upsert(
        RetrievalDocument(
            collection="focus_agent_team_plans",
            doc_id=f"agent-team:{session_id}",
            source_id=session_id,
            text=text,
            vector=embedding_provider.embed([text])[0],
            fields={
                "source_type": "agent_team_plan",
                "session_id": session_id,
                "user_id": str(getattr(session, "user_id", "") or ""),
                "root_thread_id": str(getattr(session, "root_thread_id", "") or ""),
                "status": _value(getattr(session, "status", "")),
                "plan_hash": str(getattr(session, "plan_hash", "") or ""),
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            },
        )
    )
    return True


class AgentTeamPlanRetrievalService:
    def __init__(
        self,
        *,
        retrieval_index: RetrievalIndex | None,
        embedding_provider: Any | None,
        repository: Any | None = None,
    ) -> None:
        self.retrieval_index = retrieval_index
        self.embedding_provider = embedding_provider
        self.repository = repository

    def search_similar_plans(
        self,
        *,
        query: str,
        user_id: str,
        root_thread_id: str | None = None,
        limit: int = 5,
    ) -> list[AgentTeamPlanHit]:
        if self.retrieval_index is None or self.embedding_provider is None:
            return []
        filters = {"user_id": user_id}
        if root_thread_id:
            filters["root_thread_id"] = root_thread_id
        hits = self.retrieval_index.search(
            collection="focus_agent_team_plans",
            query=query,
            vector=self.embedding_provider.embed([query])[0],
            limit=limit,
            filters=filters,
        )
        results: list[AgentTeamPlanHit] = []
        for hit in hits:
            session = _repo_call(self.repository, "get_session", hit.source_id)
            if session is not None:
                if str(getattr(session, "user_id", "") or "") != user_id:
                    continue
                if root_thread_id and str(getattr(session, "root_thread_id", "") or "") != root_thread_id:
                    continue
            tasks = _repo_call(self.repository, "list_tasks", session_id=hit.source_id) or []
            results.append(
                AgentTeamPlanHit(
                    source_id=hit.source_id,
                    score=hit.score,
                    text=hit.text,
                    fields=dict(hit.fields),
                    context_refs=_context_refs(tasks),
                )
            )
        return results


def _plan_text(*, session: Any, tasks: list[Any], outputs: list[Any]) -> str:
    parts = [
        getattr(session, "title", ""),
        getattr(session, "goal", ""),
        getattr(session, "planning_rationale", ""),
        getattr(session, "planning_error", ""),
    ]
    for task in tasks:
        parts.extend(
            [
                getattr(task, "title", ""),
                getattr(task, "goal", ""),
                getattr(task, "planning_rationale", ""),
                " ".join(getattr(task, "acceptance_criteria", []) or []),
                " ".join(getattr(task, "risk_notes", []) or []),
            ]
        )
    for output in outputs:
        parts.extend(
            [
                getattr(output, "summary", ""),
                getattr(output, "diff_summary", ""),
                json.dumps(getattr(output, "metadata", {}) or {}, ensure_ascii=False, sort_keys=True),
            ]
        )
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def _context_refs(tasks: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        for ref in getattr(task, "context_refs", []) or []:
            if not isinstance(ref, dict):
                continue
            key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                refs.append(dict(ref))
    return refs


def _repo_call(repository: Any | None, name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(repository, name, None)
    if not callable(method):
        return None
    try:
        return method(*args, **kwargs)
    except TypeError:
        return method(*args)


def _value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")
