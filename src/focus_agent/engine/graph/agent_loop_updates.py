from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage


def finalize_agent_loop_turn(
    *,
    state: dict[str, Any],
    state_messages: list[Any],
    response: AIMessage,
    hooks: dict[str, Any],
    settings: Any,
    tool_intent_plan: Any,
    tool_route_plan: Any | None,
    tool_policy: str,
    tool_intent_text: str,
    available_tools: list[Any],
    known_names: list[str],
    execution_contract: dict[str, Any],
    prompt_messages: list[Any],
    fallback_messages: list[Any],
    context_budget: Any,
    selected_model: str,
    selected_thinking_mode: str,
    quarantined_model_for: Any,
    quarantined_model_with_tools_for: Any,
    current_utc_time_result: str,
    temporal_anchor_required: bool,
    temporal_anchor_forced: bool,
    forced_degraded_skill_recovery: bool,
    tool_protocol_repair_count: int,
    tool_protocol_repair_reason: str,
) -> dict[str, Any]:
    """Verify a completed model turn and persist its observable state updates.

    The caller supplies hooks resolved from ``agent_loop`` immediately before
    each invocation. This preserves existing test patch seams while keeping
    evidence repair and update construction separate from prompt orchestration.
    """

    latest_turn_messages = hooks["_latest_turn_messages"]
    degraded_answer_from_tool_results = hooks["_degraded_answer_from_tool_results"]
    message_content_text = hooks["_message_content_text"]
    fallback_answer_from_tool_results = hooks["_fallback_answer_from_tool_results"]
    should_replace_unfound_workspace_answer = hooks["_should_replace_unfound_workspace_answer"]
    latest_tool_result_content = hooks["_latest_tool_result_content"]
    normalize_evidence_bundle = hooks["normalize_evidence_bundle"]
    normalize_evidence_ledger = hooks["normalize_evidence_ledger"]
    skill_execution_evidence_facts = hooks["skill_execution_evidence_facts"]
    tool_result_names = hooks["tool_result_names"]
    evaluate_execution_contract = hooks["evaluate_execution_contract"]
    verify_answer_against_evidence = hooks["verify_answer_against_evidence"]
    live_web_answer_repair_count = hooks["_live_web_answer_repair_count"]
    skill_execution_answer_repair_count = hooks["_skill_execution_answer_repair_count"]
    live_web_answer_needs_repair = hooks["_live_web_answer_needs_repair"]
    apply_prompt_budget_guard = hooks["apply_prompt_budget_guard"]
    skill_execution_repair_prompt = hooks["_skill_execution_repair_prompt"]
    ensure_reasoning_content = hooks["_ensure_reasoning_content_for_tool_call_history"]
    invoke_with_tool_result_fallback = hooks["_invoke_with_tool_result_fallback"]
    with_stream_phase = hooks["_with_stream_phase"]
    stream_visibility_quarantine = hooks["STREAM_VISIBILITY_QUARANTINE"]
    looks_like_textual_tool_call_artifact = hooks["_looks_like_textual_tool_call_artifact"]
    repair_textual_tool_call_response = hooks["_repair_textual_tool_call_response"]
    repair_and_dedupe_tool_calls = hooks["_repair_and_dedupe_tool_calls"]
    skill_execution_failure_answer = hooks["_skill_execution_failure_answer"]
    live_web_repair_response = hooks["_live_web_repair_response"]
    live_web_failure_answer = hooks["_live_web_failure_answer"]
    evidence_bundle_to_citation_refs = hooks["evidence_bundle_to_citation_refs"]
    new_citation_refs = hooks["_new_citation_refs"]
    latest_turn_has_tool_result = hooks["_latest_turn_has_tool_result"]
    enforce_temporal_anchor = hooks["enforce_temporal_anchor"]
    repair_chinese_output = hooks["repair_chinese_output"]
    build_task_outcome = hooks["build_task_outcome"]
    with_focus_agent_turn_metadata = hooks["_with_focus_agent_turn_metadata"]
    next_pending_tool_action = hooks["_next_pending_tool_action"]
    append_agent_state_record = hooks["append_agent_state_record"]
    build_failure_records = hooks["build_failure_records"]
    build_review_queue = hooks["build_review_queue"]

    completed_turn_messages = latest_turn_messages([*state_messages, response])
    if not getattr(response, "tool_calls", None) and should_replace_unfound_workspace_answer(
        message_content_text(response),
        completed_turn_messages,
    ):
        response = AIMessage(content=fallback_answer_from_tool_results(completed_turn_messages))
        completed_turn_messages = latest_turn_messages([*state_messages, response])
        tool_protocol_repair_reason = tool_protocol_repair_reason or "workspace_evidence_fallback"
    observed_at = latest_tool_result_content(completed_turn_messages, "current_utc_time")
    evidence_bundle = normalize_evidence_bundle(
        completed_turn_messages,
        observed_at=observed_at or None,
        user_query=tool_intent_text,
    )
    evidence_ledger = normalize_evidence_ledger(
        completed_turn_messages,
        observed_at=observed_at or None,
        user_query=tool_intent_text,
    )
    skill_evidence_facts = skill_execution_evidence_facts(
        completed_turn_messages,
        required_tools=[
            str(item) for item in execution_contract.get("required_tools") or [] if str(item)
        ],
    )
    execution_contract = evaluate_execution_contract(
        execution_contract,
        tool_results_seen=tool_result_names(completed_turn_messages),
        evidence_ledger=evidence_ledger,
        available_tool_names=known_names,
        observed_at=observed_at or None,
        user_query=tool_intent_text,
        skill_evidence_facts=skill_evidence_facts,
    )
    answer_verification = verify_answer_against_evidence(
        answer=message_content_text(response) if not getattr(response, "tool_calls", None) else "",
        contract=execution_contract,
        evidence_ledger=evidence_ledger,
    )
    live_web_repair_count = live_web_answer_repair_count(state)
    live_web_repair_taken = ""
    skill_execution_repair_count = skill_execution_answer_repair_count(state)
    skill_execution_repair_taken = ""
    if (
        str(execution_contract.get("policy") or "") == "skill_execution"
        and not getattr(response, "tool_calls", None)
        and live_web_answer_needs_repair(answer_verification)
    ):
        if (
            forced_degraded_skill_recovery
            or str(answer_verification.get("repair_action") or "") == "fallback_to_tool_results"
        ):
            response = AIMessage(content=degraded_answer_from_tool_results(completed_turn_messages))
            completed_turn_messages = latest_turn_messages([*state_messages, response])
            answer_verification = verify_answer_against_evidence(
                answer=message_content_text(response),
                contract=execution_contract,
                evidence_ledger=evidence_ledger,
            )
            answer_verification = {
                **answer_verification,
                "repair_action_taken": "fallback_to_tool_results",
            }
            skill_execution_repair_taken = "fallback_to_tool_results"
        elif skill_execution_repair_count < 1 and available_tools:
            repair_prompt = apply_prompt_budget_guard(
                [
                    prompt_messages[0],
                    SystemMessage(
                        content=skill_execution_repair_prompt(
                            verification=answer_verification,
                            execution_contract=execution_contract,
                        )
                    ),
                    *prompt_messages[1:],
                ],
                budget=context_budget,
            )
            repair_prompt = ensure_reasoning_content(
                repair_prompt,
                model_id=selected_model,
                thinking_mode=selected_thinking_mode,
                settings=settings,
            )
            repair_response = invoke_with_tool_result_fallback(
                with_stream_phase(
                    hooks["model_with_tools_for"](
                        selected_model,
                        selected_thinking_mode,
                        available_tools,
                    ),
                    stream_visibility_quarantine,
                ),
                repair_prompt,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if looks_like_textual_tool_call_artifact(
                repair_response,
                known_tool_names=known_names,
            ):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = tool_protocol_repair_reason or "textual_tool_marker"
            repair_response = repair_textual_tool_call_response(
                response=repair_response,
                prompt_messages=repair_prompt,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                available_tools=available_tools,
                model_for=quarantined_model_for,
                model_with_tools_for=quarantined_model_with_tools_for,
            )
            repair_response = repair_and_dedupe_tool_calls(repair_response)
            if getattr(repair_response, "tool_calls", None):
                response = repair_response
                completed_turn_messages = latest_turn_messages([*state_messages, response])
                answer_verification = {
                    **answer_verification,
                    "repair_action_taken": "retry_skill_primary_tool",
                }
                skill_execution_repair_taken = "retry_skill_primary_tool"
        if not skill_execution_repair_taken:
            response = AIMessage(
                content=skill_execution_failure_answer(
                    verification=answer_verification,
                    execution_contract=execution_contract,
                )
            )
            completed_turn_messages = latest_turn_messages([*state_messages, response])
            answer_verification = {
                **answer_verification,
                "repair_action_taken": "answer_with_uncertainty",
            }
            skill_execution_repair_taken = "answer_with_uncertainty"
    if (
        tool_policy == "live_web_research"
        and not getattr(response, "tool_calls", None)
        and live_web_answer_needs_repair(answer_verification)
    ):
        if str(answer_verification.get("repair_action") or "") == "fallback_to_tool_results":
            response = AIMessage(content=fallback_answer_from_tool_results(completed_turn_messages))
            completed_turn_messages = latest_turn_messages([*state_messages, response])
            answer_verification = verify_answer_against_evidence(
                answer=message_content_text(response),
                contract=execution_contract,
                evidence_ledger=evidence_ledger,
            )
            answer_verification = {
                **answer_verification,
                "repair_action_taken": "fallback_to_tool_results",
            }
            live_web_repair_taken = "fallback_to_tool_results"
        else:
            repair_response = live_web_repair_response(
                state=state,
                available_tools=available_tools,
                tool_intent_plan=tool_intent_plan.model_dump(mode="json"),
                fallback_query=tool_intent_text,
                current_utc_time=observed_at or current_utc_time_result,
                repair_count=live_web_repair_count,
                verification=answer_verification,
                execution_contract=execution_contract,
            )
            if repair_response is not None:
                response = repair_response
                completed_turn_messages = latest_turn_messages([*state_messages, response])
                answer_verification = {
                    **answer_verification,
                    "repair_action_taken": "retry_web_search",
                }
                live_web_repair_taken = "retry_web_search"
            else:
                response = AIMessage(
                    content=live_web_failure_answer(
                        verification=answer_verification,
                        execution_contract=execution_contract,
                        evidence_ledger=evidence_ledger,
                    )
                )
                completed_turn_messages = latest_turn_messages([*state_messages, response])
                answer_verification = {
                    **answer_verification,
                    "repair_action_taken": "answer_with_uncertainty",
                }
                live_web_repair_taken = "answer_with_uncertainty"
    evidence_citation_refs = evidence_bundle_to_citation_refs(evidence_bundle)
    source_urls = tuple(
        str(item.get("uri") or "").strip()
        for item in evidence_citation_refs
        if str(item.get("uri") or "").strip()
    )
    language_repair_taken = False
    language_repair_attempts = 0
    if not getattr(response, "tool_calls", None):
        language_repair = repair_chinese_output(
            response=response,
            user_text=tool_intent_text,
            model=quarantined_model_for(selected_model, selected_thinking_mode),
            observed_at=observed_at,
            source_urls=source_urls,
        )
        if language_repair is not None:
            response = language_repair.response
            completed_turn_messages = latest_turn_messages([*state_messages, response])
            language_repair_taken = True
            language_repair_attempts = language_repair.attempts
    temporal_anchor_repair_taken = ""
    if not getattr(response, "tool_calls", None) and observed_at:
        temporal_anchor_repair = enforce_temporal_anchor(
            response=response,
            user_text=tool_intent_text,
            observed_at=observed_at,
            source_refs=tuple(
                (str(item.get("label") or ""), str(item.get("uri") or ""))
                for item in evidence_citation_refs
                if str(item.get("uri") or "").strip()
            ),
        )
        if temporal_anchor_repair is not None:
            response = temporal_anchor_repair.response
            completed_turn_messages = latest_turn_messages([*state_messages, response])
            temporal_anchor_repair_taken = temporal_anchor_repair.action
    citation_refs = new_citation_refs(
        evidence_citation_refs,
        existing=list(state.get("citations", []) or []),
    )
    web_tool_result_seen = latest_turn_has_tool_result(
        state_messages,
        "web_search",
    ) or latest_turn_has_tool_result(
        state_messages,
        "web_fetch",
    )
    external_answer_missing_citation = bool(
        tool_policy == "live_web_research"
        and web_tool_result_seen
        and not getattr(response, "tool_calls", None)
        and message_content_text(response)
        and not citation_refs
        and not state.get("citations")
    )
    current_tool_outcomes = list(state.get("tool_outcomes") or [])
    current_human_turn_index = sum(
        1 for message in state_messages if isinstance(message, HumanMessage)
    )
    current_turn_id = str(current_human_turn_index or 1)
    task_outcome = (
        None
        if getattr(response, "tool_calls", None)
        else build_task_outcome(
            user_goal=tool_intent_text,
            execution_contract=execution_contract,
            answer_verification=answer_verification,
            evidence_ledger=evidence_ledger,
            tool_outcomes=current_tool_outcomes,
            final_answer=message_content_text(response),
            repair_action_taken=(
                skill_execution_repair_taken
                or live_web_repair_taken
                or ("rewrite_chinese_output" if language_repair_taken else "")
                or temporal_anchor_repair_taken
            ),
            current_turn_id=current_turn_id,
            current_human_turn_index=current_human_turn_index or 1,
        )
    )
    updates: dict[str, Any] = {
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1 + language_repair_attempts,
        "evidence_bundle": evidence_bundle,
        "evidence_ledger": evidence_ledger,
        "execution_contract": execution_contract,
        "answer_verification": answer_verification,
    }
    if task_outcome is not None:
        updates["task_outcome"] = task_outcome
    if citation_refs:
        updates["citations"] = citation_refs
    intent_dumped = tool_intent_plan.model_dump(mode="json")
    if temporal_anchor_required:
        intent_dumped["temporal_anchor_required"] = True
    if temporal_anchor_forced:
        intent_dumped["temporal_anchor_forced"] = True
    if external_answer_missing_citation:
        intent_dumped["external_answer_missing_citation"] = True
    if live_web_repair_taken:
        intent_dumped["live_web_answer_repair_action_taken"] = live_web_repair_taken
        if live_web_repair_taken == "retry_web_search":
            intent_dumped["live_web_answer_repair_count"] = live_web_repair_count + 1
    if skill_execution_repair_taken:
        intent_dumped["skill_execution_repair_action_taken"] = skill_execution_repair_taken
        if skill_execution_repair_taken == "retry_skill_primary_tool":
            intent_dumped["skill_execution_answer_repair_count"] = skill_execution_repair_count + 1
    if language_repair_taken:
        intent_dumped["output_language_repair_action_taken"] = "rewrite_chinese_output"
        intent_dumped["output_language_repair_attempts"] = language_repair_attempts
    if temporal_anchor_repair_taken:
        intent_dumped["temporal_anchor_repair_action_taken"] = temporal_anchor_repair_taken
    turn_metadata: dict[str, Any] = {}
    if intent_dumped.get("skill_execution_plan"):
        turn_metadata["skill_execution_plan"] = intent_dumped["skill_execution_plan"]
        selected_skill_ids = intent_dumped["skill_execution_plan"].get("selected_skill_ids")
        if isinstance(selected_skill_ids, list):
            turn_metadata["selected_skill_ids"] = selected_skill_ids
            turn_metadata["active_skill_ids"] = selected_skill_ids
    if str(execution_contract.get("policy") or "") == "skill_execution":
        turn_metadata["execution_contract"] = execution_contract
    if task_outcome is not None:
        turn_metadata["task_outcome"] = task_outcome
    if skill_execution_repair_taken:
        turn_metadata["answer_verification"] = answer_verification
    if turn_metadata:
        response = with_focus_agent_turn_metadata(response, turn_metadata)
        updates["messages"] = [response]
    updates["pending_tool_action"] = next_pending_tool_action(
        state=state,
        tool_intent_plan=intent_dumped,
        response=response,
        web_tool_result_seen=web_tool_result_seen,
    )
    append_agent_state_record(
        updates,
        "tool_intent_plan",
        intent_dumped,
        source="agent_loop",
    )
    append_agent_state_record(
        updates,
        "execution_contract",
        execution_contract,
        source="agent_loop",
        domain="observability",
    )
    append_agent_state_record(
        updates,
        "answer_verification",
        answer_verification,
        source="agent_loop",
        domain="observability",
    )
    if task_outcome is not None:
        append_agent_state_record(
            updates,
            "task_outcome",
            task_outcome,
            source="agent_loop",
            domain="observability",
        )
    updates["plan_meta"] = {
        **(state.get("plan_meta") or {}),
        "tool_intent_plan": intent_dumped,
        "execution_contract": execution_contract,
        "evidence_ledger": evidence_ledger,
        "answer_verification": answer_verification,
        "tool_outcomes": current_tool_outcomes,
    }
    if task_outcome is not None:
        updates["plan_meta"]["task_outcome"] = task_outcome
    if live_web_repair_taken == "retry_web_search":
        updates["plan_meta"]["live_web_answer_repair_count"] = live_web_repair_count + 1
    if skill_execution_repair_taken == "retry_skill_primary_tool":
        updates["plan_meta"]["skill_execution_answer_repair_count"] = (
            skill_execution_repair_count + 1
        )
    if language_repair_taken:
        updates["plan_meta"]["output_language_repair_action_taken"] = "rewrite_chinese_output"
        updates["plan_meta"]["output_language_repair_attempts"] = language_repair_attempts
    if temporal_anchor_repair_taken:
        updates["plan_meta"]["temporal_anchor_repair_action_taken"] = temporal_anchor_repair_taken
    if tool_route_plan is not None:
        dumped = tool_route_plan.model_dump(mode="json")
        append_agent_state_record(
            updates,
            "tool_route_plan",
            dumped,
            source="agent_loop",
        )
        plan_meta = {
            **(updates.get("plan_meta") or state.get("plan_meta") or {}),
            "tool_route_plan": dumped,
        }
        if settings.agent_self_repair_enabled:
            failures = [
                item.model_dump(mode="json")
                for item in build_failure_records(
                    delegation_plan=state.get("agent_delegation_plan"),
                    tool_route_plan=dumped,
                    model_route_decision=state.get("model_route_decision"),
                )
            ]
            append_agent_state_record(
                updates,
                "agent_failure_records",
                failures,
                source="agent_loop",
            )
            plan_meta["agent_failure_records"] = failures
        if settings.agent_review_queue_enabled:
            review_items = [
                item.model_dump(mode="json")
                for item in build_review_queue(
                    settings=settings,
                    memory_curator_decision=state.get("memory_curator_decision"),
                    tool_route_plan=dumped,
                    model_route_decision=state.get("model_route_decision"),
                    agent_failure_records=updates.get("agent_failure_records")
                    or state.get("agent_failure_records")
                    or [],
                )
            ]
            append_agent_state_record(
                updates,
                "agent_review_queue",
                review_items,
                source="agent_loop",
            )
            plan_meta["agent_review_queue"] = review_items
        if updates.get("governance_records"):
            plan_meta["governance_records"] = [
                *list(plan_meta.get("governance_records") or []),
                *list(updates.get("governance_records") or []),
            ]
        updates["plan_meta"] = plan_meta
    if tool_protocol_repair_count:
        current_plan_meta = updates.get("plan_meta") or state.get("plan_meta") or {}
        updates["plan_meta"] = {
            **current_plan_meta,
            "tool_protocol_repair_count": int(
                current_plan_meta.get("tool_protocol_repair_count", 0)
            )
            + tool_protocol_repair_count,
            "tool_protocol_repair_reason": tool_protocol_repair_reason,
        }
    return updates
