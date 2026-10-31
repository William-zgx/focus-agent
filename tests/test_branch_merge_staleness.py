from __future__ import annotations

import json

from langchain.messages import AIMessage, HumanMessage, SystemMessage

from focus_agent.core.merge_review import generate_merge_proposal
from focus_agent.services.branches.merge_upstream import findings_conflict

from .test_branch_merge_quality import _service


class ScriptedModel:
    def __init__(self, payload):
        self.payload = payload
        self.prompt = ""

    def invoke(self, messages):
        self.prompt = messages[-1].content
        return AIMessage(content=json.dumps(self.payload))


def _forked_service():
    service = _service(
        {
            "root-1": {
                "messages": [
                    HumanMessage(content="Pick a DB for billing"),
                    AIMessage(content="Shortlist: Yugabyte, Aurora"),
                ],
                "merge_queue": [{"branch_name": "older", "summary": "older import"}],
            }
        }
    )
    record = service.fork_branch(parent_thread_id="root-1", user_id="user-1")
    child = service.graph.states[record.child_thread_id]
    child["messages"] = [
        *child["messages"],
        HumanMessage(content="Compare Yugabyte cost"),
        AIMessage(content="Yugabyte costs $1.5k/mo"),
    ]
    return service, record


def _prepare(service, record, payload):
    model = ScriptedModel(payload)
    service.proposal_model = model
    service.proposal_generator = generate_merge_proposal
    proposal = service.prepare_merge_proposal(
        child_thread_id=record.child_thread_id, user_id="user-1"
    )
    return proposal, model.prompt


def test_proposal_is_fresh_when_parent_did_not_move():
    service, record = _forked_service()

    proposal, prompt = _prepare(service, record, {"summary": "Yugabyte costs $1.5k/mo"})

    assert proposal.parent_moved_on is False
    assert proposal.conflicts == []
    assert "Parent thread changes since this branch forked:\n(none)" in prompt
    dumped = proposal.model_dump(mode="json")
    assert dumped["parent_moved_on"] is False
    assert dumped["conflicts"] == []


def test_proposal_flags_parent_drift_and_sibling_conflicts():
    service, record = _forked_service()
    parent = service.graph.states["root-1"]
    parent["messages"] = [
        *parent["messages"],
        HumanMessage(content="Budget is now capped at $1k/mo"),
        AIMessage(content="Understood, $1k/mo cap."),
        SystemMessage(content="Imported conclusion from branch 'Aurora':\nAurora wins"),
    ]
    parent["merge_queue"] = [
        *parent["merge_queue"],
        {
            "branch_id": "sibling",
            "branch_name": "Aurora",
            "summary": "Aurora wins",
            "key_findings": ["Yugabyte costs $2k/mo"],
        },
    ]

    proposal, prompt = _prepare(
        service,
        record,
        {"summary": "Yugabyte wins", "key_findings": ["Yugabyte costs $1.5k/mo"]},
    )

    assert proposal.parent_moved_on is True
    assert [conflict.model_dump() for conflict in proposal.conflicts] == [
        {
            "branch_name": "Aurora",
            "finding": "Yugabyte costs $1.5k/mo",
            "conflicting_finding": "Yugabyte costs $2k/mo",
        }
    ]
    updates = prompt.split("Parent thread changes since this branch forked:")[1]
    assert "Budget is now capped at $1k/mo" in updates
    assert "Sibling import [Aurora]: Aurora wins" in updates
    assert "older import" not in updates
    stored = service.graph.states[record.child_thread_id]["merge_proposal"]
    assert stored["parent_moved_on"] is True
    assert stored["conflicts"][0]["branch_name"] == "Aurora"


def test_lexical_conflict_rules():
    assert findings_conflict("Yugabyte supports feature X", "Yugabyte lacks feature X")
    assert findings_conflict("Option B wins on cost", "Option A wins on cost")
    assert findings_conflict("Yugabyte costs $1.5k/mo", "Yugabyte costs $2k/mo")
    assert not findings_conflict("Yugabyte costs $1.5k/mo", "Yugabyte costs $1.5k/mo.")
    assert not findings_conflict("Aurora has good tooling", "Yugabyte costs $2k/mo")
