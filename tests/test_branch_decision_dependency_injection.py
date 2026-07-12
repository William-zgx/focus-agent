from __future__ import annotations

from types import SimpleNamespace

from focus_agent.branch_decision.classifier import classify_topic_relation
from focus_agent.branch_decision.service_runtime import BranchDecisionServiceRuntimeMixin


class _Runtime(BranchDecisionServiceRuntimeMixin):
    def __init__(self, *, classifier=None) -> None:
        self.settings = SimpleNamespace()
        self.branch_service = SimpleNamespace(
            semantic_topic_relation_classifier=classifier
        )
        self.coordination_backend = None


def test_branch_decision_uses_explicit_classifier_dependency() -> None:
    classifier = object()

    assert _Runtime(classifier=classifier)._semantic_topic_relation_classifier() is classifier


def test_branch_decision_falls_back_to_canonical_classifier() -> None:
    assert _Runtime()._semantic_topic_relation_classifier() is classify_topic_relation
