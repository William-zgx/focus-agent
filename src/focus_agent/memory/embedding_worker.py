from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..core.repo_call import has_repo_method
from ..repositories.memory_repository import MemoryRecordStaleError
from .dedupe import memory_fingerprint
from .embedding_cleanup import delete_embedding_artifacts
from .models import MemoryAuditEvent, MemoryRecord, MemoryStatus, MemoryWriteDecisionStatus

logger = logging.getLogger(__name__)


class MemoryEmbeddingWorker:
    def __init__(self, *, repository: Any, embedding_service: Any) -> None:
        self.repository = repository
        self.embedding_service = embedding_service

    def process_payload(
        self,
        *,
        memory_id: str,
        namespace: tuple[str, ...],
        attempt: int = 1,
        max_attempts: int = 3,
    ) -> None:
        record = self._get_record(memory_id)
        if record is None:
            raise ValueError(f"memory record not found: {memory_id}")
        if tuple(record.namespace) != tuple(namespace):
            raise ValueError(f"memory namespace mismatch: {memory_id}")
        if _memory_is_forgotten(record):
            self._delete_stale_embedding(record.memory_id)
            return
        if _memory_is_redacted(record):
            self._set_embedding_status(record, "failed", reason="sensitive_content_redacted")
            self._append_audit_event(
                record,
                action="embedding_skipped",
                decision=MemoryWriteDecisionStatus.SKIPPED,
                reason="sensitive_content_redacted",
                data={"embedding_status": "failed", "redacted": True},
            )
            return

        try:
            result = self.embedding_service.ensure_embedding(record)
        except Exception as exc:
            if int(attempt) >= int(max_attempts):
                self._set_embedding_status(record, "failed", reason="embedding_failed")
                self._append_audit_event(
                    record,
                    action="embedding_failed",
                    decision=MemoryWriteDecisionStatus.FAILED,
                    reason="embedding_failed",
                    data={
                        "attempt": int(attempt),
                        "max_attempts": int(max_attempts),
                        "error": str(exc)[:4000],
                    },
                )
            raise

        status = str(result.get("status") if isinstance(result, dict) else "")
        if status == "stale":
            raise MemoryRecordStaleError(record.memory_id)
        if status == "rejected":
            return
        if status == "written" or status == "skipped":
            self._set_embedding_status(record, "ready", reason=status or "embedding_ready")
            return
        raise RuntimeError(f"memory embedding was not written: {result!r}")

    def _get_record(self, memory_id: str) -> MemoryRecord | None:
        if not has_repo_method(self.repository, "get_record"):
            raise RuntimeError("memory repository does not support get_record")
        return self.repository.get_record(memory_id)

    def _set_embedding_status(self, record: MemoryRecord, status: str, *, reason: str) -> None:
        now = datetime.now(UTC)
        provider = getattr(self.embedding_service, "provider", None)
        model_id = getattr(provider, "model_id", None)
        if has_repo_method(self.repository, "update_record_embedding_status"):
            try:
                updated = self.repository.update_record_embedding_status(
                    memory_id=record.memory_id,
                    status=status,
                    model_id=model_id,
                    updated_at=now,
                    expected_fingerprint=record.fingerprint or memory_fingerprint(record),
                )
            except TypeError:
                updated = self.repository.update_record_embedding_status(
                    memory_id=record.memory_id,
                    status=status,
                    model_id=model_id,
                    updated_at=now,
                )
            if not updated:
                self._handle_embedding_status_rejected(record)
                logger.info(
                    "memory embedding status update skipped for protected memory",
                    extra={
                        "memory_id": record.memory_id,
                        "status": status,
                        "reason": reason,
                    },
                )
            return
        updated = (
            self.repository.get_record(record.memory_id)
            if has_repo_method(self.repository, "get_record")
            else record
        ) or record
        if updated.status == MemoryStatus.FORGOTTEN or updated.deleted_at is not None:
            self._delete_stale_embedding(record.memory_id)
            return
        updated = updated.model_copy(
            update={
                "embedding_status": status,
                "embedding_model_id": model_id,
                "embedding_updated_at": now,
                "updated_at": now,
            }
        )
        if has_repo_method(self.repository, "upsert_record"):
            logger.debug("using legacy whole-record embedding status update")
            self.repository.upsert_record(updated)
            return
        logger.warning(
            "memory embedding status update skipped",
            extra={"memory_id": record.memory_id, "status": status, "reason": reason},
        )

    def _handle_embedding_status_rejected(self, record: MemoryRecord) -> None:
        current = (
            self.repository.get_record(record.memory_id)
            if has_repo_method(self.repository, "get_record")
            else None
        )
        if (
            current is None
            or current.status == MemoryStatus.FORGOTTEN
            or current.deleted_at is not None
        ):
            self._delete_stale_embedding(record.memory_id)

    def _delete_stale_embedding(self, memory_id: str) -> None:
        delete_embedding_artifacts(
            self.repository,
            memory_id,
            retrieval_index=getattr(self.embedding_service, "retrieval_index", None),
        )

    def _append_audit_event(
        self,
        record: MemoryRecord,
        *,
        action: str,
        decision: MemoryWriteDecisionStatus,
        reason: str,
        data: dict[str, object],
    ) -> None:
        if not has_repo_method(self.repository, "append_audit_event"):
            return
        event = MemoryAuditEvent(
            event_id=str(uuid4()),
            action=action,
            decision=decision,
            memory_id=record.memory_id,
            actor="memory_embedding_worker",
            reason=reason,
            namespace=record.namespace,
            user_id=record.user_id,
            root_thread_id=record.root_thread_id,
            source_thread_id=record.source_thread_id,
            source_branch_id=record.source_branch_id,
            data=data,
        )
        self.repository.append_audit_event(event)


def _memory_is_redacted(record: MemoryRecord) -> bool:
    return any(str(tag).casefold() == "redacted" for tag in record.tags)


def _memory_is_forgotten(record: MemoryRecord) -> bool:
    return record.status == MemoryStatus.FORGOTTEN or record.deleted_at is not None


__all__ = ["MemoryEmbeddingWorker"]
