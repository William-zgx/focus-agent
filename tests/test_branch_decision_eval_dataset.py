"""Offline (no model) checks of the branch-decision eval dataset against the rule layer.

Cases marked ``expected_classifier: bypass`` are decided by the deterministic rules and
must produce ``expected_action``; ``run`` cases must leave the decision to the semantic
classifier (rules say ``continue_current``) so a model cannot be pre-empted by a rule
false positive.
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.branch_decision.scorers import score_branch_recommendation
from focus_agent.branch_decision.service_helpers import _should_run_semantic_topic_relation
from focus_agent.branch_decision.signals import collect_branch_recommendation_signals
from focus_agent.core.branching import BranchMeta

_ROOT = Path(__file__).resolve().parents[1]
_DATASET = _ROOT / "tests/eval/datasets/branch_decision_models.json"
_CASES: list[dict[str, Any]] = json.loads(_DATASET.read_text(encoding="utf-8"))


def _rule_decision(case: dict[str, Any]) -> tuple[str, bool]:
    messages = [
        HumanMessage(content=item["content"])
        if item["role"] == "user"
        else AIMessage(content=item["content"])
        for item in case["history"]
    ]
    branch_context = case.get("branch_context")
    signals = collect_branch_recommendation_signals(
        message=case["incoming"],
        values={"messages": messages},
        branch_meta=None if branch_context is None else BranchMeta.model_validate(branch_context),
    )
    score = score_branch_recommendation(signals=signals, min_confidence=0.72)
    return score.action.value, _should_run_semantic_topic_relation(
        signals=signals, action=score.action
    )


def test_dataset_loads_with_the_eval_script_validator() -> None:
    spec = importlib.util.spec_from_file_location(
        "decision_model_eval", _ROOT / "scripts/decision_model_eval.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert len(module._load_dataset(_DATASET)) == len(_CASES)


def test_dataset_has_no_duplicate_cases() -> None:
    keys = Counter(
        (case["incoming"], json.dumps(case.get("branch_context"), sort_keys=True))
        for case in _CASES
    )
    assert [key for key, count in keys.items() if count > 1] == []


@pytest.mark.parametrize("case", _CASES, ids=[case["id"] for case in _CASES])
def test_rule_layer_matches_dataset_expectation(case: dict[str, Any]) -> None:
    action, classifier_runs = _rule_decision(case)

    if case["expected_classifier"] == "bypass":
        assert action == case["expected_action"]
        assert classifier_runs is False
    else:
        assert action == "continue_current"
        assert classifier_runs is True
