from __future__ import annotations

import re
import uuid

from langchain.messages import HumanMessage, SystemMessage
from langgraph_sdk import get_sync_client

from ..core.branching import (
    BranchRecord,
    BranchRole,
    BranchStatus,
    BranchTreeNode,
    ImportedConclusion,
    MergeDecision,
    MergeProposalOverrides,
    MergeProposal,
)
from ..core.merge_review import generate_merge_proposal  # noqa: F401 - compatibility monkeypatch hook
from ..core.request_context import RequestContext
from ..core.types import ConversationRecord, FindingItem
from ..memory import MemoryCurator, MemoryWriter
from ..memory.models import MemoryKind, MemoryScope, MemoryVisibility, MemoryWriteRequest
from ..model_registry import create_chat_model
from ..repositories.branch_repository import BranchRepository
from ..storage.namespaces import branch_namespace, conversation_main_namespace
from ..config import Settings
from .branch_lifecycle import BranchLifecycleCoordinator
from .branch_merge import BranchMergeCoordinator
from .branch_tree import BranchTreeCoordinator


class BranchService:
    _DEFAULT_MAX_BRANCH_DEPTH = 5
    _DEFAULT_PENDING_BRANCH_NAME = "New Branch"
    _DEFAULT_PENDING_BRANCH_NAME_ZH = "新分支"
    _ROLE_FALLBACK_NAMES = {
        BranchRole.MAIN: "Main",
        BranchRole.EXPLORE_ALTERNATIVES: "Alternative Path",
        BranchRole.DEEP_DIVE: "Deep Dive",
        BranchRole.EXECUTE: "Execution",
        BranchRole.VERIFY: "Verification",
        BranchRole.WRITEUP: "Writeup",
    }
    _ROLE_FALLBACK_NAMES_ZH = {
        BranchRole.MAIN: "主线",
        BranchRole.EXPLORE_ALTERNATIVES: "备选方案",
        BranchRole.DEEP_DIVE: "深入分析",
        BranchRole.EXECUTE: "执行",
        BranchRole.VERIFY: "验证",
        BranchRole.WRITEUP: "整理",
    }
    _ROLE_CLASSIFICATION_OPTIONS = (
        BranchRole.EXPLORE_ALTERNATIVES,
        BranchRole.DEEP_DIVE,
        BranchRole.EXECUTE,
        BranchRole.VERIFY,
        BranchRole.WRITEUP,
    )
    _EXECUTE_SKILL_IDS = {
        "autopilot",
        "code-documentation",
        "eco",
        "ralph",
        "systematic-debugging",
        "tdd",
        "ultrawork",
    }
    _ROLE_KEYWORD_HINTS = {
        BranchRole.WRITEUP: (
            "documentation",
            "document",
            "draft",
            "summary",
            "summarize",
            "writeup",
            "整理",
            "总结",
            "文档",
            "汇总",
            "草稿",
        ),
        BranchRole.EXECUTE: (
            "build",
            "code",
            "fix",
            "implement",
            "integrate",
            "patch",
            "refactor",
            "wire",
            "开发",
            "实现",
            "修复",
            "接入",
            "编码",
            "重构",
        ),
        BranchRole.VERIFY: (
            "check",
            "compare",
            "confirm",
            "reproduce",
            "test",
            "validate",
            "verify",
            "复现",
            "对比",
            "核对",
            "测试",
            "确认",
            "验证",
        ),
        BranchRole.DEEP_DIVE: (
            "analyze",
            "debug",
            "deep dive",
            "inspect",
            "investigate",
            "root cause",
            "trace",
            "分析",
            "定位",
            "排查",
            "根因",
            "深挖",
            "调试",
            "调用链",
        ),
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
        self._last_memory_curator_decision: dict[str, object] | None = None
        self.thread_client = get_sync_client(url=settings.langgraph_api_url) if settings.langgraph_api_url else None
        self.proposal_model = create_chat_model(
            settings.helper_model or settings.model,
            temperature=0,
            settings=settings,
        )
        self.lifecycle = BranchLifecycleCoordinator(self)
        self.merge_workflow = BranchMergeCoordinator(self)
        self.tree_view = BranchTreeCoordinator(self)

    def _lifecycle_coordinator(self) -> BranchLifecycleCoordinator:
        coordinator = getattr(self, "lifecycle", None)
        if coordinator is None:
            coordinator = BranchLifecycleCoordinator(self)
            self.lifecycle = coordinator
        return coordinator

    def _merge_coordinator(self) -> BranchMergeCoordinator:
        coordinator = getattr(self, "merge_workflow", None)
        if coordinator is None:
            coordinator = BranchMergeCoordinator(self)
            self.merge_workflow = coordinator
        return coordinator

    def _tree_coordinator(self) -> BranchTreeCoordinator:
        coordinator = getattr(self, "tree_view", None)
        if coordinator is None:
            coordinator = BranchTreeCoordinator(self)
            self.tree_view = coordinator
        return coordinator

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

    @staticmethod
    def _filter_merge_importable_findings(findings: list[object]) -> list[FindingItem]:
        promotable: list[FindingItem] = []
        for finding in findings:
            item = BranchService._coerce_finding_item(finding)
            if item.merge_importable:
                promotable.append(item)
        return promotable

    @staticmethod
    def _main_memory_audit_tags(
        *,
        branch_record: BranchRecord,
        memory_kind: str,
        extra_tags: list[str] | None = None,
    ) -> list[str]:
        tags = [
            "audit:branch_merge_promotion",
            "target:conversation_main",
            f"kind:{memory_kind}",
            f"branch:{branch_record.branch_id}",
            f"role:{branch_record.branch_role.value}",
        ]
        for tag in extra_tags or []:
            value = str(tag).strip()
            if value:
                tags.append(value)
        return tags

    def _write_imported_conclusion_to_main_memory(
        self,
        *,
        branch_record: BranchRecord,
        context: RequestContext,
        imported: ImportedConclusion,
    ) -> str | None:
        if self.store is None:
            return None
        namespace = conversation_main_namespace(branch_record.root_thread_id)
        tags = self._main_memory_audit_tags(
            branch_record=branch_record,
            memory_kind=MemoryKind.IMPORTED_CONCLUSION.value,
            extra_tags=[branch_record.branch_name, f"mode:{imported.mode.value}"],
        )
        source_thread_id = context.parent_thread_id or context.root_thread_id
        memory_writer = getattr(self, "memory_writer", None)
        if memory_writer is not None:
            records = [
                MemoryWriteRequest(
                    kind=MemoryKind.IMPORTED_CONCLUSION,
                    scope=MemoryScope.ROOT_THREAD,
                    visibility=MemoryVisibility.SHARED,
                    namespace=namespace,
                    content=imported.summary,
                    summary=imported.summary,
                    tags=tags,
                    evidence_refs=imported.evidence_refs,
                    source_thread_id=source_thread_id,
                    source_branch_id=imported.branch_id,
                    root_thread_id=context.root_thread_id,
                    user_id=context.user_id,
                    promoted_to_main=True,
                )
            ]
            keys = memory_writer.write_records(records)
            return keys[0] if keys else None

        key = str(uuid.uuid4())
        self.store.put(
            namespace,
            key,
            {
                "type": "imported_conclusion",
                "branch_id": imported.branch_id,
                "branch_name": imported.branch_name,
                "mode": imported.mode.value,
                "summary": imported.summary,
                "key_findings": imported.key_findings,
                "evidence_refs": imported.evidence_refs,
                "artifacts": imported.artifacts,
                "tags": tags,
                "promoted_to_main": True,
                "source_thread_id": source_thread_id,
                "source_branch_id": imported.branch_id,
                "root_thread_id": context.root_thread_id,
                "user_id": context.user_id,
            },
        )
        return key

    def promote_branch_findings_to_main_memory(
        self,
        *,
        branch_record: BranchRecord,
        findings: list[object],
        memory_context: RequestContext | None = None,
    ) -> list[str]:
        self._last_memory_curator_decision = None
        if self.store is None:
            return []
        promotable_findings = self._filter_merge_importable_findings(findings)
        if not promotable_findings:
            return []
        context = memory_context or self._build_branch_request_context(branch_record)
        namespace = conversation_main_namespace(branch_record.root_thread_id)
        tags = self._main_memory_audit_tags(
            branch_record=branch_record,
            memory_kind=MemoryKind.BRANCH_FINDING.value,
            extra_tags=[branch_record.branch_name, "filter:merge_importable"],
        )
        source_thread_id = context.parent_thread_id or context.root_thread_id
        memory_writer = getattr(self, "memory_writer", None)
        settings = getattr(self, "settings", None)
        if bool(getattr(settings, "agent_memory_curator_enabled", False)):
            auto_promote = bool(getattr(settings, "agent_memory_auto_promote_on_merge", True))
            curator = MemoryCurator(store=self.store)
            decision = curator.evaluate_branch_promotion(
                branch_record=branch_record,
                findings=promotable_findings,
                context=context,
                auto_promote=auto_promote,
            )
            if not auto_promote:
                self._last_memory_curator_decision = decision.model_dump(mode="json")
                return []
            records = [
                curator.candidate_to_write_request(
                    candidate=candidate,
                    branch_record=branch_record,
                    context=context,
                    tags=list(tags),
                )
                for candidate in decision.candidates
            ]
            keys = (memory_writer or MemoryWriter(store=self.store)).write_records(records)
            decision.promoted_memory_ids = keys
            self._last_memory_curator_decision = decision.model_dump(mode="json")
            return keys
        if memory_writer is not None:
            records = [
                MemoryWriteRequest(
                    kind=MemoryKind.BRANCH_FINDING,
                    scope=MemoryScope.ROOT_THREAD,
                    visibility=MemoryVisibility.SHARED,
                    namespace=namespace,
                    content=item.finding,
                    summary=item.finding,
                    tags=list(tags),
                    evidence_refs=item.evidence_refs,
                    source_thread_id=source_thread_id,
                    source_branch_id=branch_record.branch_id,
                    root_thread_id=context.root_thread_id,
                    user_id=context.user_id,
                    confidence=item.confidence,
                    promoted_to_main=True,
                )
                for item in promotable_findings
            ]
            return memory_writer.write_records(records)

        keys: list[str] = []
        for item in promotable_findings:
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
                    "merge_importable": item.merge_importable,
                    "tags": list(tags),
                    "promoted_to_main": True,
                    "source_thread_id": source_thread_id,
                    "source_branch_id": branch_record.branch_id,
                    "root_thread_id": context.root_thread_id,
                    "user_id": context.user_id,
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

    @staticmethod
    def _detect_naming_language(raw_text: str) -> str:
        text = str(raw_text or "").strip()
        if not text:
            return "en"
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        latin_count = len(re.findall(r"[A-Za-z]", text))
        if cjk_count >= max(2, latin_count):
            return "zh"
        return "en"

    @classmethod
    def _fallback_role_name(cls, *, branch_role: BranchRole, language: str) -> str:
        if language == "zh":
            return cls._ROLE_FALLBACK_NAMES_ZH[branch_role]
        return cls._ROLE_FALLBACK_NAMES[branch_role]

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
    def _fallback_branch_name(cls, raw_text: str, branch_role: BranchRole, *, language: str) -> str:
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
        return cls._fallback_role_name(branch_role=branch_role, language=language)

    def _collect_branch_name_seed(self, *, thread_values: dict, name_source: str | None = None) -> str:
        parts: list[str] = []
        if name_source and name_source.strip():
            parts.append(name_source.strip())
        summary = str(thread_values.get("rolling_summary") or "").strip()
        if summary:
            parts.append(summary)
        messages = thread_values.get("messages") or []
        for message in reversed(messages):
            content = self._message_content_to_text(getattr(message, "content", ""))
            if content:
                parts.append(content)
            if len(parts) >= 6:
                break
        return "\n".join(parts).strip()

    def _collect_branch_name_context(
        self,
        *,
        thread_values: dict,
        name_source: str | None = None,
        language: str = "en",
    ) -> str:
        sections: list[str] = []
        if name_source and name_source.strip():
            heading = "命名线索" if language == "zh" else "Draft focus"
            sections.append(f"{heading}:\n{name_source.strip()}")
        messages = thread_values.get("messages") or []
        recent_messages: list[str] = []
        for message in reversed(messages):
            message_type = getattr(message, "type", None) or message.__class__.__name__.replace("Message", "").lower()
            content = self._message_content_to_text(getattr(message, "content", ""))
            if not content:
                continue
            if language == "zh":
                speaker = "用户" if message_type == "human" else "助手" if message_type == "ai" else "系统"
            else:
                speaker = "User" if message_type == "human" else "Assistant" if message_type == "ai" else message_type.title()
            recent_messages.append(f"{speaker}: {content}")
            if len(recent_messages) == 4:
                break
        if recent_messages:
            heading = "最近对话" if language == "zh" else "Recent branch conversation"
            sections.append(f"{heading}:\n" + "\n".join(reversed(recent_messages)))
        summary = str(thread_values.get("rolling_summary") or "").strip()
        if summary:
            heading = "对话摘要" if language == "zh" else "Branch summary"
            sections.append(f"{heading}:\n{summary[:400]}")
        return "\n\n".join(section for section in sections if section.strip())

    @staticmethod
    def _normalize_branch_role_candidate(value: object) -> BranchRole | None:
        text = str(value or "").strip().strip("`\"'").lower()
        if not text:
            return None
        normalized = text.replace("-", "_").replace(" ", "_")
        aliases = {
            "deepdive": "deep_dive",
            "explore": "explore_alternatives",
            "exploration": "explore_alternatives",
            "execution": "execute",
            "implement": "execute",
            "verification": "verify",
            "writing": "writeup",
            "write_up": "writeup",
            "summary": "writeup",
        }
        normalized = aliases.get(normalized, normalized)
        try:
            role = BranchRole(normalized)
        except ValueError:
            return None
        if role == BranchRole.MAIN:
            return None
        return role

    def _collect_branch_role_context(self, *, thread_values: dict) -> str:
        seed_text = self._collect_branch_name_seed(thread_values=thread_values)
        language = self._detect_naming_language(seed_text)
        sections: list[str] = []
        prompt_mode = getattr(thread_values.get("prompt_mode"), "value", thread_values.get("prompt_mode"))
        if prompt_mode:
            label = "当前模式" if language == "zh" else "Prompt mode"
            sections.append(f"{label}: {prompt_mode}")
        active_skill_ids = [str(item).strip() for item in thread_values.get("active_skill_ids", []) if str(item).strip()]
        if active_skill_ids:
            label = "激活技能" if language == "zh" else "Active skills"
            sections.append(f"{label}: {', '.join(active_skill_ids[:6])}")
        conversation = self._collect_branch_name_context(
            thread_values=thread_values,
            language=language,
        )
        if conversation:
            sections.append(conversation)
        return "\n\n".join(section for section in sections if section.strip())

    def _fallback_branch_role(self, *, thread_values: dict, current_role: BranchRole) -> BranchRole:
        prompt_mode = getattr(thread_values.get("prompt_mode"), "value", thread_values.get("prompt_mode"))
        normalized_prompt_mode = str(prompt_mode or "").strip().lower()
        if normalized_prompt_mode == "execute":
            return BranchRole.EXECUTE
        if normalized_prompt_mode == "synthesize":
            return BranchRole.WRITEUP

        active_skill_ids = {str(item).strip().lower() for item in thread_values.get("active_skill_ids", []) if str(item).strip()}
        if active_skill_ids & self._EXECUTE_SKILL_IDS:
            return BranchRole.EXECUTE

        text_parts = [
            str(thread_values.get("task_brief") or "").strip(),
            str(thread_values.get("rolling_summary") or "").strip(),
        ]
        for message in thread_values.get("messages", [])[-6:]:
            content = self._message_content_to_text(getattr(message, "content", ""))
            if content:
                text_parts.append(content)
        lowered = "\n".join(part for part in text_parts if part).lower()

        for role in (
            BranchRole.WRITEUP,
            BranchRole.EXECUTE,
            BranchRole.VERIFY,
            BranchRole.DEEP_DIVE,
        ):
            if any(keyword in lowered for keyword in self._ROLE_KEYWORD_HINTS[role]):
                return role
        if current_role != BranchRole.MAIN:
            return current_role
        return BranchRole.EXPLORE_ALTERNATIVES

    def _classify_branch_role(self, *, thread_values: dict, current_role: BranchRole) -> BranchRole:
        context = self._collect_branch_role_context(thread_values=thread_values)
        model = getattr(self, "proposal_model", None)
        if model and context:
            try:
                options = ", ".join(role.value for role in self._ROLE_CLASSIFICATION_OPTIONS)
                response = model.invoke(
                    [
                        SystemMessage(
                            content=(
                                "Classify the branch by its dominant work mode after the first completed turn. "
                                f"Return exactly one role id from: {options}. "
                                "Use execute for implementation or direct changes, verify for checking or testing, "
                                "deep_dive for focused investigation, writeup for summarizing or documentation, "
                                "and explore_alternatives for open-ended branching or option discovery."
                            )
                        ),
                        HumanMessage(content=context),
                    ]
                )
                candidate = self._normalize_branch_role_candidate(
                    self._message_content_to_text(getattr(response, "content", response))
                )
                if candidate is not None:
                    return candidate
            except Exception:
                pass
        return self._fallback_branch_role(thread_values=thread_values, current_role=current_role)

    def _generate_branch_name(self, *, thread_values: dict, branch_role: BranchRole) -> str:
        seed_text = self._collect_branch_name_seed(thread_values=thread_values)
        language = self._detect_naming_language(seed_text)
        context = self._collect_branch_name_context(thread_values=thread_values, language=language)
        model = getattr(self, "proposal_model", None)
        if model and context:
            try:
                language_label = "Chinese" if language == "zh" else "English"
                response = model.invoke(
                    [
                        SystemMessage(
                            content=(
                                "Generate a concise branch name for a research assistant. "
                                f"Return only the name, 2 to 4 words, with no quotes or punctuation unless a hyphen is necessary. "
                                f"Use {language_label} to match the conversation language."
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
        return self._fallback_branch_name(seed_text or context, branch_role, language=language)

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
        language: str | None = None,
    ) -> str:
        if preferred_name and preferred_name.strip():
            return self._sanitize_branch_name(preferred_name, branch_role=branch_role)
        del parent_values, name_source
        if str(language or "").strip().lower() == "zh":
            return self._DEFAULT_PENDING_BRANCH_NAME_ZH
        return self._DEFAULT_PENDING_BRANCH_NAME

    def _generate_conversation_name(self, *, thread_values: dict) -> str:
        return self._generate_branch_name(thread_values=thread_values, branch_role=BranchRole.MAIN)

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

    def _derive_parent_branch_status(self, parent_thread_id: str, parent_state: dict) -> BranchStatus | None:
        try:
            record = self.repo.get_by_child_thread_id(parent_thread_id)
            return record.branch_status
        except Exception:
            pass
        meta = parent_state.get('branch_meta') or {}
        raw_status = meta.get('branch_status')
        if raw_status is not None:
            try:
                return BranchStatus(str(raw_status))
            except ValueError:
                pass
        return None

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

    def _ensure_parent_branch_can_fork(self, *, parent_thread_id: str, parent_values: dict) -> None:
        parent_status = self._derive_parent_branch_status(parent_thread_id, parent_values)
        if parent_status == BranchStatus.MERGED:
            raise ValueError("Merged branches cannot create new branches.")

    @staticmethod
    def _ensure_branch_not_merged(branch_record: BranchRecord) -> None:
        if branch_record.branch_status == BranchStatus.MERGED:
            raise ValueError("Merged branches are read-only.")

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
        language: str | None = None,
        branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES,
        fork_checkpoint_id: str | None = None,
    ) -> BranchRecord:
        return self._lifecycle_coordinator().fork_branch(
            parent_thread_id=parent_thread_id,
            user_id=user_id,
            branch_name=branch_name,
            name_source=name_source,
            language=language,
            branch_role=branch_role,
            fork_checkpoint_id=fork_checkpoint_id,
        )

    def refresh_branch_role(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        force: bool = False,
    ) -> BranchRecord | None:
        return self._lifecycle_coordinator().refresh_branch_role(
            child_thread_id=child_thread_id,
            user_id=user_id,
            force=force,
        )

    def refresh_branch_name(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        name_source: str | None = None,
        force: bool = False,
    ) -> BranchRecord | None:
        return self._lifecycle_coordinator().refresh_branch_name(
            child_thread_id=child_thread_id,
            user_id=user_id,
            name_source=name_source,
            force=force,
        )

    def refresh_branch_name_after_first_turn(
        self,
        *,
        child_thread_id: str,
        user_id: str,
    ) -> BranchRecord | None:
        return self.refresh_branch_metadata_after_first_turn(
            child_thread_id=child_thread_id,
            user_id=user_id,
        )

    def refresh_branch_metadata_after_first_turn(
        self,
        *,
        child_thread_id: str,
        user_id: str,
    ) -> BranchRecord | None:
        return self._lifecycle_coordinator().refresh_branch_metadata_after_first_turn(
            child_thread_id=child_thread_id,
            user_id=user_id,
        )

    def rename_branch(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        branch_name: str,
    ) -> BranchRecord:
        return self._lifecycle_coordinator().rename_branch(
            child_thread_id=child_thread_id,
            user_id=user_id,
            branch_name=branch_name,
        )

    def refresh_conversation_title_after_first_turn(
        self,
        *,
        root_thread_id: str,
        user_id: str,
    ) -> ConversationRecord | None:
        return self._lifecycle_coordinator().refresh_conversation_title_after_first_turn(
            root_thread_id=root_thread_id,
            user_id=user_id,
        )

    def _set_conversation_archive_state(
        self,
        *,
        root_thread_id: str,
        user_id: str,
        is_archived: bool,
    ) -> ConversationRecord:
        return self._lifecycle_coordinator().set_conversation_archive_state(
            root_thread_id=root_thread_id,
            user_id=user_id,
            is_archived=is_archived,
        )

    def archive_conversation(self, *, root_thread_id: str, user_id: str) -> ConversationRecord:
        return self._set_conversation_archive_state(
            root_thread_id=root_thread_id,
            user_id=user_id,
            is_archived=True,
        )

    def activate_conversation(self, *, root_thread_id: str, user_id: str) -> ConversationRecord:
        return self._set_conversation_archive_state(
            root_thread_id=root_thread_id,
            user_id=user_id,
            is_archived=False,
        )

    def prepare_merge_proposal(self, *, child_thread_id: str, user_id: str) -> MergeProposal:
        return self._merge_coordinator().prepare_merge_proposal(
            child_thread_id=child_thread_id,
            user_id=user_id,
        )

    def apply_merge_decision(
        self,
        *,
        child_thread_id: str,
        decision: MergeDecision,
        context: RequestContext,
        proposal_overrides: MergeProposalOverrides | None = None,
    ) -> ImportedConclusion | None:
        return self._merge_coordinator().apply_merge_decision(
            child_thread_id=child_thread_id,
            decision=decision,
            context=context,
            proposal_overrides=proposal_overrides,
        )

    def get_branch_tree(self, *, root_thread_id: str, user_id: str) -> BranchTreeNode:
        return self._tree_coordinator().get_branch_tree(root_thread_id=root_thread_id, user_id=user_id)

    def list_archived_branches(self, *, root_thread_id: str, user_id: str) -> list[BranchTreeNode]:
        return self._tree_coordinator().list_archived_branches(root_thread_id=root_thread_id, user_id=user_id)

    def _set_branch_archive_state(self, *, child_thread_id: str, user_id: str, is_archived: bool) -> BranchRecord:
        return self._tree_coordinator().set_branch_archive_state(
            child_thread_id=child_thread_id,
            user_id=user_id,
            is_archived=is_archived,
        )

    def archive_branch(self, *, child_thread_id: str, user_id: str) -> BranchRecord:
        return self._set_branch_archive_state(child_thread_id=child_thread_id, user_id=user_id, is_archived=True)

    def activate_branch(self, *, child_thread_id: str, user_id: str) -> BranchRecord:
        return self._set_branch_archive_state(child_thread_id=child_thread_id, user_id=user_id, is_archived=False)
