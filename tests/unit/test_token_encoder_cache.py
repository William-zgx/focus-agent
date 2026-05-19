from __future__ import annotations

import sys
import types

import pytest

from focus_agent.core import context_token_counting as token_counting


class _FakeEncoding:
    def encode(self, text: str) -> list[str]:
        return text.split() or [text]


@pytest.fixture(autouse=True)
def _clear_tokenizer_caches():
    _clear_caches()
    yield
    _clear_caches()


def test_encoding_for_model_is_cached_below_tokenizer_resolver(monkeypatch):
    calls = {"encoding_for_model": 0}

    def encoding_for_model(_model: str) -> _FakeEncoding:
        calls["encoding_for_model"] += 1
        return _FakeEncoding()

    fake_tiktoken = types.SimpleNamespace(
        encoding_for_model=encoding_for_model,
        get_encoding=lambda _name: _FakeEncoding(),
    )
    monkeypatch.setitem(sys.modules, "tiktoken", fake_tiktoken)

    for _ in range(2):
        token_counting._resolve_tokenizer_detail.cache_clear()
        estimate = token_counting.estimate_text_token_count(
            "hello world",
            chars_per_token=4,
            tokenizer_id="gpt-test",
            tokenizer_first=True,
        )
        assert estimate.counting_backend == "tiktoken"

    assert calls["encoding_for_model"] == 1


def test_get_encoding_fallback_is_cached_after_model_lookup_fails(monkeypatch):
    calls = {"encoding_for_model": 0, "get_encoding": 0}

    def encoding_for_model(_model: str) -> _FakeEncoding:
        calls["encoding_for_model"] += 1
        raise KeyError("unknown model")

    def get_encoding(name: str) -> _FakeEncoding:
        calls["get_encoding"] += 1
        assert name == token_counting.DEFAULT_TOKENIZER_ID
        return _FakeEncoding()

    fake_tiktoken = types.SimpleNamespace(
        encoding_for_model=encoding_for_model,
        get_encoding=get_encoding,
    )
    monkeypatch.setitem(sys.modules, "tiktoken", fake_tiktoken)

    for _ in range(2):
        token_counting._resolve_tokenizer_detail.cache_clear()
        tokenizer, resolved_id = token_counting._resolve_tokenizer_detail("missing-model")
        assert tokenizer is not None
        assert resolved_id == token_counting.DEFAULT_TOKENIZER_ID

    assert calls["encoding_for_model"] == 2
    assert calls["get_encoding"] == 1


def _clear_caches() -> None:
    token_counting._resolve_tokenizer_detail.cache_clear()
    token_counting._tiktoken_encoding_for_model.cache_clear()
    token_counting._tiktoken_get_encoding.cache_clear()
