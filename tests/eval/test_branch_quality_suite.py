"""Deterministic branch-quality suite (fork, merge review, merge apply, memory).

Each scenario drives the real ``BranchService`` / prompt assembly / memory
retrieval against an in-memory graph that applies the ``AgentState`` reducers,
with scripted fake models, and scores how much branch knowledge survives.

Run ``python -m tests.eval.test_branch_quality_suite`` to print the summary
metrics as JSON. The scenarios only use entry points that predate the branch
quality work, so the same file also measures older revisions.
"""

from __future__ import annotations

import json
import operator
import re
import tempfile
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_type_hints

from langchain.messages import AIMessage, HumanMessage

from focus_agent.core.branching import MergeDecision, MergeMode
from focus_agent.core.context.policy import assemble_context
from focus_agent.core.merge_review import generate_merge_proposal
from focus_agent.core.request_context import RequestContext
from focus_agent.core.state import AgentState
from focus_agent.core.types import PromptMode
from focus_agent.engine.local_persistence import PersistentInMemoryStore
from focus_agent.memory import MemoryRetriever, MemoryWriter, render_memory_block
from focus_agent.memory.models import (
    MemoryKind,
    MemoryScope,
    MemoryVisibility,
    MemoryWriteRequest,
)
from focus_agent.services.branches import BranchService
from focus_agent.storage.namespaces import root_thread_episodic_namespace

from ..test_branch_conclusion_policy import FakeRepo

ROOT = "root-1"
USER = "user-1"
_ADDITIVE_KEYS = {
    name
    for name, hint in get_type_hints(AgentState, include_extras=True).items()
    if operator.add in getattr(hint, "__metadata__", ())
}
METRIC_THRESHOLDS = {
    "fork_recall": 1.0,
    "proposal_fidelity": 1.0,
    "evidence_survival": 1.0,
    "evidence_precision": 1.0,
    "imports_after_merges_and_compaction": 1.0,
    "nested_two_hop_survival": 1.0,
    "memory_isolation": 1.0,
    "empty_branch_guard": 1.0,
}


class ReducerGraph:
    """In-memory graph whose ``update_state`` honours additive state reducers."""

    def __init__(self, states: dict[str, dict]):
        self.states = {thread_id: deepcopy(values) for thread_id, values in states.items()}

    def get_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        return SimpleNamespace(values=deepcopy(self.states.get(thread_id, {})))

    def update_state(self, config, values, as_node=None):
        del as_node
        state = self.states.setdefault(config["configurable"]["thread_id"], {})
        for key, value in deepcopy(values).items():
            if key in _ADDITIVE_KEYS and isinstance(value, list):
                state[key] = [*list(state.get(key) or []), *value]
            else:
                state[key] = value


class FailingModel:
    def invoke(self, messages):
        del messages
        raise RuntimeError("model unavailable")


class ScriptedModel:
    """Returns a fixed proposal payload and records the prompt it was shown."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.prompt = ""

    def invoke(self, messages):
        self.prompt = str(messages[-1].content)
        return AIMessage(content=json.dumps(self.payload))


class GroundedModel:
    """Proposes exactly the ``FACT-*`` markers visible in its prompt."""

    def __init__(self):
        self.prompt = ""

    def invoke(self, messages):
        self.prompt = str(messages[-1].content)
        facts = sorted(set(re.findall(r"FACT-[A-Za-z0-9-]+", self.prompt)))
        payload = {
            "summary": ("Confirmed " + ", ".join(facts)) if facts else "",
            "key_findings": [f"{fact} holds" for fact in facts],
        }
        return AIMessage(content=json.dumps(payload))


def _service(states: dict[str, dict]) -> BranchService:
    service = object.__new__(BranchService)
    service.repo = FakeRepo()
    service.graph = ReducerGraph(states)
    service.thread_client = None
    service.proposal_model = None
    service.proposal_generator = generate_merge_proposal
    service.settings = SimpleNamespace(branch_max_depth=5)
    service.store = None
    service.memory_writer = None
    service.repo.ensure_thread_owner(thread_id=ROOT, root_thread_id=ROOT, owner_user_id=USER)
    return service


def _fork(service: BranchService, parent: str) -> str:
    return service.fork_branch(parent_thread_id=parent, user_id=USER).child_thread_id


def _chat(service: BranchService, thread_id: str, *turns: tuple[str, str]) -> None:
    messages = []
    for user, assistant in turns:
        messages.extend([HumanMessage(content=user), AIMessage(content=assistant)])
    service.graph.update_state({"configurable": {"thread_id": thread_id}}, {"messages": messages})


def _merge(service: BranchService, thread_id: str, model, *, mode=MergeMode.SUMMARY_PLUS_EVIDENCE):
    service.proposal_model = model
    service.prepare_merge_proposal(child_thread_id=thread_id, user_id=USER)
    return service.apply_merge_decision(
        child_thread_id=thread_id,
        decision=MergeDecision(approved=True, mode=mode),
        context=RequestContext(user_id=USER, root_thread_id=ROOT),
    )


def _prompt_text(state: dict[str, Any], mode: PromptMode = PromptMode.EXPLORE) -> str:
    context = assemble_context(state, mode)
    messages = "\n".join(str(message.content) for message in context.recent_messages)
    return f"{context.render_prompt()}\n{messages}"


def _ratio(checks: list[bool]) -> float:
    return round(sum(1 for item in checks if item) / len(checks), 4) if checks else 0.0


@dataclass(slots=True)
class ScenarioResult:
    case_id: str
    metrics: dict[str, float]
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(
            value >= METRIC_THRESHOLDS.get(name, 1.0) for name, value in self.metrics.items()
        )


def scenario_fork_recall() -> ScenarioResult:
    service = _service(
        {
            ROOT: {
                "messages": [
                    HumanMessage(content="Choose a DB for billing; it must be Postgres-compatible"),
                    AIMessage(content="Shortlist: CockroachDB, YugabyteDB, Aurora."),
                    HumanMessage(content="Hard constraint: budget < $2k/mo"),
                    AIMessage(content="Noted: budget < $2k/mo for every option."),
                ],
                "rolling_summary": "Earlier the user rejected MySQL due to licensing.",
            }
        }
    )
    child = _fork(service, ROOT)
    service.graph.update_state(
        {"configurable": {"thread_id": child}},
        {"messages": [HumanMessage(content="How does its cost compare?")]},
    )
    prompt = _prompt_text(service.graph.states[child])
    expected = ["Postgres-compatible", "budget < $2k/mo", "rejected MySQL"]
    checks = [item in prompt for item in expected]
    return ScenarioResult(
        "fork_recall_parent_constraints",
        {"fork_recall": _ratio(checks)},
        {"missing": [item for item, ok in zip(expected, checks, strict=True) if not ok]},
    )


def scenario_proposal_fidelity() -> ScenarioResult:
    service = _service(
        {ROOT: {"messages": [HumanMessage(content="PARENT-ONLY context about vendors")]}}
    )
    child = _fork(service, ROOT)
    _chat(service, child, ("Benchmark Yugabyte", "EARLY-FINDING: Yugabyte p99 is 12ms"))
    service.graph.update_state(
        {"configurable": {"thread_id": child}},
        {
            "citations": [{"label": "YB benchmark", "uri": "https://example.com/yb-bench"}],
            "evidence_ledger": [
                {"id": "ev-1", "title": "YB pricing", "url": "https://example.com/yb-price"}
            ],
        },
    )
    _chat(service, child, *[(f"follow-up {index}", f"answer {index}") for index in range(12)])
    model = ScriptedModel({"summary": "ok", "key_findings": ["ok"]})
    service.proposal_model = model
    service.prepare_merge_proposal(child_thread_id=child, user_id=USER)
    expected = [
        "EARLY-FINDING: Yugabyte p99 is 12ms",
        "https://example.com/yb-bench",
        "https://example.com/yb-price",
        "answer 11",
    ]
    checks = [item in model.prompt for item in expected]
    checks.append("PARENT-ONLY" not in model.prompt)
    return ScenarioResult("proposal_fidelity_long_branch", {"proposal_fidelity": _ratio(checks)})


def scenario_evidence_survival() -> ScenarioResult:
    service = _service({ROOT: {"messages": [HumanMessage(content="Compare vendors")]}})
    child = _fork(service, ROOT)
    _chat(service, child, ("Check cost and latency", "Done"))
    service.graph.update_state(
        {"configurable": {"thread_id": child}},
        {"citations": [{"label": "pricing-page"}, {"label": "latency-bench"}]},
    )
    findings = {"Yugabyte costs $1.5k/mo": "pricing-page", "Yugabyte p99 is 12ms": "latency-bench"}
    model = ScriptedModel(
        {
            "summary": "Yugabyte fits",
            "key_findings": list(findings),
            "evidence_refs": list(findings.values()),
            "finding_evidence_refs": {key: [value] for key, value in findings.items()},
        }
    )
    _merge(service, child, model)
    lines = _prompt_text(service.graph.states[ROOT]).splitlines()
    survival: list[bool] = []
    precision: list[bool] = []
    for finding, ref in findings.items():
        finding_lines = [line for line in lines if finding in line and "evidence" in line]
        survival.append(any(ref in line for line in finding_lines))
        others = [other for other in findings.values() if other != ref]
        precision.append(
            bool(finding_lines)
            and all(not any(other in line for other in others) for line in finding_lines)
        )
    return ScenarioResult(
        "evidence_survival_through_apply",
        {"evidence_survival": _ratio(survival), "evidence_precision": _ratio(precision)},
    )


def scenario_imports_after_merges_and_compaction() -> ScenarioResult:
    service = _service({ROOT: {"messages": [HumanMessage(content="Plan the billing DB")]}})
    expected: list[str] = []
    for index in range(3):
        child = _fork(service, ROOT)
        _chat(service, child, (f"Explore option {index}", f"Option {index} explored"))
        findings = [f"Option {index} finding {k} " + "detail " * (3 - index) for k in range(4)]
        payload = {
            "summary": f"Option {index} summary",
            "key_findings": findings,
            "open_questions": [f"Option {index} open question"],
            "artifacts": [f"option-{index}.md"],
        }
        _merge(service, child, ScriptedModel(payload), mode=MergeMode.SUMMARY_ONLY)
        expected.extend([payload["summary"], *payload["key_findings"], *payload["open_questions"]])
        expected.extend(payload["artifacts"])
    _chat(
        service,
        ROOT,
        *[(f"later question {index}", f"later answer {index}") for index in range(20)],
    )
    compacted = "Compacted: the user is planning the billing DB."
    service.graph.update_state(
        {"configurable": {"thread_id": ROOT}},
        {
            "rolling_summary": compacted,
            "context_compaction": {"compaction_version": 2, "history_summary": compacted},
        },
    )
    prompt = _prompt_text(service.graph.states[ROOT])
    checks = [item.strip() in prompt for item in expected]
    return ScenarioResult(
        "imports_survive_three_merges_and_compaction",
        {"imports_after_merges_and_compaction": _ratio(checks)},
        {"missing": [item for item, ok in zip(expected, checks, strict=True) if not ok]},
    )


def scenario_nested_two_hop() -> ScenarioResult:
    service = _service(
        {
            ROOT: {
                "messages": [HumanMessage(content="Pick a DB")],
                "merge_queue": [
                    {"branch_name": "old-1", "summary": "old main import one"},
                    {"branch_name": "old-2", "summary": "old main import two"},
                ],
            }
        }
    )
    parent = _fork(service, ROOT)
    _chat(service, parent, ("Dig into pricing", "Pricing looks fine"))
    grandchild = _fork(service, parent)
    _chat(service, grandchild, ("Check option B", "FACT-nested-b-cheaper: option B is 30% cheaper"))
    _merge(service, grandchild, GroundedModel())
    _chat(service, parent, *[(f"parent follow-up {index}", f"reply {index}") for index in range(6)])
    _merge(service, parent, GroundedModel())
    prompt = _prompt_text(service.graph.states[ROOT])
    return ScenarioResult(
        "nested_two_hop_survival",
        {"nested_two_hop_survival": 1.0 if "FACT-nested-b-cheaper" in prompt else 0.0},
    )


def scenario_memory_isolation() -> ScenarioResult:
    with tempfile.TemporaryDirectory() as tmp:
        store = PersistentInMemoryStore(Path(tmp) / "store.pkl")
        MemoryWriter(store=store).write_records(
            [
                MemoryWriteRequest(
                    kind=MemoryKind.TURN_SUMMARY,
                    scope=MemoryScope.ROOT_THREAD,
                    visibility=MemoryVisibility.PRIVATE,
                    namespace=root_thread_episodic_namespace(ROOT),
                    content="LEAKTOKEN unreviewed yugabyte pricing claim",
                    summary="LEAKTOKEN unreviewed yugabyte pricing claim",
                    source_branch_id="branch-a",
                    root_thread_id=ROOT,
                    user_id=USER,
                    importance=0.9,
                )
            ]
        )
        retriever = MemoryRetriever(store=store)

        def block(branch_id: str | None) -> str:
            state = {"branch_meta": {"branch_id": branch_id}} if branch_id else {}
            bundle = retriever.retrieve_for_turn(
                context=RequestContext(user_id=USER, root_thread_id=ROOT, branch_id=branch_id),
                state=state,
                query="yugabyte pricing",
                prompt_mode=PromptMode.EXPLORE,
            )
            return render_memory_block(bundle)

        isolated = ["LEAKTOKEN" not in block(None), "LEAKTOKEN" not in block("branch-b")]
        own_branch_visible = "LEAKTOKEN" in block("branch-a")
    return ScenarioResult(
        "memory_leak_unmerged_branch",
        {"memory_isolation": _ratio(isolated)},
        {"own_branch_visible": own_branch_visible},
    )


def scenario_empty_branch_guard() -> ScenarioResult:
    service = _service({ROOT: {"messages": [HumanMessage(content="Pick a DB")]}})
    child = _fork(service, ROOT)
    try:
        _merge(service, child, FailingModel(), mode=MergeMode.SUMMARY_ONLY)
    except ValueError:
        guarded = True
    else:
        guarded = not service.graph.states[ROOT].get("merge_queue")
    return ScenarioResult("empty_branch_import_guard", {"empty_branch_guard": float(guarded)})


SCENARIOS: tuple[Callable[[], ScenarioResult], ...] = (
    scenario_fork_recall,
    scenario_proposal_fidelity,
    scenario_evidence_survival,
    scenario_imports_after_merges_and_compaction,
    scenario_nested_two_hop,
    scenario_memory_isolation,
    scenario_empty_branch_guard,
)


def run_scenarios() -> list[ScenarioResult]:
    return [scenario() for scenario in SCENARIOS]


def build_summary(results: list[ScenarioResult]) -> dict[str, Any]:
    metrics: dict[str, float] = {}
    for result in results:
        metrics.update(result.metrics)
    passed = sum(1 for result in results if result.passed)
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "task_success": round(passed / len(results), 4) if results else 0.0,
        **metrics,
        "failed_case_ids": [result.case_id for result in results if not result.passed],
    }


def test_branch_quality_suite_meets_thresholds():
    results = run_scenarios()
    summary = build_summary(results)

    for name, threshold in METRIC_THRESHOLDS.items():
        assert summary[name] >= threshold, (name, summary, [r.details for r in results])
    assert summary["failed_case_ids"] == []


def test_memory_isolation_keeps_own_branch_visibility():
    assert scenario_memory_isolation().details["own_branch_visible"] is True


if __name__ == "__main__":
    print(json.dumps(build_summary(run_scenarios()), indent=2, ensure_ascii=False))
