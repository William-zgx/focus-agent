from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Literal

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from ..capabilities import ToolRegistry, build_tool_registry
from ..config import Settings
from ..core.context_policy import assemble_context as build_context_slice
from ..core.request_context import RequestContext
from ..core.state import AgentState
from ..core.types import Plan, PlanStep, PromptMode, ReflectionVerdict
from ..memory import MemoryRetriever, render_memory_block
from ..model_registry import create_chat_model
from ..skills import SkillRegistry
from ..storage.namespaces import conversation_namespace_for_context

_MAX_CONSECUTIVE_TOOL_CALL_ROUNDS = 2
_TOOL_EXHAUSTION_NOTE = (
    "You have enough tool results for this turn. Do not call more tools. "
    "Answer the user directly using the information already gathered, and state any uncertainty plainly."
)
_TOOL_CALL_PROTOCOL_REPAIR_NOTE = (
    "If you need a tool, emit a real tool call through the tool-calling interface. "
    "Do not write DSML tags, XML, or function-call payloads into the assistant text. "
    "If no tool is needed, answer directly in natural language."
)
_TOOL_CALL_MARKUP_REPAIR_NOTE = (
    "Do not emit tool-call markup, XML, JSON function-call payloads, or DSML tags. "
    "Write only the final user-facing answer in natural language."
)
_TOOL_CALL_LAST_RESORT_NOTE = (
    "The previous draft still contained internal tool-call markup. "
    "Do not call more tools. Using only the information already gathered in this conversation, "
    "write a concise final answer for the user in natural language."
)
_TOOL_CALL_REPAIR_FALLBACK_TEXT = (
    "I gathered the tool results for this turn, but formatting the final answer failed. "
    "Please retry this message or switch to a more stable model."
)


def _has_tool_calls(message: Any) -> bool:
    return bool(getattr(message, "tool_calls", None))


def _find_trailing_tool_span_start(messages: list[Any]) -> int | None:
    if not messages:
        return None

    index = len(messages) - 1
    while index >= 0 and isinstance(messages[index], ToolMessage):
        index -= 1

    if index < 0:
        return None
    if _has_tool_calls(messages[index]):
        return index
    return None


def _messages_for_model(state: AgentState) -> list[Any]:
    recent_messages = list(state.get("recent_messages") or [])
    messages = list(state.get("messages", []) or [])
    trailing_tool_span_start = _find_trailing_tool_span_start(messages)
    if trailing_tool_span_start is None:
        return recent_messages or messages
    return [*recent_messages, *messages[trailing_tool_span_start:]]


def _count_tool_call_rounds_since_latest_human(messages: list[Any]) -> int:
    rounds = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            rounds += 1
    return rounds


def _should_force_tool_free_answer(messages: list[Any]) -> bool:
    if not messages or not isinstance(messages[-1], ToolMessage):
        return False
    return _count_tool_call_rounds_since_latest_human(messages) >= _MAX_CONSECUTIVE_TOOL_CALL_ROUNDS


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _looks_like_textual_tool_call_artifact(message: Any) -> bool:
    text = _message_text(message).lower()
    if not text:
        return False
    markers = (
        "function_calls",
        "invoke name=",
        "<｜dsml｜",
        "<tool_call",
        '"tool_name"',
    )
    return any(marker in text for marker in markers)


def _latest_human_message_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def _latest_final_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            return _message_text(message)
    return ""


def _repair_textual_tool_call_response(
    *,
    response: Any,
    prompt_messages: list[Any],
    selected_model: str,
    selected_thinking_mode: str,
    model_for,
    model_with_tools_for,
) -> Any:
    if not _looks_like_textual_tool_call_artifact(response):
        return response

    repaired = model_with_tools_for(selected_model, selected_thinking_mode).invoke(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_CALL_PROTOCOL_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(response)),
        ]
    )
    if not _looks_like_textual_tool_call_artifact(repaired):
        return repaired

    return model_for(selected_model, selected_thinking_mode).invoke(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(repaired)),
        ]
    )


def _repair_tool_free_answer_response(
    *,
    response: Any,
    prompt_messages: list[Any],
    selected_model: str,
    selected_thinking_mode: str,
    model_for,
) -> Any:
    if not _looks_like_textual_tool_call_artifact(response):
        return response

    repaired = model_for(selected_model, selected_thinking_mode).invoke(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(response)),
        ]
    )
    if not _looks_like_textual_tool_call_artifact(repaired):
        return repaired

    final_attempt = model_for(selected_model, selected_thinking_mode).invoke(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            SystemMessage(content=_TOOL_CALL_LAST_RESORT_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(repaired)),
        ]
    )
    if not _looks_like_textual_tool_call_artifact(final_attempt):
        return final_attempt

    return AIMessage(content=_TOOL_CALL_REPAIR_FALLBACK_TEXT)


_PLAN_TRIGGER_KEYWORDS = (
    "然后",
    "接着",
    "之后",
    "并且",
    "对比",
    "分析",
    "then",
    "and then",
    "compare",
    "analyze",
    "step by step",
)


def _should_plan(
    *,
    state: AgentState,
    scene: str,
    plan_scenes: tuple[str, ...],
    min_chars: int,
) -> bool:
    existing = state.get("plan")
    if existing is not None:
        meta = state.get("plan_meta") or {}
        return bool(meta.get("replan_requested"))

    task_brief = str(state.get("task_brief") or "")
    if not task_brief:
        return False
    scene_allowed = scene in plan_scenes
    long_enough = len(task_brief) >= min_chars
    lowered = task_brief.lower()
    multi_step = any(keyword in lowered for keyword in _PLAN_TRIGGER_KEYWORDS)
    if long_enough:
        return True
    if scene_allowed and multi_step:
        return True
    return False


def _format_plan_block(plan: Plan, current_step_id: str) -> str:
    if not plan.steps:
        return ""
    lines = ["## 当前计划", f"目标验收: {plan.success_criteria or '(未声明)'}"]
    for step in plan.steps:
        marker = "✓" if step.done else ("➤" if step.id == current_step_id else "•")
        line = f"- {marker} [{step.id}] {step.goal}"
        if step.expected_tools:
            line += f"  (建议工具: {', '.join(step.expected_tools)})"
        if step.note:
            line += f"  // {step.note}"
        lines.append(line)
    lines.append(
        "完成当前步骤后，如仍需工具请继续调用；若已可给出最终答复，直接用自然语言回答。"
    )
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        newline = stripped.find("\n")
        if newline != -1:
            stripped = stripped[newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _parse_plan_json(text: str, *, created_at_call: int, replan_count: int) -> Plan | None:
    obj = _extract_json_object(text)
    if obj is None:
        return None
    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return None
    steps: list[PlanStep] = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            continue
        step_id = str(raw.get("id") or f"s{index + 1}")
        goal = str(raw.get("goal") or "").strip()
        if not goal:
            continue
        expected = raw.get("expected_tools") or []
        expected_tools = [str(t) for t in expected if isinstance(t, (str, int))]
        steps.append(PlanStep(id=step_id, goal=goal, expected_tools=expected_tools))
    if not steps:
        return None
    return Plan(
        steps=steps,
        success_criteria=str(obj.get("success_criteria") or "").strip(),
        created_at_call=created_at_call,
        replan_count=replan_count,
    )


def _parse_reflection_json(text: str) -> ReflectionVerdict | None:
    obj = _extract_json_object(text)
    if obj is None:
        return None
    status = str(obj.get("status") or "").strip().lower()
    if status not in {"done", "replan"}:
        return None
    missing_raw = obj.get("missing") or []
    missing = [str(m) for m in missing_raw if isinstance(m, (str, int))]
    return ReflectionVerdict(
        status=status,  # type: ignore[arg-type]
        reasoning=str(obj.get("reasoning") or ""),
        missing=missing,
    )


def _collect_tool_names_since_latest_human(messages: list[Any]) -> list[str]:
    names: list[str] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else None
                if name:
                    names.append(str(name))
    names.reverse()
    return names


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


def build_graph(
    *,
    settings: Settings,
    checkpointer=None,
    store=None,
    memory_retriever: MemoryRetriever | None = None,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
):
    effective_skill_registry = skill_registry or SkillRegistry.from_settings(settings)
    effective_tool_registry = tool_registry or build_tool_registry(
        settings=settings,
        skill_registry=effective_skill_registry,
        store=store,
        checkpointer=checkpointer,
    )
    tools = list(effective_tool_registry.tools)
    tools_by_name = effective_tool_registry.by_name
    base_model_cache: dict[str, Any] = {}
    model_cache: dict[str, Any] = {}
    model_with_tools_cache: dict[str, Any] = {}

    def base_model_for(model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = base_model_cache.get(cache_key)
        if cached is not None:
            return cached
        model = create_chat_model(
            model_id,
            temperature=settings.temperature,
            thinking_mode=thinking_mode or None,
            settings=settings,
        )
        base_model_cache[cache_key] = model
        return model

    def model_for(model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = model_cache.get(cache_key)
        if cached is not None:
            return cached
        model = base_model_for(model_id, thinking_mode).with_config({"run_name": "focus_agent_model"})
        model_cache[cache_key] = model
        return model

    def model_with_tools_for(model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = model_with_tools_cache.get(cache_key)
        if cached is not None:
            return cached
        bound = base_model_for(model_id, thinking_mode).bind_tools(tools).with_config({"run_name": "focus_agent_model"})
        model_with_tools_cache[cache_key] = bound
        return bound

    def bootstrap_turn(state: AgentState) -> dict[str, Any]:
        return {"llm_calls": state.get("llm_calls", 0)}

    def retrieve_memory(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        latest_user = _latest_human_message_text(state.get("messages", []))
        prompt_mode = _resolve_prompt_mode(state)
        if memory_retriever is not None:
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
                "prompt_mode": prompt_mode,
            }

        memories = (
            runtime.store.search(
                conversation_namespace_for_context(runtime.context),
                query=latest_user,
                limit=4,
            )
            if runtime.store
            else []
        )
        memory_texts = [
            str(item.value.get("summary") or item.value.get("text") or item.value)
            for item in memories
        ]
        return {
            "retrieved_memories": [
                {"summary": text, "namespace": list(conversation_namespace_for_context(runtime.context))}
                for text in memory_texts
            ],
            "memory_prompt_block": render_memory_block(
                type(
                    "_Bundle",
                    (),
                    {
                        "hits": [],
                    },
                )()
            )
            if not memory_texts
            else "## Retrieved long-term memories\n" + "\n".join(f"- {text}" for text in memory_texts),
            "prompt_mode": prompt_mode,
        }

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
        active_skills_block = effective_skill_registry.render_active_skills_block(active_skill_ids)
        available_skills_block = effective_skill_registry.render_available_skills_block()
        context_slice = build_context_slice(
            {
                **dict(state),
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
        return {
            "recent_messages": context_slice.recent_messages,
            "assembled_context": context_slice.render_prompt(),
            "task_brief": task_brief or state.get("task_brief", ""),
            "prompt_mode": prompt_mode,
            "active_skill_ids": list(active_skill_ids),
            "active_skills_block": active_skills_block,
            "available_skills_block": available_skills_block,
        }

    def plan_node(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        if not settings.plan_act_reflect_enabled:
            return {}
        scene = str(getattr(runtime.context, "scene", "") or "")
        if not _should_plan(
            state=state,
            scene=scene,
            plan_scenes=tuple(settings.plan_scenes),
            min_chars=int(settings.plan_task_brief_min_chars),
        ):
            return {}

        selected_model = str(state.get("selected_model") or settings.model)
        task_brief = str(state.get("task_brief") or _latest_human_message_text(state.get("messages", [])))
        tool_names = [t.name for t in tools][:20]
        prior_reflection = state.get("reflection")
        replan_count = 0
        existing_plan = state.get("plan")
        if isinstance(existing_plan, Plan):
            replan_count = existing_plan.replan_count + 1

        system = SystemMessage(
            content=(
                "你是一个任务规划器。阅读用户请求，输出一个紧凑、可验证的执行计划。"
                "必须返回 JSON，字段为 {\"steps\": [{\"id\": \"s1\", \"goal\": \"...\", "
                "\"expected_tools\": [\"tool_name\"]}], \"success_criteria\": \"...\"}。"
                "要求：2-5 步；success_criteria 必须客观可判断（禁止写‘充分’‘合理’这类模糊词）；"
                "只规划不执行；不要返回其它字段。"
            )
        )
        user_lines = [f"任务简述：{task_brief}", f"可用工具：{', '.join(tool_names) or '(无)'}"]
        if prior_reflection is not None:
            missing = ", ".join(prior_reflection.missing) or prior_reflection.reasoning
            user_lines.append(f"上一轮未满足：{missing}。请修正计划以覆盖这些缺口。")
        user = HumanMessage(content="\n".join(user_lines))

        try:
            response = model_for(selected_model, "").invoke([system, user])
            raw_text = _message_text(response)
            plan = _parse_plan_json(raw_text, created_at_call=state.get("llm_calls", 0), replan_count=replan_count)
        except Exception:  # noqa: BLE001
            plan = None

        if plan is None or not plan.steps:
            meta = {
                **(state.get("plan_meta") or {}),
                "plan_skipped": True,
                "replan_requested": False,
            }
            return {
                "plan": None,
                "current_step_id": "",
                "reflection": None,
                "plan_meta": meta,
                "llm_calls": state.get("llm_calls", 0) + 1,
            }

        meta = {
            **(state.get("plan_meta") or {}),
            "plan_calls": int((state.get("plan_meta") or {}).get("plan_calls", 0)) + 1,
            "replan_requested": False,
        }
        return {
            "plan": plan,
            "current_step_id": plan.steps[0].id,
            "reflection": None,
            "plan_meta": meta,
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    def reflect_node(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        del runtime
        plan = state.get("plan")
        if not isinstance(plan, Plan) or not plan.steps:
            return {}
        if plan.replan_count >= int(settings.plan_max_replans):
            meta = {**(state.get("plan_meta") or {}), "reflect_forced_done": True}
            return {
                "reflection": ReflectionVerdict(status="done", reasoning="replan budget exhausted"),
                "plan_meta": meta,
            }

        selected_model = str(state.get("selected_model") or settings.model)
        last_ai = _latest_final_ai_text(state.get("messages", []))
        trajectory_tools = _collect_tool_names_since_latest_human(list(state.get("messages", []) or []))

        system = SystemMessage(
            content=(
                "你是一个严格的计划审计员。判断最终答复是否满足 success_criteria。"
                "必须返回 JSON: {\"status\": \"done\"|\"replan\", \"reasoning\": \"...\", \"missing\": [\"...\"]}。"
                "只在确实存在未覆盖的子目标时选 replan，否则选 done。"
            )
        )
        plan_summary = _format_plan_block(plan, state.get("current_step_id", ""))
        user = HumanMessage(
            content=(
                f"success_criteria: {plan.success_criteria}\n"
                f"计划快照:\n{plan_summary}\n"
                f"已调用工具: {', '.join(trajectory_tools) or '(无)'}\n"
                f"最终答复:\n{last_ai}"
            )
        )
        try:
            response = model_for(selected_model, "").invoke([system, user])
            verdict = _parse_reflection_json(_message_text(response))
        except Exception:  # noqa: BLE001
            verdict = None

        if verdict is None:
            verdict = ReflectionVerdict(status="done", reasoning="reflect parse failed; defaulting done")

        meta = {
            **(state.get("plan_meta") or {}),
            "reflect_calls": int((state.get("plan_meta") or {}).get("reflect_calls", 0)) + 1,
        }
        if verdict.status == "replan" and plan.replan_count < int(settings.plan_max_replans):
            meta["replan_requested"] = True
            meta["replanned"] = True
        else:
            verdict = ReflectionVerdict(status="done", reasoning=verdict.reasoning, missing=verdict.missing)
            meta["replan_requested"] = False
        return {
            "reflection": verdict,
            "plan_meta": meta,
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    def agent_loop(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        del runtime
        messages = _messages_for_model(state)
        selected_model = str(state.get("selected_model") or settings.model)
        selected_thinking_mode = str(state.get("selected_thinking_mode") or "")
        assembled = state.get("assembled_context", "")
        plan = state.get("plan")
        if isinstance(plan, Plan) and plan.steps:
            plan_block = _format_plan_block(plan, state.get("current_step_id", ""))
            if plan_block and plan_block not in assembled:
                assembled = f"{assembled}\n\n{plan_block}".strip()
        prompt_messages = [SystemMessage(content=assembled), *messages]
        if _should_force_tool_free_answer(list(state.get("messages", []) or [])):
            response = model_for(selected_model, selected_thinking_mode).invoke(
                [
                    prompt_messages[0],
                    SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
                    *prompt_messages[1:],
                ]
            )
            response = _repair_tool_free_answer_response(
                response=response,
                prompt_messages=prompt_messages,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                model_for=model_for,
            )
        else:
            response = model_with_tools_for(selected_model, selected_thinking_mode).invoke(prompt_messages)
            response = _repair_textual_tool_call_response(
                response=response,
                prompt_messages=prompt_messages,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                model_for=model_for,
                model_with_tools_for=model_with_tools_for,
            )
        return {
            "messages": [response],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    def tool_executor(state: AgentState) -> dict[str, Any]:
        result_messages: list[ToolMessage] = []
        last_message = state["messages"][-1]
        for tool_call in getattr(last_message, "tool_calls", []) or []:
            tool = tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            result_messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
        return {"messages": result_messages}

    def summarize_turn(state: AgentState) -> dict[str, Any]:
        last_user = _latest_human_message_text(state.get("messages", []))
        last_ai = _latest_final_ai_text(state.get("messages", []))
        previous_summary = state.get("rolling_summary", "")
        candidate_lines = [
            line
            for line in [previous_summary, f"User: {last_user}", f"Assistant: {last_ai}"]
            if line
        ]
        joined = "\n".join(candidate_lines)
        if len(joined) > 4000:
            joined = joined[-4000:]
        return {"rolling_summary": joined}

    def maybe_interrupt_for_merge(state: AgentState) -> dict[str, Any]:
        if state.get("merge_proposal") and not state.get("merge_decision"):
            decision = interrupt(
                {
                    "kind": "merge_review",
                    "proposal": state["merge_proposal"],
                    "message": "Review the branch proposal and choose whether to import it into the parent thread.",
                }
            )
            return {"merge_decision": decision}
        return {}

    def should_continue_after_act(
        state: AgentState,
    ) -> Literal["tool_executor", "reflect", "summarize_turn"]:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tool_executor"
        if settings.plan_act_reflect_enabled and isinstance(state.get("plan"), Plan):
            return "reflect"
        return "summarize_turn"

    def should_continue_after_reflect(
        state: AgentState,
    ) -> Literal["plan", "summarize_turn"]:
        meta = state.get("plan_meta") or {}
        if meta.get("replan_requested"):
            return "plan"
        return "summarize_turn"

    builder = StateGraph(AgentState, context_schema=RequestContext)
    builder.add_node("bootstrap_turn", bootstrap_turn)
    builder.add_node("retrieve_memory", retrieve_memory)
    builder.add_node("assemble_context", assemble_context)
    builder.add_node("plan", plan_node)
    builder.add_node("agent_loop", agent_loop)
    builder.add_node("tool_executor", tool_executor)
    builder.add_node("reflect", reflect_node)
    builder.add_node("summarize_turn", summarize_turn)
    builder.add_node("maybe_interrupt_for_merge", maybe_interrupt_for_merge)

    builder.add_edge(START, "bootstrap_turn")
    builder.add_edge("bootstrap_turn", "retrieve_memory")
    builder.add_edge("retrieve_memory", "assemble_context")
    builder.add_edge("assemble_context", "plan")
    builder.add_edge("plan", "agent_loop")
    builder.add_conditional_edges(
        "agent_loop",
        should_continue_after_act,
        ["tool_executor", "reflect", "summarize_turn"],
    )
    builder.add_edge("tool_executor", "agent_loop")
    builder.add_conditional_edges(
        "reflect",
        should_continue_after_reflect,
        ["plan", "summarize_turn"],
    )
    builder.add_edge("summarize_turn", "maybe_interrupt_for_merge")
    builder.add_edge("maybe_interrupt_for_merge", END)

    return builder.compile(checkpointer=checkpointer, store=store)
