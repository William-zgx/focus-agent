from __future__ import annotations

import inspect
import logging
import re

from ..core.request_context import RequestContext
from ..core.types import FindingItem, Plan, PromptMode
from ..repositories.memory_repository import MemoryListQuery
from ..retrieval import RetrievalIndex
from .dedupe import memory_resolution_key, memory_semantic_key
from .models import (
    MemoryRecord,
    MemoryRetrievalPlan,
    MemoryScope,
    MemorySearchHit,
    MemoryVisibility,
    RetrievedMemoryBundle,
)
from .policy import MemoryPolicy
from .scorer import score_memory_hit

logger = logging.getLogger(__name__)


class MemoryRetriever:
    def __init__(
        self,
        *,
        store=None,
        repository=None,
        policy: MemoryPolicy | None = None,
        default_limit: int = 8,
        retrieval_mode: str = "fts",
        vector_shadow: bool = True,
        rrf_k: int = 60,
        embedding_provider=None,
        retrieval_index: RetrievalIndex | None = None,
    ):
        if retrieval_mode not in {"fts", "hybrid"}:
            raise ValueError("retrieval_mode must be 'fts' or 'hybrid'")
        self.store = store
        self.repository = repository
        self.policy = policy or MemoryPolicy(top_k=default_limit)
        self.default_limit = default_limit
        self.retrieval_mode = retrieval_mode
        self.vector_shadow = vector_shadow
        self.rrf_k = max(1, int(rrf_k))
        self.embedding_provider = embedding_provider
        self.retrieval_index = retrieval_index

    def retrieve_for_turn(
        self,
        *,
        context: RequestContext,
        state: dict,
        query: str,
        prompt_mode: PromptMode,
    ) -> RetrievedMemoryBundle:
        effective_query = _build_retrieval_query(
            query=query,
            state=state,
            prompt_mode=prompt_mode,
        )
        namespaces = self._candidate_namespaces(context=context)
        hits: list[MemorySearchHit] = []
        vector_hits: list[MemorySearchHit] = []
        vector_statuses: list[str] = []
        vector_enabled = self._should_search_vectors()
        query_vector: list[float] | None = None
        query_vector_status: str | None = None
        if vector_enabled and namespaces and self.embedding_provider is not None:
            try:
                query_vector = self.embedding_provider.embed([effective_query])[0]
            except Exception:
                logger.warning("memory query embedding failed; falling back to FTS", exc_info=True)
                query_vector_status = "failed"
        retrieval_hits: list[MemorySearchHit] = []
        retrieval_failed = False
        if self.retrieval_index is not None and namespaces:
            for namespace in namespaces:
                namespace_retrieval_hits, namespace_retrieval_status = (
                    self._search_retrieval_namespace(
                        namespace,
                        effective_query,
                        limit=self.default_limit,
                        query_vector=query_vector,
                    )
                )
                retrieval_hits.extend(namespace_retrieval_hits)
                if namespace_retrieval_status == "failed":
                    retrieval_failed = True
                    break
        if retrieval_hits and not retrieval_failed:
            deduped = self._dedupe_hits(
                self._rerank_hits(retrieval_hits, query=effective_query, prompt_mode=prompt_mode)
            )
            bundle = RetrievedMemoryBundle(
                query=effective_query,
                hits=deduped[: self.default_limit],
                namespaces=namespaces,
                total_hits=len(deduped),
            )
            filtered = self.policy.filter_bundle_for_prompt(bundle, prompt_mode=prompt_mode)
            selected_ids = [hit.record.memory_id for hit in filtered.hits]
            retrieval_plan = MemoryRetrievalPlan(
                query=effective_query,
                namespaces=namespaces,
                filters={"status": "active"},
                selected_memory_ids=selected_ids,
                budget_reason=f"top_k:{self.default_limit}",
                source="zvec",
                vector_shadow={},
                vector_status="completed",
                vector_candidate_count=len(retrieval_hits),
                vector_fallback_reason=None,
                embedding_provider=_embedding_provider_metadata(self.embedding_provider),
            )
            return filtered.model_copy(
                update={"retrieval_plan": retrieval_plan.model_dump(mode="json")}
            )
        for namespace in namespaces:
            namespace_hits = self._search_namespace(
                namespace, effective_query, limit=self.default_limit
            )
            if not namespace_hits and _is_user_profile_namespace(namespace):
                namespace_hits = self._recent_user_profile_hits(
                    namespace, effective_query, limit=self.default_limit
                )
            hits.extend(namespace_hits)
            if vector_enabled:
                if query_vector_status == "failed":
                    namespace_vector_hits, namespace_vector_status = [], "failed"
                else:
                    namespace_vector_hits, namespace_vector_status = (
                        self._search_vector_namespace(
                            namespace,
                            effective_query,
                            limit=self.default_limit,
                            query_vector=query_vector,
                        )
                    )
                vector_hits.extend(namespace_vector_hits)
                vector_statuses.append(namespace_vector_status)
        vector_status = _combined_vector_status(
            vector_statuses,
            enabled=vector_enabled,
            repository_available=self.repository is not None,
        )
        if self.retrieval_mode == "hybrid" and vector_status == "completed":
            reranked = self._rrf_blend_hits(
                [
                    self._rerank_hits(hits, query=effective_query, prompt_mode=prompt_mode),
                    self._rerank_hits(vector_hits, query=effective_query, prompt_mode=prompt_mode),
                ]
            )
        else:
            reranked = self._rerank_hits(hits, query=effective_query, prompt_mode=prompt_mode)
        deduped = self._dedupe_hits(reranked)
        bundle = RetrievedMemoryBundle(
            query=effective_query,
            hits=deduped[: self.default_limit],
            namespaces=namespaces,
            total_hits=len(deduped),
        )
        filtered = self.policy.filter_bundle_for_prompt(bundle, prompt_mode=prompt_mode)
        selected_ids = [hit.record.memory_id for hit in filtered.hits]
        retrieval_plan = MemoryRetrievalPlan(
            query=effective_query,
            namespaces=namespaces,
            filters={"status": "active"},
            selected_memory_ids=selected_ids,
            budget_reason=f"top_k:{self.default_limit}",
            source="postgres" if self.repository is not None else "legacy_store",
            vector_shadow=_vector_shadow_plan(
                vector_hits=vector_hits,
                vector_status=vector_status,
                retrieval_mode=self.retrieval_mode,
                vector_shadow_enabled=self.vector_shadow,
            ),
            vector_status=vector_status,
            vector_candidate_count=len(vector_hits),
            vector_fallback_reason=_vector_fallback_reason(
                vector_status=vector_status,
                enabled=vector_enabled,
                retrieval_mode=self.retrieval_mode,
            ),
            embedding_provider=_embedding_provider_metadata(self.embedding_provider),
        )
        return filtered.model_copy(
            update={"retrieval_plan": retrieval_plan.model_dump(mode="json")}
        )

    def _candidate_namespaces(self, *, context: RequestContext) -> list[tuple[str, ...]]:
        return self.policy.allowed_namespaces_for_read(context=context)

    def _search_namespace(
        self, namespace: tuple[str, ...], query: str, limit: int
    ) -> list[MemorySearchHit]:
        if self.repository is not None:
            hits = self.repository.search(namespace=namespace, query=query, limit=limit)
            return _normalize_repository_hits(hits, namespace=namespace, query=query)
        if self.store is None:
            return []
        raw_hits = self.store.search(namespace, query=query, limit=limit) or []
        hits: list[MemorySearchHit] = []
        for raw in raw_hits:
            value = getattr(raw, "value", raw)
            if not isinstance(value, dict):
                value = {"content": str(value), "summary": str(value)}
            payload = {
                "memory_id": str(value.get("memory_id") or getattr(raw, "key", "")),
                "kind": value.get("kind", value.get("type", "turn_summary")),
                "scope": value.get("scope", "root_thread"),
                "visibility": value.get("visibility", "private"),
                "namespace": tuple(value.get("namespace") or getattr(raw, "namespace", namespace)),
                "content": value.get("content") or value.get("summary") or str(value),
                "summary": value.get("summary") or value.get("content") or "",
                "tags": value.get("tags", []),
                "evidence_refs": value.get("evidence_refs", []),
                "source_thread_id": value.get("source_thread_id"),
                "source_branch_id": value.get("source_branch_id") or value.get("branch_id"),
                "root_thread_id": value.get("root_thread_id"),
                "user_id": value.get("user_id"),
                "confidence": value.get("confidence"),
                "importance": value.get("importance", 0.5),
                "promoted_to_main": value.get("promoted_to_main", False),
                "fingerprint": value.get("fingerprint"),
                "semantic_key": value.get("semantic_key"),
            }
            created_at = value.get("created_at")
            updated_at = value.get("updated_at")
            if created_at is not None:
                payload["created_at"] = created_at
            if updated_at is not None:
                payload["updated_at"] = updated_at
            record = MemoryRecord.model_validate(payload)
            hits.append(
                MemorySearchHit(
                    record=record,
                    score=float(getattr(raw, "score", 0.0) or 0.0),
                    matched_terms=_matched_terms(query, record),
                    namespace=record.namespace or namespace,
                )
            )
        return hits

    def _recent_user_profile_hits(
        self, namespace: tuple[str, ...], query: str, limit: int
    ) -> list[MemorySearchHit]:
        if self.repository is None:
            return []
        list_records = getattr(self.repository, "list_records", None)
        if not callable(list_records):
            return []
        records = list_records(
            MemoryListQuery(namespace=namespace, status="active", limit=limit)
        )
        hits: list[MemorySearchHit] = []
        for record in records:
            if record.kind.value not in {"user_preference", "user_profile"}:
                continue
            hits.append(
                MemorySearchHit(
                    record=record,
                    score=0.0,
                    matched_terms=_matched_terms(query, record),
                    namespace=record.namespace or namespace,
                    rationale="recent_user_profile",
                )
            )
        return hits

    def _should_search_vectors(self) -> bool:
        if self.repository is None:
            return False
        if self.embedding_provider is None:
            return _vector_search_accepts_query(_repository_vector_search(self.repository))
        if self.retrieval_mode == "hybrid":
            return True
        return self.vector_shadow

    def _search_vector_namespace(
        self,
        namespace: tuple[str, ...],
        query: str,
        limit: int,
        query_vector: list[float] | None = None,
    ) -> tuple[list[MemorySearchHit], str]:
        search_vectors = _repository_vector_search(self.repository)
        if search_vectors is None:
            return [], "unsupported"
        try:
            if self.embedding_provider is not None:
                if query_vector is None:
                    query_vector = self.embedding_provider.embed([query])[0]
                hits = search_vectors(
                    namespace=namespace,
                    embedding=query_vector,
                    provider_id=self.embedding_provider.provider_id,
                    model_id=self.embedding_provider.model_id,
                    limit=limit,
                )
            else:
                hits = search_vectors(namespace=namespace, query=query, limit=limit)
        except Exception:
            logger.warning("memory vector search failed; falling back to FTS", exc_info=True)
            return [], "failed"
        return _normalize_repository_hits(hits, namespace=namespace, query=query), "completed"

    def _search_retrieval_namespace(
        self,
        namespace: tuple[str, ...],
        query: str,
        limit: int,
        query_vector: list[float] | None = None,
    ) -> tuple[list[MemorySearchHit], str]:
        if self.retrieval_index is None or self.repository is None:
            return [], "unsupported"
        try:
            hits = self.retrieval_index.search(
                collection="focus_memory",
                query=query,
                vector=query_vector,
                limit=limit,
                filters={"namespace": namespace, "status": "active"},
            )
        except Exception:
            logger.warning("memory zvec search failed; falling back to repository", exc_info=True)
            return [], "failed"
        normalized: list[MemorySearchHit] = []
        for hit in hits:
            record = self.repository.get_record(hit.source_id)
            if record is None or tuple(record.namespace) != namespace:
                continue
            if getattr(record.status, "value", record.status) != "active":
                continue
            normalized.append(
                MemorySearchHit(
                    record=record,
                    score=float(hit.score),
                    matched_terms=_matched_terms(query, record),
                    namespace=record.namespace,
                    rationale="zvec",
                )
            )
        return normalized, "completed"

    def _rerank_hits(
        self, hits: list[MemorySearchHit], *, query: str, prompt_mode: PromptMode
    ) -> list[MemorySearchHit]:
        reranked = [
            hit.model_copy(
                update={"score": score_memory_hit(hit, query=query, prompt_mode=prompt_mode)}
            )
            for hit in hits
        ]
        return sorted(reranked, key=lambda item: item.score, reverse=True)

    def _dedupe_hits(self, hits: list[MemorySearchHit]) -> list[MemorySearchHit]:
        deduped_by_key: dict[str, MemorySearchHit] = {}
        for hit in hits:
            resolution_key = memory_resolution_key(
                hit.record.model_copy(
                    update={
                        "semantic_key": hit.record.semantic_key or memory_semantic_key(hit.record),
                    }
                )
            )
            current = deduped_by_key.get(resolution_key)
            if current is None or _hit_preference(hit) > _hit_preference(current):
                deduped_by_key[resolution_key] = hit
        return sorted(deduped_by_key.values(), key=lambda item: item.score, reverse=True)

    def _rrf_blend_hits(
        self, ranked_hit_lists: list[list[MemorySearchHit]]
    ) -> list[MemorySearchHit]:
        hits_by_id: dict[str, MemorySearchHit] = {}
        scores_by_id: dict[str, float] = {}
        for ranked_hits in ranked_hit_lists:
            seen_ids: set[str] = set()
            for rank, hit in enumerate(ranked_hits, start=1):
                memory_id = hit.record.memory_id
                if memory_id in seen_ids:
                    continue
                seen_ids.add(memory_id)
                scores_by_id[memory_id] = scores_by_id.get(memory_id, 0.0) + (
                    1.0 / (self.rrf_k + rank)
                )
                current = hits_by_id.get(memory_id)
                if current is None or _hit_preference(hit) > _hit_preference(current):
                    hits_by_id[memory_id] = hit
        blended = [
            hit.model_copy(update={"score": round(scores_by_id[memory_id], 6)})
            for memory_id, hit in hits_by_id.items()
        ]
        return sorted(blended, key=lambda item: item.score, reverse=True)


def _repository_vector_search(repository):
    for name in ("vector_search", "search_vector", "search_vectors"):
        search_vectors = getattr(repository, name, None)
        if callable(search_vectors):
            return search_vectors
    return None


def _is_user_profile_namespace(namespace: tuple[str, ...]) -> bool:
    return len(namespace) == 3 and namespace[0] == "user" and namespace[2] == "profile"


def _vector_search_accepts_query(search_vectors) -> bool:
    if search_vectors is None:
        return False
    try:
        return "query" in inspect.signature(search_vectors).parameters
    except (TypeError, ValueError):
        return False


def _normalize_repository_hits(
    hits: list[object],
    *,
    namespace: tuple[str, ...],
    query: str,
) -> list[MemorySearchHit]:
    normalized: list[MemorySearchHit] = []
    for hit in hits or []:
        if isinstance(hit, MemorySearchHit):
            normalized.append(
                hit.model_copy(
                    update={
                        "matched_terms": hit.matched_terms or _matched_terms(query, hit.record),
                        "namespace": hit.namespace or namespace,
                    }
                )
            )
            continue
        record = getattr(hit, "record", None)
        if not isinstance(record, MemoryRecord):
            continue
        hit_namespace = getattr(hit, "namespace", None) or namespace
        normalized.append(
            MemorySearchHit(
                record=record,
                score=float(getattr(hit, "score", 0.0) or 0.0),
                matched_terms=_matched_terms(query, record),
                namespace=tuple(hit_namespace),
                rationale=str(getattr(hit, "rationale", None) or "vector"),
            )
        )
    return normalized


def _combined_vector_status(
    statuses: list[str],
    *,
    enabled: bool,
    repository_available: bool,
) -> str:
    if not repository_available:
        return "unsupported"
    if not enabled:
        return "disabled"
    if not statuses:
        return "unsupported"
    if "failed" in statuses:
        return "failed"
    if "completed" in statuses:
        return "completed"
    return "unsupported"


def _vector_shadow_plan(
    *,
    vector_hits: list[MemorySearchHit],
    vector_status: str,
    retrieval_mode: str,
    vector_shadow_enabled: bool,
) -> dict[str, object]:
    if (
        retrieval_mode != "fts"
        or not vector_shadow_enabled
        or vector_status not in {"completed", "failed"}
    ):
        return {}
    return {
        "enabled": True,
        "status": vector_status,
        "hit_count": len(vector_hits),
        "memory_ids": [hit.record.memory_id for hit in vector_hits],
    }


def _vector_fallback_reason(
    *, vector_status: str, enabled: bool, retrieval_mode: str
) -> str | None:
    if vector_status == "completed":
        return None
    if not enabled:
        return "vector_search_disabled"
    if vector_status == "failed":
        return "vector_search_failed_fts_fallback"
    if vector_status == "unsupported":
        return "vector_search_unsupported_fts_fallback"
    if retrieval_mode != "hybrid":
        return None
    return f"vector_search_{vector_status}_fts_fallback"


def _embedding_provider_metadata(provider: object | None) -> dict[str, object]:
    if provider is None:
        return {}
    metadata: dict[str, object] = {}
    for output_key, attr in (
        ("provider_id", "provider_id"),
        ("model_id", "model_id"),
        ("dimensions", "dimensions"),
    ):
        value = getattr(provider, attr, None)
        if value is not None:
            metadata[output_key] = value
    return metadata


def _matched_terms(query: str, record: MemoryRecord) -> list[str]:
    haystack = f"{record.summary} {record.content}".casefold()
    terms = []
    for term in _query_terms(query):
        if term.casefold() in haystack and term not in terms:
            terms.append(term)
    return terms


def _hit_preference(hit: MemorySearchHit) -> tuple[float, ...]:
    record = hit.record
    return (
        1.0 if record.promoted_to_main else 0.0,
        1.0 if record.visibility == MemoryVisibility.SHARED else 0.0,
        1.0 if record.scope == MemoryScope.ROOT_THREAD else 0.0,
        float(record.confidence or 0.0),
        record.importance,
        float(len(record.evidence_refs)),
        record.updated_at.timestamp(),
        hit.score,
    )


def _build_retrieval_query(*, query: str, state: dict, prompt_mode: PromptMode) -> str:
    parts: list[str] = []
    for candidate in (
        str(query or "").strip(),
        str(state.get("active_goal") or "").strip(),
        str(state.get("task_brief") or "").strip(),
        _current_plan_step_goal(state),
    ):
        if not candidate:
            continue
        normalized = " ".join(candidate.split())
        if normalized and normalized not in parts:
            parts.append(normalized)

    if prompt_mode == PromptMode.SYNTHESIZE:
        imported_lines = []
        for item in list(state.get("imported_findings", []) or [])[:2]:
            if isinstance(item, FindingItem):
                line = item.finding.strip()
            elif isinstance(item, dict):
                line = str(item.get("finding") or item.get("summary") or "").strip()
            else:
                line = str(item or "").strip()
            if line:
                imported_lines.append(line)
        for line in imported_lines:
            if line and line not in parts:
                parts.append(line)

    combined = " | ".join(parts)
    return combined[:240]


def _current_plan_step_goal(state: dict) -> str:
    plan = state.get("plan")
    current_step_id = str(state.get("current_step_id") or "").strip()
    if not isinstance(plan, Plan) or not current_step_id:
        return ""
    for step in plan.steps:
        if step.id == current_step_id:
            return str(step.goal or "").strip()
    return ""


def _query_terms(query: str) -> list[str]:
    lowered = str(query or "").casefold()
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9]{2,}", lowered):
        if token not in terms:
            terms.append(token)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", str(query or "")):
        compact = "".join(sequence.split())
        if len(compact) <= 2:
            if compact and compact not in terms:
                terms.append(compact)
            continue
        for index in range(len(compact) - 1):
            token = compact[index : index + 2]
            if token not in terms:
                terms.append(token)
    return terms
