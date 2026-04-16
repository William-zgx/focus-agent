from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import re
import uuid

from langchain.messages import HumanMessage, SystemMessage
from langgraph_sdk import get_sync_client

from ..core.branching import (
    BranchMeta,
    BranchRecord,
    BranchRole,
    BranchStatus,
    BranchTreeNode,
    ImportedConclusion,
    MergeDecision,
    MergeProposalOverrides,
    MergeProposal,
    MergeTarget,
)
from ..core.merge_review import generate_merge_proposal
from ..core.request_context import RequestContext
from ..core.types import FindingItem
from ..memory import MemoryWriter
from ..model_registry import create_chat_model
from ..repositories.branch_repository import BranchRepository
from ..storage.import_memory import persist_imported_conclusion
from ..storage.namespaces import branch_namespace, conversation_main_namespace
from ..config import Settings


class BranchService:
    _DEFAULT_MAX_BRANCH_DEPTH = 5
    _DEFAULT_PENDING_BRANCH_NAME = "New Branch"
    _ROLE_FALLBACK_NAMES = {
        BranchRole.MAIN: "Main",
        BranchRole.EXPLORE_ALTERNATIVES: "Alternative Path",
        BranchRole.DEEP_DIVE: "Deep Dive",
        BranchRole.VERIFY: "Verification",
        BranchRole.WRITEUP: "Writeup",
    }
    _BRANCH_NAME_STOPWORDS = {
        "a",
        "an",
        "and",
        "analyze",
        "branch",
        "chat",
        "deep",
        "dive",
        "explore",
        "focus",
        "for",
        "from",
        "help",
        "if",
        "in",
        "into",
        "investigate",
        "main",
        "need",
        "needed",
        "on",
        "only",
        "path",
        "please",
        "recent",
        "review",
        "the",
        "this",
        "thread",
        "topic",
        "user",
        "use",
        "verify",
        "with",
        "draft",
        "writeup",
    }

    def __init__(
        self,
        *,
        settings: Settings,
        graph,
        repo: BranchRepository,
        store=None,
        memory_writer: MemoryWriter | None = None,
    ):
        self.settings = settings
        self.graph = graph
        self.repo = repo
        self.store = store
        self.memory_writer = memory_writer
        self.thread_client = get_sync_client(url=settings.langgraph_api_url) if settings.langgraph_api_url else None
        self.proposal_model = create_chat_model(settings.model, temperature=0)

    def _persist_branch_findings_to_branch_memory(
        self,
        *,
        branch_record: BranchRecord,
        findings: list[object],
    ) -> list[str]:
        if self.store is None:
            return []
        context = self._build_branch_request_context(branch_record)
        memory_writer = getattr(self, "memory_writer", None)
        if memory_writer is not None:
            return memory_writer.write_branch_findings(
                context=context,
                branch_name=branch_record.branch_name,
                findings=[self._coerce_finding_item(finding) for finding in findings],
            )

        namespace = branch_namespace(branch_record.root_thread_id, branch_record.branch_id)
        keys: list[str] = []
        for finding in findings:
            item = self._coerce_finding_item(finding)
            key = str(uuid.uuid4())
            self.store.put(
                namespace,
                key,
                {
                    "type": "branch_finding",
                    "branch_id": branch_record.branch_id,
                    "branch_name": branch_record.branch_name,
                    "summary": item.finding,
                    "evidence_refs": item.evidence_refs,
                    "confidence": item.confidence,
                },
            )
            keys.append(key)
        return keys

    @staticmethod
    def _imported_conclusion_message(imported: ImportedConclusion) -> str:
        lines = [f"Imported conclusion from branch '{imported.branch_name}':", imported.summary.strip()]
        key_findings = [item.strip() for item in imported.key_findings if str(item).strip()]
        if key_findings:
            lines.append("")
            lines.append("Key findings:")
            lines.extend(f"- {item}" for item in key_findings)
        evidence_refs = [item.strip() for item in imported.evidence_refs if str(item).strip()]
        if evidence_refs:
            lines.append("")
            lines.append(f"Evidence refs: {', '.join(evidence_refs)}")
        return "\n".join(lines).strip()

    @staticmethod
    def _append_imported_summary(existing_summary: object, imported: ImportedConclusion) -> str:
        previous = str(existing_summary or "").strip()
        imported_line = f"Imported from {imported.branch_name}: {imported.summary.strip()}".strip()
        combined = "\n".join(part for part in [previous, imported_line] if part)
        if len(combined) > 4000:
            combined = combined[-4000:]
        return combined

    @staticmethod
    def _clean_list_override(items: object) -> list[str]:
        cleaned: list[str] = []
        for item in items or []:
            text = str(item).strip()
            if text:
                cleaned.append(text)
        return cleaned

    def _apply_merge_proposal_overrides(
        self,
        *,
        proposal: MergeProposal,
        overrides: MergeProposalOverrides | None,
    ) -> MergeProposal:
        if overrides is None:
            return proposal

        proposal_payload = proposal.model_dump(mode='json')
        override_payload = overrides.model_dump(exclude_none=True, mode='json')
        if 'summary' in override_payload:
            override_payload['summary'] = str(override_payload['summary']).strip()
        for key in ('key_findings', 'open_questions', 'evidence_refs', 'artifacts'):
            if key in override_payload:
                override_payload[key] = self._clean_list_override(override_payload[key])

        merged = MergeProposal.model_validate({**proposal_payload, **override_payload})
        if not merged.summary.strip():
            raise ValueError('Merge proposal summary cannot be empty.')
        return merged

    def promote_branch_findings_to_main_memory(
        self,
        *,
        branch_record: BranchRecord,
        findings: list[object],
    ) -> list[str]:
        if self.store is None:
            return []
        context = self._build_branch_request_context(branch_record)
        memory_writer = getattr(self, "memory_writer", None)
        if memory_writer is not None:
            return memory_writer.promote_branch_findings(
                context=context,
                branch_id=branch_record.branch_id,
                findings=[self._coerce_finding_item(finding) for finding in findings],
            )

        namespace = conversation_main_namespace(branch_record.root_thread_id)
        keys: list[str] = []
        for finding in findings:
            item = self._coerce_finding_item(finding)
            key = str(uuid.uuid4())
            self.store.put(
                namespace,
                key,
                {
                    "type": "promoted_branch_finding",
                    "branch_id": branch_record.branch_id,
                    "branch_name": branch_record.branch_name,
                    "summary": item.finding,
                    "evidence_refs": item.evidence_refs,
                    "confidence": item.confidence,
                },
            )
            keys.append(key)
        return keys

    @staticmethod
    def _coerce_finding_item(value: object) -> FindingItem:
        if isinstance(value, FindingItem):
            return value
        if isinstance(value, dict):
            return FindingItem.model_validate(value)
        return FindingItem(finding=str(value))

    @staticmethod
    def _build_branch_request_context(branch_record: BranchRecord) -> RequestContext:
        return RequestContext(
            user_id=branch_record.owner_user_id,
            root_thread_id=branch_record.root_thread_id,
            branch_id=branch_record.branch_id,
            parent_thread_id=branch_record.parent_thread_id,
            branch_role=branch_record.branch_role.value,
        )

    @staticmethod
    def _message_content_to_text(content: object) -> str:
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if text:
                        parts.append(str(text))
                elif item is not None:
                    parts.append(str(item))
            return " ".join(parts).strip()
        if content is None:
            return ""
        return str(content).strip()

    @classmethod
    def _sanitize_branch_name(cls, value: str | None, *, branch_role: BranchRole) -> str:
        text = str(value or "").strip()
        if not text:
            return cls._ROLE_FALLBACK_NAMES[branch_role]
        text = re.sub(r"^[^A-Za-z0-9\u4e00-\u9fff]+", "", text)
        text = re.sub(r"^(branch\s*name|name)\s*:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[`\"“”‘’]+", "", text)
        text = re.sub(r"\s+", " ", text).strip(" -–—.,;:!?")
        if re.search(r"[\u4e00-\u9fff]", text):
            compact = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text))
            return (compact[:12] or cls._ROLE_FALLBACK_NAMES[branch_role]).strip()
        words = text.split()
        if len(words) > 4:
            text = " ".join(words[:4])
        return (text[:36].strip() or cls._ROLE_FALLBACK_NAMES[branch_role]).strip()

    @classmethod
    def _fallback_branch_name(cls, raw_text: str, branch_role: BranchRole) -> str:
        cjk_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", raw_text or "")
        if cjk_chunks:
            return cls._sanitize_branch_name("".join(cjk_chunks), branch_role=branch_role)
        tokens = re.findall(r"[A-Za-z0-9]+", raw_text or "")
        meaningful = [
            token.lower()
            for token in tokens
            if len(token) > 1 and token.lower() not in cls._BRANCH_NAME_STOPWORDS
        ]
        if meaningful:
            label = " ".join(word.capitalize() for word in meaningful[:4])
            return cls._sanitize_branch_name(label, branch_role=branch_role)
        return cls._ROLE_FALLBACK_NAMES[branch_role]

    def _collect_branch_name_context(self, *, thread_values: dict, name_source: str | None = None) -> str:
        sections: list[str] = []
        if name_source and name_source.strip():
            sections.append(f"Draft focus:\n{name_source.strip()}")
        messages = thread_values.get("messages") or []
        recent_messages: list[str] = []
        for message in reversed(messages):
            message_type = getattr(message, "type", None) or message.__class__.__name__.replace("Message", "").lower()
            content = self._message_content_to_text(getattr(message, "content", ""))
            if not content:
                continue
            speaker = "User" if message_type == "human" else "Assistant" if message_type == "ai" else message_type.title()
            recent_messages.append(f"{speaker}: {content}")
            if len(recent_messages) == 4:
                break
        if recent_messages:
            sections.append("Recent branch conversation:\n" + "\n".join(reversed(recent_messages)))
        summary = str(thread_values.get("rolling_summary") or "").strip()
        if summary:
            sections.append(f"Branch summary:\n{summary[:400]}")
        return "\n\n".join(section for section in sections if section.strip())

    def _generate_branch_name(self, *, thread_values: dict, branch_role: BranchRole) -> str:
        context = self._collect_branch_name_context(thread_values=thread_values)
        model = getattr(self, "proposal_model", None)
        if model and context:
            try:
                response = model.invoke(
                    [
                        SystemMessage(
                            content=(
                                "Generate a concise branch name for a research assistant. "
                                "Return only the name, 2 to 4 words, with no quotes or punctuation unless a hyphen is necessary."
                            )
                        ),
                        HumanMessage(
                            content=(
                                f"Branch role: {branch_role.value.replace('_', ' ')}\n\n"
                                f"{context}"
                            )
                        ),
                    ]
                )
                candidate = self._message_content_to_text(getattr(response, "content", response))
                if candidate:
                    return self._sanitize_branch_name(candidate, branch_role=branch_role)
            except Exception:
                pass
        return self._fallback_branch_name(context, branch_role)

    def _resolve_branch_name(
        self,
        *,
        preferred_name: str | None,
        thread_values: dict,
        branch_role: BranchRole,
    ) -> str:
        if preferred_name and preferred_name.strip():
            return self._sanitize_branch_name(preferred_name, branch_role=branch_role)
        return self._generate_branch_name(
            thread_values=thread_values,
            branch_role=branch_role,
        )

    def _resolve_initial_branch_name(
        self,
        *,
        preferred_name: str | None,
        parent_values: dict,
        name_source: str | None,
        branch_role: BranchRole,
    ) -> str:
        if preferred_name and preferred_name.strip():
            return self._sanitize_branch_name(preferred_name, branch_role=branch_role)
        del parent_values, name_source
        return self._DEFAULT_PENDING_BRANCH_NAME

    def _derive_root_thread_id(self, parent_thread_id: str, parent_state: dict) -> str:
        meta = parent_state.get('branch_meta') or {}
        root_thread_id = meta.get('root_thread_id')
        if root_thread_id:
            return str(root_thread_id)
        try:
            record = self.repo.get_by_child_thread_id(parent_thread_id)
        except Exception:
            return parent_thread_id
        return record.root_thread_id

    def _derive_parent_branch_depth(self, parent_thread_id: str, parent_state: dict) -> int:
        meta = parent_state.get('branch_meta') or {}
        if meta.get('branch_depth') is not None:
            return int(meta.get('branch_depth') or 0)
        try:
            record = self.repo.get_by_child_thread_id(parent_thread_id)
        except Exception:
            return 0
        return record.branch_depth

    def _max_branch_depth(self) -> int:
        settings = getattr(self, "settings", None)
        value = getattr(settings, "branch_max_depth", self._DEFAULT_MAX_BRANCH_DEPTH)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return self._DEFAULT_MAX_BRANCH_DEPTH

    def _ensure_branch_depth_allowed(self, *, parent_thread_id: str, parent_values: dict) -> int:
        parent_depth = self._derive_parent_branch_depth(parent_thread_id, parent_values)
        next_depth = parent_depth + 1
        max_depth = self._max_branch_depth()
        if next_depth > max_depth:
            raise ValueError(f"Maximum branch depth is {max_depth}.")
        return next_depth

    @staticmethod
    def _branch_meta_payload_from_record(record: BranchRecord, existing_meta: dict | None = None) -> dict[str, object]:
        payload = dict(existing_meta or {})
        payload.pop('conclusion_policy', None)
        payload.update(
            {
                'branch_id': record.branch_id,
                'root_thread_id': record.root_thread_id,
                'parent_thread_id': record.parent_thread_id,
                'return_thread_id': record.return_thread_id,
                'branch_name': record.branch_name,
                'branch_role': record.branch_role.value,
                'branch_depth': record.branch_depth,
                'branch_status': record.branch_status.value,
                'is_archived': record.is_archived,
                'archived_at': record.archived_at,
                'fork_checkpoint_id': record.fork_checkpoint_id,
                'fork_strategy': record.fork_strategy,
            }
        )
        return payload

    def _build_tree_node(self, record: BranchRecord, by_parent: dict[str, list[BranchRecord]]) -> BranchTreeNode:
        return BranchTreeNode(
            thread_id=record.child_thread_id,
            root_thread_id=record.root_thread_id,
            parent_thread_id=record.parent_thread_id,
            branch_id=record.branch_id,
            branch_name=record.branch_name,
            branch_role=record.branch_role,
            branch_status=record.branch_status,
            is_archived=record.is_archived,
            archived_at=record.archived_at,
            branch_depth=record.branch_depth,
            fork_strategy=record.fork_strategy,
            children=[self._build_tree_node(child, by_parent) for child in by_parent.get(record.child_thread_id, [])],
        )

    def _ensure_root_thread_access(self, *, root_thread_id: str, user_id: str) -> None:
        owner = self.repo.get_thread_owner(thread_id=root_thread_id)
        if owner is None:
            self.repo.ensure_thread_owner(
                thread_id=root_thread_id,
                root_thread_id=root_thread_id,
                owner_user_id=user_id,
            )
            return
        self.repo.assert_thread_owner(thread_id=root_thread_id, owner_user_id=user_id)

    def _ensure_parent_thread_access(self, *, parent_thread_id: str, user_id: str) -> None:
        try:
            self.repo.get_by_child_thread_id(parent_thread_id)
        except Exception:
            self._ensure_root_thread_access(root_thread_id=parent_thread_id, user_id=user_id)
            return
        self.repo.assert_thread_owner(thread_id=parent_thread_id, owner_user_id=user_id)

    def fork_branch(
        self,
        *,
        parent_thread_id: str,
        user_id: str,
        branch_name: str | None = None,
        name_source: str | None = None,
        branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES,
        fork_checkpoint_id: str | None = None,
    ) -> BranchRecord:
        self._ensure_parent_thread_access(parent_thread_id=parent_thread_id, user_id=user_id)
        parent_config = {'configurable': {'thread_id': parent_thread_id}}
        parent_snapshot = self.graph.get_state(parent_config)
        parent_values = deepcopy(parent_snapshot.values)
        root_thread_id = self._derive_root_thread_id(parent_thread_id, parent_values)
        next_branch_depth = self._ensure_branch_depth_allowed(
            parent_thread_id=parent_thread_id,
            parent_values=parent_values,
        )
        resolved_branch_name = self._resolve_initial_branch_name(
            preferred_name=branch_name,
            parent_values=parent_values,
            name_source=name_source,
            branch_role=branch_role,
        )
        branch_id = str(uuid.uuid4())
        child_thread_id: str
        fork_strategy: str

        if self.thread_client and fork_checkpoint_id is None:
            copied = self.thread_client.threads.copy(parent_thread_id)
            child_thread_id = copied['thread_id']
            fork_strategy = 'copy_thread'
        else:
            child_thread_id = str(uuid.uuid4())
            fork_strategy = 'local_snapshot_seed'
            self.graph.update_state(
                {'configurable': {'thread_id': child_thread_id}},
                parent_values,
                as_node='bootstrap_turn',
            )

        branch_meta = BranchMeta(
            branch_id=branch_id,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
            return_thread_id=parent_thread_id,
            branch_name=resolved_branch_name,
            branch_role=branch_role,
            branch_depth=next_branch_depth,
            branch_status=BranchStatus.ACTIVE,
            fork_checkpoint_id=fork_checkpoint_id,
            fork_strategy=fork_strategy,
        )
        branch_meta_payload = branch_meta.model_dump(mode='json')
        branch_meta_payload['branch_name_pending_ai'] = branch_name is None

        self.graph.update_state(
            {'configurable': {'thread_id': child_thread_id}},
            {
                'branch_meta': branch_meta_payload,
                'merge_proposal': None,
                'merge_decision': None,
                'branch_local_findings': [],
            },
            as_node='bootstrap_turn',
        )
        self.repo.ensure_thread_owner(
            thread_id=child_thread_id,
            root_thread_id=root_thread_id,
            owner_user_id=user_id,
        )

        record = BranchRecord(
            branch_id=branch_id,
            root_thread_id=root_thread_id,
            parent_thread_id=parent_thread_id,
            child_thread_id=child_thread_id,
            return_thread_id=parent_thread_id,
            owner_user_id=user_id,
            branch_name=resolved_branch_name,
            branch_role=branch_role,
            branch_depth=branch_meta.branch_depth,
            branch_status=BranchStatus.ACTIVE,
            fork_checkpoint_id=fork_checkpoint_id,
            fork_strategy=fork_strategy,
        )
        self.repo.create(record)
        return record

    def refresh_branch_name(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        name_source: str | None = None,
        force: bool = False,
    ) -> BranchRecord | None:
        self.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        branch_record = self.repo.get_by_child_thread_id(child_thread_id)
        if not force and not branch_record.branch_name.strip():
            force = True
        if self.proposal_model is None and not force:
            return branch_record

        child_config = {'configurable': {'thread_id': child_thread_id}}
        child_snapshot = self.graph.get_state(child_config)
        child_values = deepcopy(child_snapshot.values)
        generated_name = self._generate_branch_name(
            thread_values=child_values,
            branch_role=branch_record.branch_role,
        )
        next_name = self._sanitize_branch_name(generated_name, branch_role=branch_record.branch_role)
        if not next_name or next_name == branch_record.branch_name:
            return branch_record

        self.repo.update_branch_name(branch_record.branch_id, next_name)
        existing_meta = child_values.get('branch_meta') or {}
        updated_record = branch_record.model_copy(update={'branch_name': next_name})
        self.graph.update_state(
            child_config,
            {'branch_meta': self._branch_meta_payload_from_record(updated_record, existing_meta)},
            as_node='bootstrap_turn',
        )
        return updated_record

    def refresh_branch_name_after_first_turn(
        self,
        *,
        child_thread_id: str,
        user_id: str,
    ) -> BranchRecord | None:
        try:
            self.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
            child_config = {'configurable': {'thread_id': child_thread_id}}
            child_snapshot = self.graph.get_state(child_config)
            child_values = deepcopy(child_snapshot.values)
            existing_meta = dict(child_values.get('branch_meta') or {})
            if not existing_meta.get('branch_name_pending_ai'):
                return None

            updated_record = self.refresh_branch_name(
                child_thread_id=child_thread_id,
                user_id=user_id,
                name_source=None,
                force=True,
            )

            refreshed_snapshot = self.graph.get_state(child_config)
            refreshed_values = deepcopy(refreshed_snapshot.values)
            refreshed_meta = dict(refreshed_values.get('branch_meta') or {})
            refreshed_meta['branch_name_pending_ai'] = False
            self.graph.update_state(
                child_config,
                {'branch_meta': refreshed_meta},
                as_node='bootstrap_turn',
            )
            return updated_record
        except Exception:
            return None

    def prepare_merge_proposal(self, *, child_thread_id: str, user_id: str) -> MergeProposal:
        self.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        child_config = {'configurable': {'thread_id': child_thread_id}}
        snapshot = self.graph.get_state(child_config)
        values = deepcopy(snapshot.values)
        branch_record = self.repo.get_by_child_thread_id(child_thread_id)
        self.repo.update_status(branch_record.branch_id, BranchStatus.PREPARING_MERGE_REVIEW)
        preparing_record = self.repo.get(branch_record.branch_id)
        self.graph.update_state(
            child_config,
            {
                'branch_meta': self._branch_meta_payload_from_record(
                    preparing_record,
                    existing_meta=dict(values.get('branch_meta') or {}),
                ),
            },
            as_node='bootstrap_turn',
        )
        self._persist_branch_findings_to_branch_memory(
            branch_record=branch_record,
            findings=list(values.get('branch_local_findings', [])),
        )
        try:
            proposal = generate_merge_proposal(self.proposal_model, values, values.get('branch_meta'))
            self.repo.save_merge_proposal(branch_record.branch_id, proposal)
            self.repo.update_status(branch_record.branch_id, BranchStatus.AWAITING_MERGE_REVIEW)
            updated_record = self.repo.get(branch_record.branch_id)

            self.graph.update_state(
                child_config,
                {
                    'merge_proposal': proposal.model_dump(mode='json'),
                    'branch_meta': self._branch_meta_payload_from_record(
                        updated_record,
                        existing_meta=dict(values.get('branch_meta') or {}),
                    ),
                },
                as_node='summarize_turn',
            )
            return proposal
        except Exception:
            self.repo.update_status(branch_record.branch_id, BranchStatus.ACTIVE)
            reverted_record = self.repo.get(branch_record.branch_id)
            self.graph.update_state(
                child_config,
                {
                    'branch_meta': self._branch_meta_payload_from_record(
                        reverted_record,
                        existing_meta=dict(values.get('branch_meta') or {}),
                    ),
                },
                as_node='bootstrap_turn',
            )
            raise

    def apply_merge_decision(
        self,
        *,
        child_thread_id: str,
        decision: MergeDecision,
        context: RequestContext,
        proposal_overrides: MergeProposalOverrides | None = None,
    ) -> ImportedConclusion | None:
        self.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=context.user_id)
        branch_record = self.repo.get_by_child_thread_id(child_thread_id)
        child_config = {'configurable': {'thread_id': child_thread_id}}
        snapshot = self.graph.get_state(child_config)
        values = deepcopy(snapshot.values)
        proposal_dict = values.get('merge_proposal') or branch_record.merge_proposal
        if not proposal_dict:
            raise ValueError('No merge proposal found for this child thread.')
        proposal = self._apply_merge_proposal_overrides(
            proposal=MergeProposal.model_validate(proposal_dict),
            overrides=proposal_overrides,
        )
        if proposal_overrides is not None:
            self.repo.save_merge_proposal(branch_record.branch_id, proposal)

        self.repo.save_merge_decision(branch_record.branch_id, decision)
        self.graph.update_state(
            child_config,
            {
                'merge_proposal': proposal.model_dump(mode='json'),
                'merge_decision': decision.model_dump(mode='json'),
            },
            as_node='maybe_interrupt_for_merge',
        )

        if not decision.approved or decision.mode.value == 'none':
            self.repo.update_status(branch_record.branch_id, BranchStatus.DISCARDED)
            discarded_record = self.repo.get(branch_record.branch_id)
            self.graph.update_state(
                child_config,
                {
                    'branch_meta': self._branch_meta_payload_from_record(
                        discarded_record,
                        existing_meta=dict(values.get('branch_meta') or {}),
                    )
                },
                as_node='bootstrap_turn',
            )
            return None

        artifacts = proposal.artifacts
        if decision.mode.value == 'selected_artifacts' and decision.selected_artifacts:
            allowed = set(decision.selected_artifacts)
            artifacts = [a for a in proposal.artifacts if a in allowed]

        imported = ImportedConclusion(
            branch_id=branch_record.branch_id,
            branch_name=branch_record.branch_name,
            mode=decision.mode,
            summary=proposal.summary,
            key_findings=proposal.key_findings,
            evidence_refs=proposal.evidence_refs if decision.mode.value != 'summary_only' else [],
            artifacts=artifacts,
            rationale=decision.rationale,
        )

        imported_findings = [
            FindingItem(
                finding=item,
                evidence_refs=proposal.evidence_refs if decision.mode.value != 'summary_only' else [],
                source_branch_id=branch_record.branch_id,
            )
            for item in proposal.key_findings
        ]

        target_thread_id = (
            branch_record.root_thread_id
            if decision.target == MergeTarget.ROOT_THREAD
            else branch_record.return_thread_id
        )
        target_config = {'configurable': {'thread_id': target_thread_id}}
        target_snapshot = self.graph.get_state(target_config)
        target_values = deepcopy(getattr(target_snapshot, "values", {}) or {})
        import_notice = SystemMessage(content=self._imported_conclusion_message(imported))
        self.graph.update_state(
            target_config,
            {
                'messages': [import_notice],
                'rolling_summary': self._append_imported_summary(
                    target_values.get('rolling_summary'),
                    imported,
                ),
                'merge_queue': [imported.model_dump(mode='json')],
                'imported_findings': [finding.model_dump(mode='json') for finding in imported_findings],
            },
            as_node='bootstrap_turn',
        )
        is_returning_to_root_main = target_thread_id == branch_record.root_thread_id
        if self.store is not None and is_returning_to_root_main:
            memory_context = RequestContext(
                user_id=context.user_id,
                root_thread_id=branch_record.root_thread_id,
                parent_thread_id=target_thread_id,
                branch_id=branch_record.branch_id,
                branch_role=branch_record.branch_role.value,
            )
            memory_writer = getattr(self, "memory_writer", None)
            if memory_writer is not None:
                memory_writer.write_imported_conclusion(context=memory_context, imported=imported)
            else:
                persist_imported_conclusion(self.store, memory_context, imported)
            self.promote_branch_findings_to_main_memory(
                branch_record=branch_record,
                findings=list(values.get('branch_local_findings', [])),
            )
        self.repo.update_status(branch_record.branch_id, BranchStatus.MERGED)
        merged_record = self.repo.get(branch_record.branch_id)
        self.graph.update_state(
            child_config,
            {
                'branch_meta': self._branch_meta_payload_from_record(
                    merged_record,
                    existing_meta=dict(values.get('branch_meta') or {}),
                )
            },
            as_node='bootstrap_turn',
        )
        return imported

    def get_branch_tree(self, *, root_thread_id: str, user_id: str) -> BranchTreeNode:
        self._ensure_root_thread_access(root_thread_id=root_thread_id, user_id=user_id)
        records = self.repo.list_by_root_thread_id(root_thread_id)
        by_parent: dict[str, list[BranchRecord]] = defaultdict(list)
        for record in records:
            if record.is_archived:
                continue
            by_parent[record.parent_thread_id].append(record)

        return BranchTreeNode(
            thread_id=root_thread_id,
            root_thread_id=root_thread_id,
            branch_name='main',
            branch_role=BranchRole.MAIN,
            branch_status=BranchStatus.ACTIVE,
            is_archived=False,
            branch_depth=0,
            children=[self._build_tree_node(child, by_parent) for child in by_parent.get(root_thread_id, [])],
        )

    def list_archived_branches(self, *, root_thread_id: str, user_id: str) -> list[BranchTreeNode]:
        self._ensure_root_thread_access(root_thread_id=root_thread_id, user_id=user_id)
        records = self.repo.list_by_root_thread_id(root_thread_id)
        archived_records = [record for record in records if record.is_archived]
        archived_records.sort(key=lambda record: (record.branch_depth, record.branch_name, record.child_thread_id))
        return [
            BranchTreeNode(
                thread_id=record.child_thread_id,
                root_thread_id=record.root_thread_id,
                parent_thread_id=record.parent_thread_id,
                branch_id=record.branch_id,
                branch_name=record.branch_name,
                branch_role=record.branch_role,
                branch_status=record.branch_status,
                is_archived=True,
                archived_at=record.archived_at,
                branch_depth=record.branch_depth,
                fork_strategy=record.fork_strategy,
            )
            for record in archived_records
        ]

    def _set_branch_archive_state(self, *, child_thread_id: str, user_id: str, is_archived: bool) -> BranchRecord:
        self.repo.assert_thread_owner(thread_id=child_thread_id, owner_user_id=user_id)
        branch_record = self.repo.get_by_child_thread_id(child_thread_id)
        self.repo.update_archive_state(branch_record.branch_id, is_archived=is_archived)
        updated_record = self.repo.get(branch_record.branch_id)

        if self.graph is not None:
            child_config = {'configurable': {'thread_id': child_thread_id}}
            snapshot = self.graph.get_state(child_config)
            values = deepcopy(snapshot.values)
            branch_meta = self._branch_meta_payload_from_record(
                updated_record,
                existing_meta=dict(values.get('branch_meta') or {}),
            )
            self.graph.update_state(
                child_config,
                {'branch_meta': branch_meta},
                as_node='bootstrap_turn',
            )
        return updated_record

    def archive_branch(self, *, child_thread_id: str, user_id: str) -> BranchRecord:
        return self._set_branch_archive_state(child_thread_id=child_thread_id, user_id=user_id, is_archived=True)

    def activate_branch(self, *, child_thread_id: str, user_id: str) -> BranchRecord:
        return self._set_branch_archive_state(child_thread_id=child_thread_id, user_id=user_id, is_archived=False)
