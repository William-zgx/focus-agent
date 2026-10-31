"""Lexical branch-intent detection for pre-turn branch recommendations.

The detector grades how strongly the incoming message asks for a branch:

* ``explicit`` – the user literally asks for a branch ("新建分支", "open a new branch").
* ``strong``   – an exploration verb qualified by branch/separate wording, or a clear
  topic switch at the start of the message.
* ``weak``     – a side question, an A-vs-B comparison or a "pause and debug" detour.
  These yield a lower-confidence, non-blocking recommendation.
* ``none``     – nothing branch-shaped; the semantic classifier may still run.

Ambiguous single words ("新建", "split", "fork", "深入", "展开" ...) never count on
their own: they must sit next to a branch or "separately" word. English is matched on
word boundaries so ``fork()`` or ``parallelize`` cannot trigger a branch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from focus_agent.core.governance import BranchDecisionAction
from focus_agent.services.branches.actions import has_negated_branch_action_request

STRENGTH_EXPLICIT = "explicit"
STRENGTH_STRONG = "strong"
STRENGTH_WEAK = "weak"
STRENGTH_NONE = "none"

_CONTINUE_HINTS_ZH = (
    "继续当前",
    "当前线程",
    "在这里",
    "在这个分支",
    "在当前分支",
    "不用分支",
    "不要分支",
    "别开分支",
)
_CONTINUE_HINTS_EN = (
    "continue here",
    "current thread",
    "same thread",
    "this thread",
    "no branch",
    "don't branch",
    "do not branch",
)

# Explicit "make a branch" commands. Chinese uses the compacted text.
_EXPLICIT_BRANCH_ZH_RE = re.compile(
    r"(新建|创建|建立|新开|另开|开|单独开|切到|切换到|切换|拉)(一个|个|一条|条)?"
    r"(新的|新|子|同级|平级|下级)?分支"
    r"|子分支|同级分支|平级分支|下级分支"
)
_EXPLICIT_BRANCH_EN_RE = re.compile(
    r"\b(?:new|separate|another|child|sibling|sub|parallel)[\s-]+branch(?:es)?\b"
    r"|\bsub-?branch\b"
    r"|\b(?:create|open|make|start|spin\s+up|fork|switch\s+to)\s+"
    r"(?:a\s+|an\s+|another\s+|the\s+)?(?:new\s+)?(?:child\s+|sibling\s+|separate\s+)?branch\b"
    r"|\bbranch\s+(?:off|out)\b"
    r"|\bfork\s+(?:this|it|off|the\s+(?:conversation|thread|chat))\b",
)
_SIBLING_WORDS_ZH = ("同级", "平级", "并行", "平行", "并列", "替代方案", "备选方案", "另一个方向")
_SIBLING_WORDS_EN_RE = re.compile(r"\b(?:sibling|parallel|alternatives?|same\s+level)\b")

# Ambiguous words that only count when a branch/separate word is nearby.
_BARE_EXPLORATION_ZH = (
    "深入",
    "展开",
    "细化",
    "深挖",
    "拆开",
    "拆分",
    "并行",
    "另开",
    "新开",
    "新建",
    "探索",
    "研究",
    "替代方案",
    "备选方案",
    "换个方向",
    "另一个方向",
)
_BARE_EXPLORATION_EN_RE = re.compile(
    r"\b(?:split|fork|parallel|alternatives?|explore|deep\s+dive|drill\s+down|deepen|"
    r"dig\s+into|spin\s+off|investigate|research)\b"
)
_BRANCH_CONTEXT_ZH = (
    "分支",
    "支线",
    "同级",
    "平级",
    "单独研究",
    "单独聊",
    "单独讨论",
    "单独看",
    "单独探索",
    "单独分析",
    "单独展开",
    "单独深入",
    "另起",
    "另开一个话题",
    "另开一个对话",
)
_BRANCH_CONTEXT_EN_RE = re.compile(
    r"\b(?:branch(?:es)?|separately|side\s+thread|separate\s+thread|own\s+thread)\b"
)
# Strong phrases that already combine "parallel" with an exploration verb.
_PARALLEL_EXPLORATION_ZH = ("并行探索", "并行研究", "并行评估", "平行探索")
_PARALLEL_EXPLORATION_EN_RE = re.compile(
    r"\b(?:explore|investigate|evaluate|research)\b[^.?!\n]{0,40}\bin\s+parallel\b"
)
# Code/git context: "split this function", "new git branch", "fork() call".
_CODE_CONTEXT_RE = re.compile(
    r"函数|方法|文件|代码|脚本|项目|模块|组件|接口|仓库|字符串"
    r"|\b(?:function|method|class|file|code|script|module|component|repo|string|git|"
    r"commit|pull\s+request|pr|merge\s+request)\b"
    r"|\(\)|`",
    flags=re.IGNORECASE,
)

# Topic drift. Unambiguous phrases count anywhere; generic ones ("新问题",
# "another question") only at the start of the message or right before a colon.
_TOPIC_DRIFT_ANYWHERE_ZH = (
    "换个主题",
    "换个话题",
    "换个问题",
    "另一个话题",
    "另一个主题",
    "另一个议题",
    "不相关领域",
    "不相关的问题",
    "先看另一个",
    "先聊另一个",
)
_TOPIC_DRIFT_ANYWHERE_EN = (
    "change topic",
    "change the topic",
    "switch topic",
    "switch topics",
    "new topic",
    "another topic",
    "different topic",
    "unrelated topic",
    "unrelated question",
    "different domain",
)
_TOPIC_DRIFT_POSITIONAL_ZH = (
    "另一个问题",
    "另外一个问题",
    "另一件事",
    "新的议题",
    "新议题",
    "新问题",
    "新的问题",
)
_TOPIC_DRIFT_POSITIONAL_EN = (
    "another question",
    "different question",
    "separate question",
    "separate issue",
    "look at another",
)
_LEADING_FILLER_RE = re.compile(
    r"^(?:(?:好的?|好吧|ok(?:ay)?|嗯|那么?|然后|还有|另外|我还有|我有|also|and|so|then|"
    r"now|i\s+have|here\s+is|here's)[\s，,。.!！]*)+",
    flags=re.IGNORECASE,
)
_POSITIONAL_FOLLOWER = "：:，,"

# Weak detour signals (item: recall). Matched on compacted Chinese / spaced English.
_SIDE_QUESTION_ZH_RE = re.compile(
    r"顺便问(?:一下|下|个|一句)?|顺带问(?:一下|下)?|顺带一提|另外问(?:一下|下|个)"
    r"|插(?:个|一个|一句)?题外话|题外话|插一句|岔开一下|跑个题|跑题一下|离题一下"
)
_SIDE_QUESTION_EN_RE = re.compile(
    r"\b(?:by\s+the\s+way|btw|side\s+question|off[\s-]topic|tangent(?:ially)?|"
    r"unrelated,?\s+but)\b"
)
_EN_QUESTION_RE = re.compile(
    r"\?|\b(?:what|how|why|which|when|where|who|is|are|does|do|can|could|should)\b"
)
_COMPARISON_ZH_RE = re.compile(
    r"(?:对比|比较|权衡)(?:一下|下)?.{1,40}?(?:和|与|跟|还是|vs|以及)"
    r"|.{1,30}还是.{1,30}(?:哪个|哪种|哪一个)(?:好|更好|更合适|合适)"
)
_COMPARISON_EN_RE = re.compile(
    r"\bcompare\b[^.?!\n]{1,80}?\b(?:vs\.?|versus|and|with|to|against)\b"
    r"|\b\w+\s+(?:vs\.?|versus)\s+\w+"
    r"|\bor\b[^.?!\n]{1,60}\bwhich\b|\bwhich\b[^.?!\n]{1,60}\bor\b"
)
_DETOUR_ZH_RE = re.compile(
    r"(?:先)?(?:暂停|停)(?:一下|下)?.{0,40}(?:排查|调试|debug|修复|修一下|处理|查一下|看一下)"
    r"|先(?:放一放|搁置一下|插(?:个|一个)(?:问题|事))"
)
_DETOUR_EN_RE = re.compile(
    r"\b(?:pause|hold\s+on|hold\s+that\s+thought|put\s+(?:this|that)\s+on\s+hold|"
    r"step\s+aside)\b[^.?!\n]{0,80}?\b(?:debug|investigate|look\s+into|fix|check|"
    r"troubleshoot)\b"
    r"|\b(?:quick\s+)?detour\b"
)


@dataclass(frozen=True, slots=True)
class BranchIntent:
    target: BranchDecisionAction
    source: str
    strength: str
    route: str
    matched: str | None = None


def detect_branch_intent(message: str, *, on_branch: bool) -> BranchIntent:
    """Classify the explicit (non-drift) branch intent of an incoming message."""
    raw = _normalize_space(message)
    compact = compact_text(message)
    continue_intent = BranchIntent(
        target=BranchDecisionAction.CONTINUE_CURRENT,
        source="continue_hint",
        strength=STRENGTH_EXPLICIT,
        route="continue_hint",
    )
    none = BranchIntent(
        target=BranchDecisionAction.CONTINUE_CURRENT,
        source="none",
        strength=STRENGTH_NONE,
        route="none",
    )
    if not compact:
        return none
    if has_negated_branch_action_request(message):
        return continue_intent
    if any(hint in compact for hint in _CONTINUE_HINTS_ZH) or _contains_en_phrase(
        raw, _CONTINUE_HINTS_EN
    ):
        return continue_intent
    has_code_context = bool(_CODE_CONTEXT_RE.search(raw))
    fork_target = _fork_target(raw, compact, on_branch=on_branch)
    explicit = _explicit_branch_match(raw, compact, has_code_context=has_code_context)
    if explicit is not None:
        return BranchIntent(
            target=fork_target,
            source="branch_hint",
            strength=STRENGTH_EXPLICIT,
            route="explicit_branch",
            matched=explicit,
        )
    if has_code_context:
        return none
    qualified = _qualified_exploration_match(raw, compact)
    if qualified is not None:
        return BranchIntent(
            target=fork_target,
            source="branch_hint",
            strength=STRENGTH_STRONG,
            route="qualified_exploration",
            matched=qualified,
        )
    return none


def topic_drift_match(message: str) -> str | None:
    """Return the matched topic-drift phrase, honoring position for generic phrases."""
    raw = _normalize_space(message)
    compact = compact_text(message)
    if not compact:
        return None
    for marker in _TOPIC_DRIFT_ANYWHERE_ZH:
        if marker in compact:
            return marker
    for marker in _TOPIC_DRIFT_ANYWHERE_EN:
        if _contains_en_phrase(raw, (marker,)):
            return marker
    stripped_compact = _LEADING_FILLER_RE.sub("", compact)
    for marker in _TOPIC_DRIFT_POSITIONAL_ZH:
        if stripped_compact.startswith(marker) or _followed_by_separator(compact, marker):
            return marker
    stripped_raw = _LEADING_FILLER_RE.sub("", raw).lower()
    for marker in _TOPIC_DRIFT_POSITIONAL_EN:
        pattern = _en_phrase_pattern(marker)
        if re.match(pattern, stripped_raw) or re.search(pattern + r"\s*[:：]", raw.lower()):
            return marker
    return None


def weak_detour_match(message: str) -> tuple[str, str] | None:
    """Return ``(route, matched)`` for side questions, comparisons and detours."""
    raw = _normalize_space(message)
    compact = compact_text(message)
    if not compact:
        return None
    side = _SIDE_QUESTION_ZH_RE.search(compact)
    if side:
        return "side_question", side.group(0)
    side_en = _SIDE_QUESTION_EN_RE.search(raw)
    if side_en and _EN_QUESTION_RE.search(raw[side_en.end() :]):
        return "side_question", side_en.group(0)
    detour = _DETOUR_ZH_RE.search(compact) or _DETOUR_EN_RE.search(raw)
    if detour:
        return "detour", detour.group(0)
    if _CODE_CONTEXT_RE.search(raw):
        return None
    comparison = _COMPARISON_ZH_RE.search(compact) or _COMPARISON_EN_RE.search(raw)
    if comparison:
        return "comparison", comparison.group(0)
    return None


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _normalize_space(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


def _en_phrase_pattern(phrase: str) -> str:
    words = [re.escape(word) for word in phrase.lower().split()]
    return r"(?<![a-z0-9_])" + r"\s+".join(words) + r"(?![a-z0-9_])"


def _contains_en_phrase(raw: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(_en_phrase_pattern(phrase), raw) for phrase in phrases)


def _followed_by_separator(compact: str, marker: str) -> bool:
    start = compact.find(marker)
    while start >= 0:
        end = start + len(marker)
        if end < len(compact) and compact[end] in _POSITIONAL_FOLLOWER:
            return True
        start = compact.find(marker, start + 1)
    return False


def _fork_target(raw: str, compact: str, *, on_branch: bool) -> BranchDecisionAction:
    if not on_branch:
        return BranchDecisionAction.FORK_CHILD_BRANCH
    if "子分支" in compact or "下级" in compact or re.search(r"\bchild\b|\bsub-?branch", raw):
        return BranchDecisionAction.FORK_CHILD_BRANCH
    if any(word in compact for word in _SIBLING_WORDS_ZH) or _SIBLING_WORDS_EN_RE.search(raw):
        return BranchDecisionAction.FORK_SIBLING_BRANCH
    return BranchDecisionAction.FORK_CHILD_BRANCH


def _explicit_branch_match(raw: str, compact: str, *, has_code_context: bool) -> str | None:
    zh_match = _EXPLICIT_BRANCH_ZH_RE.search(compact)
    if zh_match and not re.search(r"git|代码分支|if分支|else分支", compact):
        return zh_match.group(0)
    if has_code_context:
        return None
    en_match = _EXPLICIT_BRANCH_EN_RE.search(raw)
    if en_match:
        return en_match.group(0)
    return None


def _qualified_exploration_match(raw: str, compact: str) -> str | None:
    for phrase in _PARALLEL_EXPLORATION_ZH:
        if phrase in compact:
            return phrase
    en_parallel = _PARALLEL_EXPLORATION_EN_RE.search(raw)
    if en_parallel:
        return en_parallel.group(0)
    for word in _BARE_EXPLORATION_ZH:
        index = compact.find(word)
        while index >= 0:
            window = compact[max(0, index - 12) : index + len(word) + 12]
            if any(context in window for context in _BRANCH_CONTEXT_ZH):
                return word
            index = compact.find(word, index + 1)
    for match in _BARE_EXPLORATION_EN_RE.finditer(raw):
        window = raw[max(0, match.start() - 48) : match.end() + 48]
        if _BRANCH_CONTEXT_EN_RE.search(window):
            return match.group(0)
    return None


__all__ = [
    "STRENGTH_EXPLICIT",
    "STRENGTH_NONE",
    "STRENGTH_STRONG",
    "STRENGTH_WEAK",
    "BranchIntent",
    "compact_text",
    "detect_branch_intent",
    "topic_drift_match",
    "weak_detour_match",
]
