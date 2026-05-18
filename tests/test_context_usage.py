from __future__ import annotations

import pytest
from langchain.messages import HumanMessage

from focus_agent.context_usage import build_context_usage
from focus_agent.core import context_token_counting
from focus_agent.core.types import ContextBudget


def test_context_usage_reports_tokenizer_fallback_and_drift_risk(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_tiktoken(_name: str):
        raise ImportError("tiktoken unavailable")

    context_token_counting._resolve_tokenizer_detail.cache_clear()
    monkeypatch.setattr(context_token_counting.importlib, "import_module", missing_tiktoken)

    usage = build_context_usage(
        {
            "messages": [HumanMessage(content="Keep the Postgres migration path.")],
            "context_budget": ContextBudget(
                prompt_token_limit=1000,
                token_budget_mode="tokenizer_first",
                tokenizer_id="fake-model",
            ),
            "context_compaction": {
                "context_compaction_drift_report": {
                    "overall_drift": 0.5,
                }
            },
        }
    )

    payload = usage.to_dict()

    assert payload["counting_backend"] == "chars_fallback"
    assert payload["tokenizer_id"] == "fake-model"
    assert payload["estimated"] is True
    assert payload["drift_risk"] == "high"
