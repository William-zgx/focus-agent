from __future__ import annotations

import pytest

from focus_agent.memory.text import (
    has_correction_signal,
    memory_text_terms,
    normalize_memory_dedupe_text,
    normalize_memory_text,
)


def test_normalize_memory_text_casefolds_and_collapses_whitespace():
    assert normalize_memory_text("  Hello\tWORLD \n again ") == "hello world again"
    assert normalize_memory_text(None) == ""


def test_normalize_memory_dedupe_text_drops_punctuation_noise():
    assert normalize_memory_dedupe_text("Use: src/app.py, NOW!") == "use: src/app.py now"


def test_memory_text_terms_keeps_order_and_builds_cjk_bigrams():
    assert memory_text_terms("Zvec index 检索服务 ok a") == [
        "zvec",
        "index",
        "ok",
        "检索",
        "索服",
        "服务",
    ]
    assert memory_text_terms("中文") == ["中文"]
    assert memory_text_terms("api key value", min_latin_length=3) == ["api", "key", "value"]
    assert memory_text_terms("an api", min_latin_length=3) == ["api"]


@pytest.mark.parametrize(
    "text",
    [
        "更正：默认语言是英文",
        "以此为准",
        "以这个为准",
        "默认不是中文而是英文",
        "不再使用 A，改为 B",
        "From now on use English",
        "Use B instead",
    ],
)
def test_has_correction_signal_matches_known_phrasings(text: str):
    assert has_correction_signal(text) is True


@pytest.mark.parametrize("text", ["默认语言是英文", "不是很确定", "", None])
def test_has_correction_signal_ignores_plain_statements(text: str | None):
    assert has_correction_signal(text) is False
