from __future__ import annotations

from typing import Any

from langchain.messages import SystemMessage
from pydantic import ValidationError

from ..core.branching import BranchMeta, BranchStatus
from ..core.request_context import RequestContext
from ..core.state import normalize_agent_state
from ..core.types import ConversationRecord


class ChatThreadAccessMixin:
    def _safe_snapshot(self, thread_id: str):
        try:
            return self.runtime.graph.get_state({'configurable': {'thread_id': thread_id}})
        except Exception:
            return None

    def _safe_get_values(self, thread_id: str) -> dict[str, Any]:
        snapshot = self._safe_snapshot(thread_id)
        values = normalize_agent_state(dict(getattr(snapshot, 'values', {}) or {})) if snapshot else normalize_agent_state()
        return self._backfill_import_records(thread_id=thread_id, values=values)

    def _safe_get_interrupts(self, thread_id: str) -> list[Any]:
        snapshot = self._safe_snapshot(thread_id)
        return list(getattr(snapshot, 'interrupts', []) or []) if snapshot else []

    @staticmethod
    def _imported_conclusion_message(imported: dict[str, Any]) -> str:
        summary = str(imported.get('summary') or '').strip()
        if not summary:
            return ''
        branch_name = str(imported.get('branch_name') or imported.get('branch_id') or 'unknown branch').strip()
        lines = [f"Imported conclusion from branch '{branch_name}':", summary]
        key_findings = [str(item).strip() for item in imported.get('key_findings', []) if str(item).strip()]
        if key_findings:
            lines.append('')
            lines.append('Key findings:')
            lines.extend(f"- {item}" for item in key_findings)
        evidence_refs = [str(item).strip() for item in imported.get('evidence_refs', []) if str(item).strip()]
        if evidence_refs:
            lines.append('')
            lines.append(f"Evidence refs: {', '.join(evidence_refs)}")
        return '\n'.join(lines).strip()

    @staticmethod
    def _append_imported_summary(existing_summary: Any, imported: dict[str, Any]) -> str:
        previous = str(existing_summary or '').strip()
        summary = str(imported.get('summary') or '').strip()
        if not summary:
            return previous
        branch_name = str(imported.get('branch_name') or imported.get('branch_id') or 'unknown branch').strip()
        imported_line = f"Imported from {branch_name}: {summary}"
        if imported_line in previous:
            return previous
        combined = '\n'.join(part for part in [previous, imported_line] if part)
        if len(combined) > 4000:
            combined = combined[-4000:]
        return combined

    def _backfill_import_records(self, *, thread_id: str, values: dict[str, Any]) -> dict[str, Any]:
        merge_queue = [item for item in values.get('merge_queue', []) if isinstance(item, dict)]
        if not merge_queue:
            return values

        messages = list(values.get('messages', []))
        existing_contents = {
            self._message_content_to_text(getattr(message, 'content', '')).strip()
            for message in messages
        }
        appended_messages: list[SystemMessage] = []
        updated_summary = values.get('rolling_summary', '')

        for imported in merge_queue:
            notice = self._imported_conclusion_message(imported)
            if notice and notice not in existing_contents:
                appended_messages.append(SystemMessage(content=notice))
                existing_contents.add(notice)
            updated_summary = self._append_imported_summary(updated_summary, imported)

        payload: dict[str, Any] = {}
        if appended_messages:
            payload['messages'] = appended_messages
            values = {**values, 'messages': messages + appended_messages}
        if updated_summary != values.get('rolling_summary', ''):
            payload['rolling_summary'] = updated_summary
            values = {**values, 'rolling_summary': updated_summary}

        if payload and hasattr(self.runtime.graph, 'update_state'):
            try:
                self.runtime.graph.update_state(
                    {'configurable': {'thread_id': thread_id}},
                    payload,
                    as_node='bootstrap_turn',
                )
            except Exception:
                pass

        return values

    def _branch_meta_from_repo(self, thread_id: str) -> BranchMeta | None:
        try:
            record = self.runtime.repo.get_by_child_thread_id(thread_id)
        except Exception:
            return None
        return BranchMeta(
            branch_id=record.branch_id,
            root_thread_id=record.root_thread_id,
            parent_thread_id=record.parent_thread_id,
            return_thread_id=record.return_thread_id,
            branch_name=record.branch_name,
            branch_role=record.branch_role,
            branch_depth=record.branch_depth,
            branch_status=record.branch_status,
            is_archived=record.is_archived,
            archived_at=record.archived_at,
            fork_checkpoint_id=record.fork_checkpoint_id,
            fork_strategy=record.fork_strategy,
        )

    def _branch_meta(self, *, thread_id: str, values: dict[str, Any]) -> BranchMeta | None:
        meta = values.get('branch_meta')
        repo_meta = self._branch_meta_from_repo(thread_id)
        if not meta:
            return repo_meta
        try:
            branch_meta = BranchMeta.model_validate(meta)
        except ValidationError:
            return repo_meta
        return repo_meta or branch_meta

    def _context_for_thread(
        self,
        *,
        thread_id: str,
        user_id: str,
        explicit_skill_hints: tuple[str, ...] | None = None,
    ) -> tuple[RequestContext, BranchMeta | None, dict[str, Any]]:
        values = self._safe_get_values(thread_id)
        branch_meta = self._branch_meta(thread_id=thread_id, values=values)
        root_thread_id = branch_meta.root_thread_id if branch_meta else thread_id
        stored_skill_hints = tuple(str(item) for item in values.get('active_skill_ids', []) or ())
        context = RequestContext(
            user_id=user_id,
            root_thread_id=root_thread_id,
            branch_id=branch_meta.branch_id if branch_meta else None,
            parent_thread_id=branch_meta.parent_thread_id if branch_meta else None,
            branch_role=branch_meta.branch_role.value if branch_meta else None,
            skill_hints=explicit_skill_hints if explicit_skill_hints is not None else stored_skill_hints,
        )
        return context, branch_meta, values

    def _preflight_thread_access(
        self,
        *,
        thread_id: str,
        user_id: str,
        explicit_skill_hints: tuple[str, ...] | None = None,
        require_writable: bool = False,
    ) -> tuple[RequestContext, BranchMeta | None, dict[str, Any]]:
        context, branch_meta, values = self._context_for_thread(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=explicit_skill_hints,
        )
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        if require_writable:
            self._ensure_thread_writable(branch_meta)
        return context, branch_meta, values

    def _ensure_access(self, *, thread_id: str, user_id: str, context: RequestContext) -> None:
        owner = self.runtime.repo.get_thread_owner(thread_id=thread_id)
        if owner is None:
            self.runtime.repo.ensure_thread_owner(
                thread_id=thread_id,
                root_thread_id=context.root_thread_id,
                owner_user_id=user_id,
            )
        else:
            self.runtime.repo.assert_thread_owner(thread_id=thread_id, owner_user_id=user_id)
        if context.branch_id is None and thread_id == context.root_thread_id:
            self._ensure_root_conversation_record(root_thread_id=context.root_thread_id, user_id=user_id)

    def _ensure_root_conversation_record(self, *, root_thread_id: str, user_id: str) -> None:
        get_conversation = getattr(self.runtime.repo, "get_conversation", None)
        create_conversation = getattr(self.runtime.repo, "create_conversation", None)
        if not callable(get_conversation) or not callable(create_conversation):
            return
        try:
            get_conversation(root_thread_id)
            return
        except KeyError:
            pass
        try:
            create_conversation(
                ConversationRecord(
                    root_thread_id=root_thread_id,
                    owner_user_id=user_id,
                    title="New Conversation",
                    title_pending_ai=True,
                )
            )
        except Exception:
            # If concurrent workers race here, another session may have already persisted it.
            # Retry the read path and only fail loudly when the conversation is still missing.
            try:
                get_conversation(root_thread_id)
            except Exception:
                raise

    @staticmethod
    def _ensure_thread_writable(branch_meta: BranchMeta | None) -> None:
        if branch_meta and branch_meta.branch_status == BranchStatus.MERGED:
            raise PermissionError('Merged branches are read-only.')
