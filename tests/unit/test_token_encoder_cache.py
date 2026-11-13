from __future__ import annotations

import sys
import types

import pytest

from focus_agent.core import context_token_counting as token_counting


class _FakeEncoding:
    def __init__(self):
        self.encoded_texts: list[str] = []

    def encode(self, text: str) -> list[str]:
        self.encoded_texts.append(text)
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


def test_known_model_estimate_encodes_once_and_reports_metadata(monkeypatch):
    encoding = _FakeEncoding()
    model_lookups = []

    def encoding_for_model(model: str) -> _FakeEncoding:
        model_lookups.append(model)
        return encoding

    fake_tiktoken = types.SimpleNamespace(
        encoding_for_model=encoding_for_model,
        get_encoding=lambda name: pytest.fail(f"unexpected fallback lookup: {name}"),
    )
    monkeypatch.setitem(sys.modules, "tiktoken", fake_tiktoken)

    estimate = token_counting.estimate_text_token_count(
        "hello world",
        chars_per_token=4,
        tokenizer_id="gpt-test",
        tokenizer_first=True,
    )

    assert estimate == token_counting.TokenCountEstimate(
        tokens=2,
        counting_backend="tiktoken",
        tokenizer_id="gpt-test",
        estimated=False,
    )
    assert encoding.encoded_texts == ["hello world"]
    assert model_lookups == ["gpt-test"]


def test_unknown_model_estimate_uses_fallback_once_and_reports_resolved_id(monkeypatch):
    encoding = _FakeEncoding()
    lookups = []

    def encoding_for_model(model: str) -> _FakeEncoding:
        lookups.append(("model", model))
        raise KeyError("unknown model")

    def get_encoding(name: str) -> _FakeEncoding:
        lookups.append(("encoding", name))
        return encoding

    fake_tiktoken = types.SimpleNamespace(
        encoding_for_model=encoding_for_model,
        get_encoding=get_encoding,
    )
    monkeypatch.setitem(sys.modules, "tiktoken", fake_tiktoken)

    estimate = token_counting.estimate_text_token_count(
        "hello world",
        chars_per_token=1,
        tokenizer_id="missing-model",
        tokenizer_first=True,
    )

    assert estimate == token_counting.TokenCountEstimate(
        tokens=2,
        counting_backend="tiktoken",
        tokenizer_id=token_counting.DEFAULT_TOKENIZER_ID,
        estimated=False,
    )
    assert encoding.encoded_texts == ["hello world"]
    assert lookups == [
        ("model", "missing-model"),
        ("encoding", token_counting.DEFAULT_TOKENIZER_ID),
    ]


def test_missing_tiktoken_estimate_uses_character_fallback(monkeypatch):
    imports = []

    def missing_tiktoken(name: str):
        imports.append(name)
        raise ImportError("tiktoken unavailable")

    monkeypatch.setattr(token_counting.importlib, "import_module", missing_tiktoken)

    estimate = token_counting.estimate_text_token_count(
        "hello world",
        chars_per_token=5,
        tokenizer_id="missing-model",
        tokenizer_first=True,
    )

    assert estimate == token_counting.TokenCountEstimate(
        tokens=3,
        counting_backend="chars_fallback",
        tokenizer_id="missing-model",
        estimated=True,
    )
    assert imports == ["tiktoken"]


def test_empty_text_estimate_skips_tokenizer_resolution(monkeypatch):
    def fail_import(name: str):
        pytest.fail(f"unexpected import for empty text: {name}")

    monkeypatch.setattr(token_counting.importlib, "import_module", fail_import)

    estimate = token_counting.estimate_text_token_count(
        "",
        chars_per_token=4,
        tokenizer_id="gpt-test",
        tokenizer_first=True,
    )

    assert estimate == token_counting.TokenCountEstimate(
        tokens=0,
        counting_backend="tiktoken",
        tokenizer_id="gpt-test",
        estimated=False,
    )


def _clear_caches() -> None:
    token_counting._resolve_tokenizer_detail.cache_clear()
    token_counting._tiktoken_encoding_for_model.cache_clear()
    token_counting._tiktoken_get_encoding.cache_clear()
