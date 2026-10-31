from __future__ import annotations

import logging
import uuid
from copy import deepcopy

from ...core.branch_brief import build_fork_brief, pending_fork_handoff_goal
from ...core.branch_messages import (
    _is_tool_message_type,
    _message_type_name,
    branch_seed_messages,
    branch_visible_messages,
)
from ...core.branching import BranchMeta, BranchRecord, BranchRole, BranchStatus
from ...core.merge_review_inputs import fork_inherited_counts_for
from ...core.types import ConversationRecord, PromptMode

logger = logging.getLogger("focus_agent.branches")

_LOCAL_SNAPSHOT_SEED_RESETS: dict[str, object] = {
    "rolling_summary": "",
    "recent_messages": [],
    "assembled_context": "",
    "llm_calls": 0,
    "branch_meta": None,
    "branch_actions": [],
    "branch_action_audit": [],
    "branch_local_findings": [],
    "merge_proposal": None,
    "merge_decision": None,
    "prompt_mode": PromptMode.EXPLORE,
    "retrieved_memories": [],
    "memory_prompt_block": "",
    "memory_retrieval_plan": {},
    "active_skill_ids": [],
    "available_skills_block": "",
    "active_skills_block": "",
    "selected_model": "",
    "selected_thinking_mode": "",
    "role_route_plan": None,
    "governance_records": [],
    "memory_curator_decision": None,
    "tool_intent_plan": None,
    "tool_route_plan": None,
    "pending_tool_action": None,
    "evidence_bundle": [],
    "evidence_ledger": [],
    "execution_contract": None,
    "answer_verification": None,
    "agent_delegation_plan": None,
    "agent_runs": [],
    "model_route_decision": None,
    "agent_failure_records": [],
    "agent_review_queue": [],
    "context_budget_decision": None,
    "context_compression_plan": None,
    "context_artifact_refs": [],
    "role_context_views": [],
    "context_compaction": {},
    "agent_task_ledger": None,
    "delegated_artifacts": [],
    "artifact_synthesis_result": None,
    "critic_gate_result": None,
    "memory_write_requests": [],
    "memory_write_result": {},
    "plan": None,
    "current_step_id": "",
    "reflection": None,
    "plan_meta": {},
}


def _local_snapshot_seed_values(parent_values: dict) -> dict:
    seed_values = deepcopy(parent_values)
    seed_values["messages"] = branch_seed_messages(
        list(parent_values.get("messages") or []),
        values=parent_values,
    )
    seed_values.update(deepcopy(_LOCAL_SNAPSHOT_SEED_RESETS))
    return seed_values


def _message_id(message: object) -> str:
    if isinstance(message, dict):
        value = message.get("id")
    else:
        value = getattr(message, "id", None)
    return str(value or "").strip()


def _summary_written_after(values: dict, later_messages: list) -> bool:
    """Whether the parent's summary already covers messages after the cut.

    Each summarize pass stamps ``context_compaction.source_message_tail_id`` with
    the last message it saw. When that id belongs to a dropped message the
    summary describes later turns. Without a recognisable stamp (legacy rolling
    summaries, id-less messages) there is no reliable way to tell, so the summary
    is kept: it is only background in the fork brief, never transcript.
    """
    compaction = values.get("context_compaction")
    if not isinstance(compaction, dict):
        return False
    tail_id = str(compaction.get("source_message_tail_id") or "").strip()
    return bool(tail_id) and tail_id in {_message_id(message) for message in later_messages}


def _parent_values_at_message(parent_values: dict, message_id: str) -> dict:
    """Parent state as seen right after ``message_id``, minus later-turn state.

    Raises ``ValueError`` when the id is not one of the parent's visible messages.
    """
    messages = list(parent_values.get("messages") or [])
    visible_ids = {
        _message_id(message) for message in branch_visible_messages(messages, values=parent_values)
    }
    if not message_id or message_id not in visible_ids:
        raise ValueError(f"Message {message_id!r} is not a visible message of the parent thread.")
    cut = next(index for index, item in enumerate(messages) if _message_id(item) == message_id) + 1
    # Keep tool results that answer the cut message so the seed never ends on
    # an unanswered tool call.
    while cut < len(messages) and _is_tool_message_type(_message_type_name(messages[cut])):
        cut += 1
    later_messages = messages[cut:]
    if not later_messages:
        return parent_values

    cut_values = dict(parent_values)
    cut_values["messages"] = messages[:cut]
    # Pending branch proposals and the task outcome belong to the latest turn,
    # which is after the cut. Resolved actions stay: they only filter copied
    # branch-control chatter out of the seed.
    cut_values["branch_actions"] = [
        item
        for item in list(parent_values.get("branch_actions") or [])
        if not (isinstance(item, dict) and str(item.get("status") or "") == "pending")
    ]
    cut_values["task_outcome"] = None
    # Tool outcomes are keyed by tool call; drop those whose ToolMessage was cut.
    later_tool_call_ids = {
        str(getattr(item, "tool_call_id", "") or "")
        for item in later_messages
        if _is_tool_message_type(_message_type_name(item))
    } - {""}
    cut_values["tool_outcomes"] = [
        item
        for item in list(parent_values.get("tool_outcomes") or [])
        if not (isinstance(item, dict) and item.get("tool_call_id") in later_tool_call_ids)
    ]
    if _summary_written_after(parent_values, later_messages):
        cut_values["rolling_summary"] = ""
        cut_values["context_compaction"] = {}
    return cut_values


def _ancestor_branch_ids(parent_values: dict) -> list[str]:
    """Branch ids whose unreviewed memory this child may see (its lineage)."""
    parent_meta = parent_values.get("branch_meta")
    if not isinstance(parent_meta, dict) or not parent_meta.get("branch_id"):
        return []
    ancestors = [str(item) for item in parent_meta.get("ancestor_branch_ids") or [] if item]
    return [*ancestors, str(parent_meta["branch_id"])]


class BranchLifecycleCoordinator:
    """Owns branch lifecycle operations behind the BranchService facade."""

    def __init__(self, service):
        self.service = service

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
        fork_at_message_id: str | None = None,
    ) -> BranchRecord:
        svc = self.service
        svc._ensure_parent_thread_access(parent_thread_id=parent_thread_id, user_id=user_id)
        parent_config = {"configurable": {"thread_id": parent_thread_id}}
        parent_snapshot = svc.graph.get_state(parent_config)
        parent_values = deepcopy(parent_snapshot.values)
        svc._ensure_parent_branch_can_fork(
            parent_thread_id=parent_thread_id,
            parent_values=parent_values,
        )
        if fork_at_message_id is not None:
            # The child must not see parent turns after the chosen message, so
            # everything below (seed, brief, inherited counts) uses the cut view.
            parent_values = _parent_values_at_message(parent_values, fork_at_message_id)
        root_thread_id = svc._derive_root_thread_id(parent_thread_id, parent_values)
        next_branch_depth = svc._ensure_branch_depth_allowed(
            parent_thread_id=parent_thread_id,
            parent_values=parent_values,
        )
        resolved_branch_name = svc._resolve_initial_branch_name(
            preferred_name=branch_name,
            parent_values=parent_values,
            name_source=name_source,
            branch_role=branch_role,
            language=language,
        )
        branch_id = str(uuid.uuid4())

        if svc.thread_client and fork_checkpoint_id is None and fork_at_message_id is None:
            copied = svc.thread_client.threads.copy(parent_thread_id)
            child_thread_id = copied["thread_id"]
            fork_strategy = "copy_thread"
        else:
            child_thread_id = str(uuid.uuid4())
            fork_strategy = "local_snapshot_seed"

        seed_values = (
            _local_snapshot_seed_values(parent_values)
            if fork_strategy == "local_snapshot_seed"
            else parent_values
        )
        seed_message_count = len(list(seed_values.get("messages") or []))

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
            fork_at_message_id=fork_at_message_id,
        )
        branch_meta_payload = branch_meta.model_dump(mode="json")
        branch_meta_payload["branch_name_pending_ai"] = branch_name is None
        branch_meta_payload["branch_role_pending_ai"] = (
            branch_role == BranchRole.EXPLORE_ALTERNATIVES
        )
        branch_meta_payload["branch_fork_message_count"] = seed_message_count
        fork_brief = build_fork_brief(
            parent_values,
            goal=pending_fork_handoff_goal(parent_values, parent_thread_id=parent_thread_id),
        )
        branch_meta_payload["fork_brief"] = fork_brief
        branch_meta_payload["fork_inherited_counts"] = fork_inherited_counts_for(seed_values)
        branch_meta_payload["ancestor_branch_ids"] = _ancestor_branch_ids(parent_values)
        if name_source is not None:
            branch_meta_payload["branch_name_source"] = name_source

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
        with svc._thread_write_lease(thread_id=child_thread_id):
            if fork_strategy == "local_snapshot_seed":
                svc.graph.update_state(
                    {"configurable": {"thread_id": child_thread_id}},
                    seed_values,
                    as_node="bootstrap_turn",
                )

            svc.graph.update_state(
                {"configurable": {"thread_id": child_thread_id}},
                {
                    "branch_meta": branch_meta_payload,
                    "active_goal": fork_brief["goal"],
                    "rolling_summary": "",
                    "context_compaction": {},
                    "evidence_ledger": [],
                    "merge_proposal": None,
                    "merge_decision": None,
                    "branch_local_findings": [],
                },
                as_node="bootstrap_turn",
            )
            svc.repo.ensure_thread_owner(
                thread_id=child_thread_id,
                root_thread_id=root_thread_id,
                owner_user_id=user_id,
            )
            svc.repo.create(record)
        return record

    def refresh_branch_role(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        force: bool = False,
    ) -> BranchRecord | None:
        svc = self.service
        branch_record = svc._require_child_branch_record(
            child_thread_id=child_thread_id,
            user_id=user_id,
            operation="Refreshing branch role",
        )
        child_config = {"configurable": {"thread_id": child_thread_id}}
        child_snapshot = svc.graph.get_state(child_config)
        child_values = deepcopy(child_snapshot.values)
        existing_meta = dict(child_values.get("branch_meta") or {})
        if not force and not existing_meta.get("branch_role_pending_ai"):
            return branch_record

        next_role = svc._classify_branch_role(
            thread_values=child_values,
            current_role=branch_record.branch_role,
        )
        if next_role == branch_record.branch_role:
            return branch_record

        svc.repo.update_branch_role(branch_record.branch_id, next_role)
        updated_record = branch_record.model_copy(update={"branch_role": next_role})
        svc.graph.update_state(
            child_config,
            {"branch_meta": svc._branch_meta_payload_from_record(updated_record, existing_meta)},
            as_node="bootstrap_turn",
        )
        return updated_record

    def refresh_branch_name(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        name_source: str | None = None,
        force: bool = False,
    ) -> BranchRecord | None:
        svc = self.service
        branch_record = svc._require_child_branch_record(
            child_thread_id=child_thread_id,
            user_id=user_id,
            operation="Refreshing branch name",
        )
        if not force and not branch_record.branch_name.strip():
            force = True
        if svc.proposal_model is None and not force:
            return branch_record

        child_config = {"configurable": {"thread_id": child_thread_id}}
        child_snapshot = svc.graph.get_state(child_config)
        child_values = deepcopy(child_snapshot.values)
        existing_meta = dict(child_values.get("branch_meta") or {})
        resolved_name_source = (
            name_source if name_source is not None else existing_meta.get("branch_name_source")
        )
        generated_name = svc._generate_branch_name(
            thread_values=child_values,
            branch_role=branch_record.branch_role,
            name_source=resolved_name_source,
        )
        next_name = svc._sanitize_branch_name(generated_name, branch_role=branch_record.branch_role)
        if not next_name or next_name == branch_record.branch_name:
            return branch_record

        svc.repo.update_branch_name(branch_record.branch_id, next_name)
        existing_meta = child_values.get("branch_meta") or {}
        updated_record = branch_record.model_copy(update={"branch_name": next_name})
        svc.graph.update_state(
            child_config,
            {"branch_meta": svc._branch_meta_payload_from_record(updated_record, existing_meta)},
            as_node="bootstrap_turn",
        )
        return updated_record

    def refresh_branch_metadata_after_first_turn(
        self,
        *,
        child_thread_id: str,
        user_id: str,
    ) -> BranchRecord | None:
        svc = self.service
        try:
            svc._require_child_branch_record(
                child_thread_id=child_thread_id,
                user_id=user_id,
                operation="Refreshing branch metadata",
            )
            child_config = {"configurable": {"thread_id": child_thread_id}}
            child_snapshot = svc.graph.get_state(child_config)
            child_values = deepcopy(child_snapshot.values)
            existing_meta = dict(child_values.get("branch_meta") or {})
            pending_name = bool(existing_meta.get("branch_name_pending_ai"))
            pending_role = bool(existing_meta.get("branch_role_pending_ai"))
            if not pending_name and not pending_role:
                return None

            updated_record = svc._require_child_branch_record(
                child_thread_id=child_thread_id,
                user_id=user_id,
                operation="Refreshing branch metadata",
            )
            if pending_role:
                refreshed_role_record = self.refresh_branch_role(
                    child_thread_id=child_thread_id,
                    user_id=user_id,
                    force=True,
                )
                if refreshed_role_record is not None:
                    updated_record = refreshed_role_record
            if pending_name:
                refreshed_name_record = self.refresh_branch_name(
                    child_thread_id=child_thread_id,
                    user_id=user_id,
                    name_source=None,
                    force=True,
                )
                if refreshed_name_record is not None:
                    updated_record = refreshed_name_record

            refreshed_snapshot = svc.graph.get_state(child_config)
            refreshed_values = deepcopy(refreshed_snapshot.values)
            refreshed_meta = dict(refreshed_values.get("branch_meta") or {})
            refreshed_meta["branch_name_pending_ai"] = False
            refreshed_meta["branch_role_pending_ai"] = False
            svc.graph.update_state(
                child_config,
                {"branch_meta": refreshed_meta},
                as_node="bootstrap_turn",
            )
            return updated_record
        except (KeyError, PermissionError):
            raise
        except Exception:  # noqa: BLE001 - first-turn metadata refresh is best-effort
            logger.warning(
                "failed to refresh branch metadata after first turn",
                extra={"child_thread_id": child_thread_id},
                exc_info=True,
            )
            return None

    def rename_branch(
        self,
        *,
        child_thread_id: str,
        user_id: str,
        branch_name: str,
    ) -> BranchRecord:
        svc = self.service
        branch_record = svc._require_child_branch_record(
            child_thread_id=child_thread_id,
            user_id=user_id,
            operation="Renaming a branch",
        )
        next_name = svc._sanitize_branch_name(branch_name, branch_role=branch_record.branch_role)
        svc.repo.update_branch_name(branch_record.branch_id, next_name)
        child_config = {"configurable": {"thread_id": child_thread_id}}
        snapshot = svc.graph.get_state(child_config)
        values = deepcopy(snapshot.values)
        updated_record = branch_record.model_copy(update={"branch_name": next_name})
        updated_meta = svc._branch_meta_payload_from_record(
            updated_record,
            existing_meta=dict(values.get("branch_meta") or {}),
        )
        updated_meta["branch_name_pending_ai"] = False
        svc.graph.update_state(
            child_config,
            {"branch_meta": updated_meta},
            as_node="bootstrap_turn",
        )
        return updated_record

    def refresh_conversation_title_after_first_turn(
        self,
        *,
        root_thread_id: str,
        user_id: str,
    ) -> ConversationRecord | None:
        svc = self.service
        try:
            svc.repo.assert_thread_owner(thread_id=root_thread_id, owner_user_id=user_id)
            record = svc.repo.get_conversation(root_thread_id)
            if not record.title_pending_ai:
                return None
            snapshot = svc.graph.get_state({"configurable": {"thread_id": root_thread_id}})
            values = deepcopy(getattr(snapshot, "values", {}) or {})
            generated_name = svc._generate_conversation_name(thread_values=values)
            next_title = svc._sanitize_branch_name(generated_name, branch_role=BranchRole.MAIN)
            return svc.repo.update_conversation_title(
                root_thread_id=root_thread_id,
                owner_user_id=user_id,
                title=next_title,
                title_pending_ai=False,
            )
        except (KeyError, PermissionError):
            raise
        except Exception:  # noqa: BLE001 - first-turn title refresh is best-effort
            logger.warning(
                "failed to refresh conversation title after first turn",
                extra={"root_thread_id": root_thread_id},
                exc_info=True,
            )
            return None

    def set_conversation_archive_state(
        self,
        *,
        root_thread_id: str,
        user_id: str,
        is_archived: bool,
    ) -> ConversationRecord:
        svc = self.service
        svc.repo.assert_thread_owner(thread_id=root_thread_id, owner_user_id=user_id)
        return svc.repo.update_conversation_archive_state(
            root_thread_id=root_thread_id,
            owner_user_id=user_id,
            is_archived=is_archived,
        )


__all__ = ["BranchLifecycleCoordinator"]
