from __future__ import annotations

import json

from langchain.messages import AIMessage, HumanMessage

from focus_agent.core.merge_review import generate_merge_proposal


class CaptureModel:
    def __init__(self):
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return AIMessage(
            content=json.dumps(
                {
                    "summary": "分支新增结论",
                    "key_findings": ["结论 A"],
                    "open_questions": ["问题 B"],
                    "evidence_refs": ["证据 C"],
                    "artifacts": ["artifact-1"],
                    "recommended_import_mode": "summary_plus_evidence",
                },
                ensure_ascii=False,
            )
        )


class FailingModel:
    def invoke(self, messages):
        raise RuntimeError("provider unavailable")


def test_generate_merge_proposal_keeps_inherited_context_brief_and_matches_language():
    model = CaptureModel()
    state = {
        "rolling_summary": "主线背景 " * 120 + "尾部不应完整出现在结论 prompt 里",
        "branch_local_findings": ["验证了新的假设", "收敛出更短的方案"],
        "messages": [
            HumanMessage(content="我们继续看这个中文分支"),
            AIMessage(content="好的，我会基于这个中文上下文整理结论。"),
        ],
        "merge_queue": [
            {
                "branch_name": "parent-branch",
                "summary": "父分支此前确认了基础假设和用户目标。",
            }
        ],
    }

    proposal = generate_merge_proposal(
        model, state, {"branch_name": "中文分支", "branch_role": "deep_dive"}
    )

    assert proposal.summary == "分支新增结论"
    prompt = model.messages[-1].content
    assert "Output language: Chinese" in prompt
    assert "Inherited upstream context (brief):" in prompt
    assert "主线背景" not in prompt
    assert "This branch's recent interaction history:" in prompt
    assert "Generate the conclusion mainly from this branch's own interaction history." in prompt
    assert "尾部不应完整出现在结论 prompt 里" not in prompt
    assert (
        "Do not restate parent-thread context unless this branch materially changed or challenged it."
        in prompt
    )


def test_generate_merge_proposal_falls_back_when_model_call_fails():
    proposal = generate_merge_proposal(
        FailingModel(),
        {
            "branch_local_findings": ["模型失败时也保留本地结论"],
            "messages": [HumanMessage(content="整理这个分支")],
        },
        {"branch_name": "fallback-branch"},
    )

    assert proposal.summary == "模型失败时也保留本地结论"
    assert proposal.key_findings == ["模型失败时也保留本地结论"]
    assert proposal.recommended_import_mode == "summary_only"


class ScriptedModel:
    def __init__(self, payload):
        self.payload = payload
        self.prompt = ""

    def invoke(self, messages):
        self.prompt = messages[-1].content
        return AIMessage(content=json.dumps(self.payload, ensure_ascii=False))


def _forked_state(local_messages, **extra):
    parent = [
        HumanMessage(content="Parent asks about databases"),
        AIMessage(content="Shortlist: CockroachDB, YugabyteDB, Aurora"),
    ]
    state = {
        "messages": [*parent, *local_messages],
        "branch_meta": {
            "branch_id": "b-1",
            "branch_name": "Yugabyte",
            "branch_fork_message_count": len(parent),
            "fork_inherited_counts": {
                "imported_findings": 1,
                "merge_queue": 1,
                "branch_local_findings": 0,
                "citations": 0,
                "artifacts": 0,
            },
        },
        "imported_findings": [{"finding": "OLD main finding"}],
        "merge_queue": [{"branch_name": "main-old", "summary": "OLD main import"}],
    }
    state.update(extra)
    return state


def test_proposal_prompt_uses_branch_local_messages_and_keeps_early_findings():
    local = [
        HumanMessage(content="How does its cost compare?"),
        AIMessage(content="KEY FINDING: Yugabyte lacks feature X " + "detail " * 300),
    ]
    local += [
        message
        for index in range(15)
        for message in (HumanMessage(content=f"q{index}"), AIMessage(content=f"a{index}"))
    ]
    model = ScriptedModel({"summary": "s", "key_findings": []})

    generate_merge_proposal(model, _forked_state(local), {"branch_name": "Yugabyte"})

    assert "Shortlist" not in model.prompt
    assert "KEY FINDING: Yugabyte lacks feature X" in model.prompt
    assert "middle messages condensed" in model.prompt
    assert "a14" in model.prompt
    assert "detail " * 120 not in model.prompt


def test_proposal_prompt_receives_citations_evidence_artifacts_summary_and_nested_imports():
    state = _forked_state(
        [HumanMessage(content="Benchmark it"), AIMessage(content="Done")],
        rolling_summary="Branch summary: benchmark ran twice.",
        citations=[{"label": "Benchmark", "uri": "https://example.com/bench"}],
        evidence_ledger=[{"id": "ev-1", "title": "Pricing page", "url": "https://ex.com/p"}],
        artifacts=[{"title": "bench.csv", "kind": "file", "uri": "file:///bench.csv"}],
    )
    state["imported_findings"].append({"finding": "NESTED FINDING: B is 30% cheaper"})
    state["merge_queue"].append(
        {"branch_name": "nested-child", "summary": "NESTED CHILD CONCLUSION: option B wins"}
    )
    model = ScriptedModel({"summary": "s"})

    generate_merge_proposal(model, state, {"branch_name": "Yugabyte"})

    prompt = model.prompt
    assert "https://example.com/bench" in prompt
    assert "ev-1: Pricing page (https://ex.com/p)" in prompt
    assert "bench.csv (file:///bench.csv)" in prompt
    assert "Branch summary: benchmark ran twice." in prompt
    received = prompt.split("Conclusions imported into this branch after the fork:")[1]
    received = received.split("Recorded findings:")[0]
    assert "NESTED CHILD CONCLUSION" in received
    assert "NESTED FINDING" in received
    assert "OLD main" not in received
    assert "main-old: OLD main import" in prompt


def test_proposal_keeps_only_known_evidence_refs_and_per_finding_refs():
    state = _forked_state(
        [HumanMessage(content="Check"), AIMessage(content="Checked")],
        citations=[{"label": "Benchmark", "uri": "https://example.com/bench"}],
        evidence_ledger=[{"id": "ev-1", "title": "Pricing", "url": "https://ex.com/p"}],
    )
    model = ScriptedModel(
        {
            "summary": "B wins",
            "key_findings": [
                {"finding": "B is faster", "evidence_refs": ["Benchmark", "invented-ref"]},
                {"finding": "B is cheaper", "evidence_refs": ["ev-1"]},
                "Plain finding",
            ],
            "evidence_refs": ["made-up", "see https://example.com/bench#x"],
        }
    )

    proposal = generate_merge_proposal(model, state, {"branch_name": "Yugabyte"})

    assert proposal.key_findings == ["B is faster", "B is cheaper", "Plain finding"]
    assert proposal.finding_evidence_refs == {
        "B is faster": ["Benchmark"],
        "B is cheaper": ["ev-1"],
    }
    assert proposal.evidence_refs == ["see https://example.com/bench#x", "Benchmark", "ev-1"]


def test_empty_branch_fallback_is_not_importable():
    proposal = generate_merge_proposal(FailingModel(), _forked_state([]), {"branch_name": "b"})

    assert proposal.summary == ""
    assert proposal.key_findings == []
    assert "No explicit" not in proposal.model_dump_json()


def test_fallback_carries_nested_imports_forward():
    state = _forked_state([HumanMessage(content="merge it"), AIMessage(content="ok")])
    state["imported_findings"].append({"finding": "NESTED FINDING", "evidence_refs": ["doc-9"]})

    proposal = generate_merge_proposal(FailingModel(), state, {"branch_name": "b"})

    assert proposal.key_findings == ["NESTED FINDING"]
    assert proposal.finding_evidence_refs == {"NESTED FINDING": ["doc-9"]}
    assert "OLD main finding" not in proposal.key_findings
