from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Literal

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from ..config import Settings
from ..core.request_context import RequestContext
from ..core.state import AgentState
from ..core.types import Plan, PlanStep, ReflectionVerdict
from .graph_turn_helpers import (
    _latest_final_ai_text,
    _latest_human_message_text,
    _message_text,
)

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
    lines.append("完成当前步骤后，如仍需工具请继续调用；若已可给出最终答复，直接用自然语言回答。")
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


def make_plan_node(
    *,
    settings: Settings,
    model_for: Callable[[str, str], Any],
    tools: Sequence[Any],
) -> Any:
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

        model_route_decision = state.get("model_route_decision") or {}
        if (
            isinstance(model_route_decision, dict)
            and model_route_decision.get("enabled")
            and model_route_decision.get("mode") == "enforce"
            and model_route_decision.get("effective_model")
        ):
            selected_model = str(model_route_decision.get("effective_model"))
        else:
            selected_model = str(state.get("selected_model") or settings.model)
        task_brief = str(
            state.get("task_brief") or _latest_human_message_text(state.get("messages", []))
        )
        tool_names = [tool.name for tool in tools][:20]
        prior_reflection = state.get("reflection")
        replan_count = 0
        existing_plan = state.get("plan")
        if isinstance(existing_plan, Plan):
            replan_count = existing_plan.replan_count + 1

        system = SystemMessage(
            content=(
                "你是一个任务规划器。阅读用户请求，输出一个紧凑、可验证的执行计划。"
                '必须返回 JSON，字段为 {"steps": [{"id": "s1", "goal": "...", '
                '"expected_tools": ["tool_name"]}], "success_criteria": "..."}。'
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
            plan = _parse_plan_json(
                raw_text, created_at_call=state.get("llm_calls", 0), replan_count=replan_count
            )
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

    return plan_node


def make_reflect_node(
    *,
    settings: Settings,
    model_for: Callable[[str, str], Any],
) -> Any:
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
        trajectory_tools = _collect_tool_names_since_latest_human(
            list(state.get("messages", []) or [])
        )

        system = SystemMessage(
            content=(
                "你是一个严格的计划审计员。判断最终答复是否满足 success_criteria。"
                '必须返回 JSON: {"status": "done"|"replan", "reasoning": "...", '
                '"missing": ["..."]}。'
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
            verdict = ReflectionVerdict(
                status="done", reasoning="reflect parse failed; defaulting done"
            )

        meta = {
            **(state.get("plan_meta") or {}),
            "reflect_calls": int((state.get("plan_meta") or {}).get("reflect_calls", 0)) + 1,
        }
        if verdict.status == "replan" and plan.replan_count < int(settings.plan_max_replans):
            meta["replan_requested"] = True
            meta["replanned"] = True
        else:
            verdict = ReflectionVerdict(
                status="done", reasoning=verdict.reasoning, missing=verdict.missing
            )
            meta["replan_requested"] = False
        return {
            "reflection": verdict,
            "plan_meta": meta,
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    return reflect_node


def make_should_continue_after_reflect(
    state: AgentState,
) -> Literal["plan", "summarize_turn"]:
    meta = state.get("plan_meta") or {}
    if meta.get("replan_requested"):
        return "plan"
    return "summarize_turn"


__all__ = [
    "_format_plan_block",
    "_parse_plan_json",
    "_parse_reflection_json",
    "_should_plan",
    "make_plan_node",
    "make_reflect_node",
    "make_should_continue_after_reflect",
]
