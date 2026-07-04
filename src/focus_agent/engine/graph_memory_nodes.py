from __future__ import annotations

from copy import deepcopy
from typing import Any

from langchain.messages import AIMessage
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from ..agent_context_engineering import build_context_engineering_decision
from ..config import Settings
from ..core.branch_messages import branch_visible_messages
from ..core.context_policy import assemble_context as build_context_slice
from ..core.request_context import RequestContext
from ..core.state import AgentState
from ..core.types import PromptMode
from ..memory import (
    MemoryExtractor,
    MemoryRetriever,
    MemoryWriter,
    MemoryWriteRequest,
    render_memory_block,
)
from ..skills import SkillRegistry
from .graph_turn_helpers import (
    _context_budget_from_state,
    _latest_final_ai_text,
    _latest_human_message_text,
)


def _resolve_prompt_mode(state: AgentState) -> PromptMode:
    stored = state.get("prompt_mode")
    if isinstance(stored, PromptMode):
        return stored
    if isinstance(stored, str):
        try:
            return PromptMode(stored)
        except ValueError:
            pass
    if state.get("merge_proposal") and not state.get("merge_decision"):
        return PromptMode.BRANCH_REVIEW
    return PromptMode.EXPLORE


def make_retrieve_memory_node(
    memory_retriever: MemoryRetriever,
) -> Any:
    def retrieve_memory(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        latest_user = _latest_human_message_text(state.get("messages", []))
        prompt_mode = _resolve_prompt_mode(state)
        bundle = memory_retriever.retrieve_for_turn(
            context=runtime.context,
            state=dict(state),
            query=latest_user,
            prompt_mode=prompt_mode,
        )
        return {
            "retrieved_memories": [
                {
                    **hit.record.model_dump(mode="json"),
                    "score": hit.score,
                    "matched_terms": hit.matched_terms,
                }
                for hit in bundle.hits
            ],
            "memory_prompt_block": render_memory_block(bundle),
            "memory_retrieval_plan": bundle.retrieval_plan,
            "prompt_mode": prompt_mode,
        }

    return retrieve_memory


def make_assemble_context_node(
    *,
    settings: Settings,
    skill_registry: SkillRegistry,
) -> Any:
    def assemble_context(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        latest_user = _latest_human_message_text(state.get("messages", []))
        prompt_mode = _resolve_prompt_mode(state)
        active_skill_ids = tuple(
            runtime.context.skill_hints
            or tuple(str(item) for item in state.get("active_skill_ids", []) or ())
        )
        active_skills_block = skill_registry.render_active_skills_block(active_skill_ids)
        available_skills_block = skill_registry.render_available_skills_block()
        prompt_state = {
            **dict(state),
            "messages": branch_visible_messages(
                list(state.get("messages", []) or []),
                values=state,
            ),
        }
        context_slice = build_context_slice(
            {
                **prompt_state,
                "pinned_items": deepcopy(state.get("pinned_items", [])),
                "merge_queue": deepcopy(state.get("merge_queue", [])),
                "_memory_lines": [
                    item.get("summary") or item.get("content") or str(item)
                    for item in state.get("retrieved_memories", [])
                ],
                "_scene": runtime.context.scene,
                "_active_skills_block": active_skills_block,
                "_available_skills_block": available_skills_block,
            },
            prompt_mode,
        )
        task_brief = state.get("task_brief")
        if not task_brief and latest_user:
            task_brief = latest_user[:300]
        assembled_context = context_slice.render_prompt()
        # Splice in any extra blocks produced by the ContextPipeline augment
        # node (e.g. from custom stages added via create_default_pipeline).
        pipeline_extra = list(state.get("context_extra_blocks") or [])
        if pipeline_extra:
            extra_text = "\n\n".join(block.strip() for block in pipeline_extra if block)
            if extra_text:
                assembled_context = f"{assembled_context}\n\n{extra_text}".strip()
        updates: dict[str, Any] = {
            "recent_messages": context_slice.recent_messages,
            "assembled_context": assembled_context,
            "task_brief": task_brief or state.get("task_brief", ""),
            "prompt_mode": prompt_mode,
            "active_skill_ids": list(active_skill_ids),
            "active_skills_block": active_skills_block,
            "available_skills_block": available_skills_block,
            # Reset per-turn pipeline extras so they don't accumulate across turns.
            "context_extra_blocks": [],
        }
        if settings.agent_context_engineering_v2_enabled:
            decision = build_context_engineering_decision(
                settings=settings,
                state={
                    **dict(state),
                    "recent_messages": context_slice.recent_messages,
                    "context_budget": _context_budget_from_state(state),
                },
                prompt_mode=prompt_mode,
                assembled_context=assembled_context,
                role="executor",
                artifact_dir=settings.artifact_dir,
            ).model_dump(mode="json")
            compressed_prompt = decision.pop("compressed_prompt", None)
            if compressed_prompt:
                updates["assembled_context"] = str(compressed_prompt)
            updates["context_budget_decision"] = decision.get("budget")
            updates["context_compression_plan"] = decision.get("compression_plan")
            updates["context_artifact_refs"] = list(decision.get("artifact_refs") or [])
            updates["role_context_views"] = list(decision.get("role_context_views") or [])
            updates["plan_meta"] = {
                **(state.get("plan_meta") or {}),
                "context_budget_decision": updates["context_budget_decision"],
                "context_compression_plan": updates["context_compression_plan"],
                "context_artifact_refs": updates["context_artifact_refs"],
                "role_context_views": updates["role_context_views"],
            }
        return updates

    return assemble_context


def summarize_turn(state: AgentState) -> dict[str, Any]:
    last_user = _latest_human_message_text(state.get("messages", []))
    last_ai = _latest_final_ai_text(state.get("messages", []))
    previous_summary = state.get("rolling_summary", "")
    candidate_lines = [
        line for line in [previous_summary, f"User: {last_user}", f"Assistant: {last_ai}"] if line
    ]
    joined = "\n".join(candidate_lines)
    if len(joined) > 4000:
        joined = joined[-4000:]
    return {"rolling_summary": joined}


def _should_extract_memories(state: AgentState) -> bool:
    verification = state.get("answer_verification") or (state.get("plan_meta") or {}).get(
        "answer_verification"
    )
    if isinstance(verification, dict):
        status = str(verification.get("status") or "").strip()
        if status in {"unsupported", "contradicted", "blocked"}:
            return False
    reflection = state.get("reflection")
    reflection_status = getattr(reflection, "status", None) or (
        reflection.get("status") if isinstance(reflection, dict) else None
    )
    if reflection_status == "replan":
        return False
    messages = list(state.get("messages", []) or [])
    if not messages:
        return False
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        return False
    return bool(_latest_final_ai_text(messages))


def make_extract_memories_node(
    memory_extractor: MemoryExtractor,
) -> Any:
    def extract_memories(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        if not _should_extract_memories(state):
            verification = state.get("answer_verification") or (state.get("plan_meta") or {}).get(
                "answer_verification"
            )
            skipped = []
            if isinstance(verification, dict) and str(verification.get("status") or "") in {
                "unsupported",
                "contradicted",
                "blocked",
            }:
                skipped.append(
                    {
                        "reason": "answer_verification_failed",
                        "status": str(verification.get("status") or ""),
                    }
                )
            return {
                "memory_write_requests": [],
                "memory_write_result": {
                    "prepared": 0,
                    "written": [],
                    "merged": [],
                    "skipped": skipped,
                    "failed": [],
                },
            }
        extraction = memory_extractor.extract_from_turn(context=runtime.context, state=dict(state))
        return {
            "memory_write_requests": [
                record.model_dump(mode="json") for record in extraction.records
            ],
            "memory_write_result": {
                "prepared": len(extraction.records),
                "written": [],
                "merged": [],
                "skipped": list(extraction.skipped_reasons),
                "failed": [],
                "summary": extraction.summary,
            },
        }

    return extract_memories


def make_write_memories_node(
    memory_writer: MemoryWriter,
) -> Any:
    def write_memories(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        raw_requests = list(state.get("memory_write_requests", []) or [])
        if not raw_requests:
            return {
                "memory_write_requests": [],
                "memory_write_result": state.get("memory_write_result", {}),
            }
        records = [MemoryWriteRequest.model_validate(item) for item in raw_requests]
        outcome = memory_writer.persist_records(
            records,
            context=runtime.context,
            state=dict(state),
        )
        return {
            "memory_write_requests": [],
            "memory_write_result": outcome,
        }

    return write_memories


def maybe_interrupt_for_merge(state: AgentState) -> dict[str, Any]:
    if state.get("merge_proposal") and not state.get("merge_decision"):
        decision = interrupt(
            {
                "kind": "merge_review",
                "proposal": state["merge_proposal"],
                "message": (
                    "Review the branch proposal and choose whether to import it into "
                    "the parent thread."
                ),
            }
        )
        return {"merge_decision": decision}
    return {}


__all__ = [
    "_resolve_prompt_mode",
    "_should_extract_memories",
    "make_assemble_context_node",
    "make_extract_memories_node",
    "make_retrieve_memory_node",
    "make_write_memories_node",
    "maybe_interrupt_for_merge",
    "summarize_turn",
]
