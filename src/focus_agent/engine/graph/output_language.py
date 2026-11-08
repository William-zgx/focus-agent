from __future__ import annotations

from focus_agent.engine.graph.lexicon import CJK_RE


def _cjk_count(value: str) -> int:
    return len(CJK_RE.findall(value))


def _requires_chinese_output(user_text: str) -> bool:
    # A bare "chinese" would also match topics such as "Chinese New Year".
    return bool(_cjk_count(user_text)) or "in chinese" in user_text.lower()


__all__ = ["_requires_chinese_output"]
