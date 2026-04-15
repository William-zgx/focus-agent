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

    proposal = generate_merge_proposal(model, state, {"branch_name": "中文分支", "branch_role": "deep_dive"})

    assert proposal.summary == "分支新增结论"
    prompt = model.messages[-1].content
    assert "Output language: Chinese" in prompt
    assert "Inherited upstream context (brief):" in prompt
    assert "主线背景" not in prompt
    assert "This branch's recent interaction history:" in prompt
    assert "Generate the conclusion mainly from this branch's own interaction history." in prompt
    assert "尾部不应完整出现在结论 prompt 里" not in prompt
    assert "Do not restate parent-thread context unless this branch materially changed or challenged it." in prompt
