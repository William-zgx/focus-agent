from __future__ import annotations

import logging
import re

from langchain.messages import HumanMessage, SystemMessage

from ..core.branching import BranchRole


logger = logging.getLogger("focus_agent.branches")


class BranchNamingPolicyMixin:
    """Branch name generation and role inference helpers."""

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
    def _thread_values_after_branch_fork(thread_values: dict) -> dict:
        branch_meta = thread_values.get("branch_meta")
        if not isinstance(branch_meta, dict):
            return thread_values
        try:
            fork_message_count = int(branch_meta.get("branch_fork_message_count"))
        except (TypeError, ValueError):
            return thread_values
        messages = list(thread_values.get("messages") or [])
        if fork_message_count <= 0:
            return thread_values
        values = dict(thread_values)
        values["messages"] = messages[min(fork_message_count, len(messages)) :]
        return values

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
        thread_values = self._thread_values_after_branch_fork(thread_values)
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
        thread_values = self._thread_values_after_branch_fork(thread_values)
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
        thread_values = self._thread_values_after_branch_fork(thread_values)
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
            except Exception:  # noqa: BLE001 - helper model failures fall back to deterministic role inference
                logger.warning("failed to classify branch role with helper model", exc_info=True)
        return self._fallback_branch_role(thread_values=thread_values, current_role=current_role)

    def _generate_branch_name(
        self,
        *,
        thread_values: dict,
        branch_role: BranchRole,
        name_source: str | None = None,
        language: str | None = None,
    ) -> str:
        seed_text = self._collect_branch_name_seed(thread_values=thread_values, name_source=name_source)
        language_code = str(language or "").strip().lower()
        language = language_code if language_code in {"en", "zh"} else self._detect_naming_language(seed_text)
        context = self._collect_branch_name_context(
            thread_values=thread_values,
            name_source=name_source,
            language=language,
        )
        model = getattr(self, "proposal_model", None)
        if model and context:
            try:
                language_label = "Chinese" if language == "zh" else "English"
                response = model.invoke(
                    [
                        SystemMessage(
                            content=(
                                "Generate a concise branch name for a research assistant. "
                                "Return only the name, 2 to 4 words, with no quotes or punctuation unless a hyphen is necessary. "
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
            except Exception:  # noqa: BLE001 - helper model failures fall back to deterministic naming
                logger.warning("failed to generate branch name with helper model", exc_info=True)
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
        del parent_values, name_source, branch_role
        if str(language or "").strip().lower() == "zh":
            return self._DEFAULT_PENDING_BRANCH_NAME_ZH
        return self._DEFAULT_PENDING_BRANCH_NAME

    def _generate_conversation_name(self, *, thread_values: dict) -> str:
        return self._generate_branch_name(thread_values=thread_values, branch_role=BranchRole.MAIN)
