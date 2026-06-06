from __future__ import annotations

import re
from collections.abc import Iterable

TEXTUAL_TOOL_ARTIFACT_MARKERS = (
    "function_calls",
    "invoke name=",
    "<｜dsml｜",
    "<tool_c",
    "</tool_c",
    "<tool_call",
    "<tool_calls",
    "<tool_req",
    "<toolreq",
    "</tool_call",
    "</tool_calls",
    "</tool_req",
    "</toolreq",
    "<invoke=",
    "</invoke>",
    "tool-observation://",
    "tool-result://",
    '"tool_name"',
)

DEFAULT_TEXTUAL_TOOL_NAMES = frozenset(
    {
        "artifact_list",
        "artifact_read",
        "apply_patch",
        "codebase_stats",
        "conversation_summary",
        "current_utc_time",
        "git_diff",
        "git_log",
        "git_status",
        "list_files",
        "read_file",
        "run_shell_command",
        "runshell_command",
        "run_workspace_command",
        "search_code",
        "skills_list",
        "skill_view",
        "web_fetch",
        "web_search",
        "write_text_artifact",
    }
)

_BRACKET_TOOL_MARKER_RE = re.compile(r"(?m)^\s*\[([A-Za-z_][\w.-]*)\]\s*")
_DSML_TOKEN_RE = re.compile(r"(?is)<\s*/?\s*(?:[|｜]\s*){1,2}dsml\s*(?:[|｜]\s*){1,2}")
_BARE_DSML_TOKEN_RE = re.compile(r"(?is)(?:^|[\s</])(?:[|｜]\s*){1,2}dsml\s*(?:[|｜]\s*){1,2}")
_DSML_TOOL_MARKUP_RE = re.compile(
    r"(?is)(?:^|[\n\r<|｜/])\s*(?:[-*•·]\s*)*/?<?\s*"
    r"(?:invoke\s+name(?:\b|[A-Za-z0-9_\"'=])[^<>\n]{0,160}|"
    r"parameter\s+name(?:\b|[A-Za-z0-9_\"'=])[^<>\n]{0,240}|"
    r"tool_?calls\s*(?:>|/))"
)
_XMLISH_TOOL_CALL_RE = re.compile(
    r"(?is)<\s*/?\s*tool_?c(?:alls?)?\s*>|"
    r"<\s*/?\s*tool_?req(?:uest)?(?:\s+name\b|\s*=|>)|"
    r"<\s*/?\s*invoke(?:\s*=|\s+name\b|>)|"
    r"<\s*/?\s*arg(?:\s+name\b|\s*=|>)|"
    r"<\s*/?\s*parameter(?:[\w.-]+|\s+name\b|\s*=|>)|"
    r"(?:^|[\s<])/?<?function\s*=\s*[a-z_][\w.-]*\s*>|"
    r"(?:^|[\n\r<|｜/])\s*(?:[-*•·]\s*)*/?<?invoke\s+name(?:\b|[A-Za-z0-9_\"'=])[^<>\n]{0,160}|"
    r"<\s*/?\s*parameter\s*=|"
    r"<[^>\n]{0,120}\bparameter\s+name\s*=|"
    r"(?:^|[\s<])/?<?parameter\s*=\s*[\w.-]+\s*>"
)
_DEGRADED_TOOL_PROTOCOL_FRAGMENT_RE = re.compile(
    r"(?is)(?:^|[\n\r])\s*"
    r"(?:"
    r"(?:alls?|calls?|tool_?calls?|tool_?req(?:uest)?|arg|invoke|parameter)>|"
    r"(?:https?://[^\s<>\"']{1,240}|[0-9]{1,8}|[a-z_][\w.-]{0,80})\s*(?:arg|parameter|invoke)>|"
    r"=\s*[\"']?[a-z_][\w.-]*\s*=\s*[\"']?[a-z_][\w.-]*[\"']?\s+"
    r"(?:string|number|boolean|object|array)\s*=?|"
    r"=\s*[\"']?(?:web_[a-z_]+|[a-z_]*(?:chars?|url|query|count|fresh_days|format|limit|length|path|filepath|read|max_results)[\w.-]*)[\"']?"
    r"(?:\s*=|\s+string\s*=?|\s+string(?:true|false)|[\"']\s*(?:string|true|false|>|[0-9])|>)|"
    r"=\s*[\"'][^\"'\n]{1,160}[\"']\s*(?:>|string\s*=)|"
    r"</?\s*(?:invoke|tool_?c|tool_?calls?|tool_?req(?:uest)?|arg|parameter)\s*>"
    r")"
)
_TOOL_RESULT_URI_RE = re.compile(
    r"(?is)\b(?:tool[-_](?:observation|result|call|calls)|toolcall|observation)://[^\s<>\"']+"
)
_DEGRADED_PARAMETER_TAIL_RE = re.compile(
    r"(?is)(?:^|[\n\r])\s*=\s*[\"']?[\w.-]{1,80}"
    r"(?:=\s*[\"']?[\w.-]{1,80})?[\"']?\s+"
    r"(?:string|number|boolean|object|array)\s*=?\s*[\"']?(?:true|false)?[\"']?\s*>"
    r"|(?:^|[\n\r])\s*=\s*[\"']?[\w.-]{1,80}(?:=\s*[\"']?[\w.-]{1,80})?[\"']?"
    r"\s*(?:true|false|null|[0-9]{1,8})?\s*>"
    r"|(?:^|[\n\r])\s*=\s*[\"']?[\w.-]{1,80}(?:=\s*[\"']?[\w.-]{1,80})?[\"']?"
    r"\s*(?:string|number|boolean|object|array)?\s*(?:true|false|null)?[0-9]{0,8}\s*"
    r"(?:arg|parameter|invoke)>"
)
_DEGRADED_TOOL_REFERENCE_RE = re.compile(
    r"(?is)(?:^|[\s,;])"
    r"(?:[\w./-]+/)?[\w.-]+\.(?:py|ts|tsx|js|jsx|md|toml|json|yaml|yml)"
    r"(?:"
    r"\s*=\s*[\"']?(?:offset|line|lines|line_number|path|uri|read|filepath)[\"']?"
    r"\s+(?:string|number|boolean|object|array)\w*"
    r"|(?:true|false|null)?[\"']?>[0-9]{1,8}(?:alls?>?)?"
    r")"
)
_TOOL_CALL_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:"
    r"https?://[^\s<>\"']{1,512}|"
    r"=|=\s*[\"']?|=\s*[\"']?[a-z_][\w.-]*\s*=|"
    r"=\s*[\"']?[a-z_][\w.-]*[\"']?(?:\s*=\s*[\"']?[a-z_][\w.-]*[\"']?)?"
    r"(?:\s*(?:t|tr|tru|true|f|fa|fal|fals|false|n|nu|null|[0-9]{1,8})?)?|"
    r"<|</|</<|"
    r"<\s*/?\s*(?:t|to|too|tool|tool_|tool_?c|tool_?ca|tool_?cal|tool_?call|tool_?calls?)|"
    r"<\s*/?\s*(?:t|to|too|tool|tool_|tool_?r|tool_?re|tool_?req|tool_?requ|tool_?reque|tool_?reques|tool_?request)(?:\s+n(?:a(?:m(?:e)?)?)?)?|"
    r"<\s*/?\s*(?:i|in|inv|invo|invok|invoke)(?:\s*=)?|"
    r"<\s*/?\s*(?:a|ar|arg)(?:\s+n(?:a(?:m(?:e)?)?)?|\s*=)?|"
    r"<\s*/?\s*(?:p|pa|par|para|param|parame|paramet|paramete|parameter)(?:[\w.-]*|\s*=)?|"
    r"<\s*/?\s*(?:[|｜]\s*){0,2}(?:d|ds|dsm|dsml)?\s*(?:[|｜]\s*){0,2}|"
    r"f|fu|fun|func|funct|functi|functio|function(?:\s*=\s*[\w.-]*)?|"
    r"i|in|inv|invo|invok|invoke(?:\s+n(?:a(?:m(?:e)?)?)?)?|"
    r"p|pa|par|para|param|parame|paramet|paramete|parameter(?:\s*=\s*[\w.-]*)?|"
    r"t|to|too|tool|tool_?c|tool_?ca|tool_?cal|tool_?call|tool_?calls/?"
    r")$"
)
_INTERNAL_PROCESS_NARRATION_RE = re.compile(
    r"(?ims)(?:^|[\n。；;:：,，])\s*"
    r"(?:我(?:来|先)?(?:帮你|为你)?(?:查询|获取|搜索|查找)|"
    r"先(?:获取|查询|搜索|抓取)|让我(?:先|再)?(?:尝试|查询|搜索|获取|访问|抓取)|"
    r"让我(?:先|再|进一步)?(?:查询|搜索|获取|访问|抓取)|"
    r"现在让我|接下来我(?:会|将)?尝试|我(?:会|将|再)?尝试(?:通过)?)"
    r"(?=.{0,160}(?:搜索|查询|访问|获取|抓取|页面|来源|资料|信息|内容|数据|行情|日线|东方财富|数据源|"
    r"web_fetch|web_search|tool|fetch|search|browse|计算))"
)
_INTERNAL_SEARCH_RESULT_NARRATION_RE = re.compile(
    r"(?ims)(?:我已经|我已)(?:从|在).{0,12}搜索结果.{0,80}(?:获取|拿到|掌握|整理)"
)
_INTERNAL_CONTINUATION_LOOP_RE = re.compile(
    r"(?ims)(?=.{0,260}(?:获取|查询|搜索|执行|处理|分析|计划|数据|网页|页面|行情))"
    r"(?:如果(?:你)?(?:没有|无)(?:进一步|额外|其他|特别|新的?)?(?:指示|要求|需求|回复)|"
    r"如无(?:其他|额外|特别|新的?)?(?:要求|指示)|"
    r"当前(?:继续|正在)(?:执行|处理|获取|分析)|"
    r"我将(?:默认)?继续(?:执行|推进|处理)|"
    r"请确认是否继续|如果没有回复|请稍候|正在(?:获取|查询|处理|分析)(?:数据)?)"
)
_INTERNAL_TOOL_DELIBERATION_RE = re.compile(
    r"(?ims)(?=.{0,360}(?:web[_\s-]?search|web[_\s-]?fetch|工具|tool|搜索结果))"
    r"(?:"
    r"我(?:因为|之前|刚才).{0,180}(?:搜索结果|重复调用|工具|web[_\s-]?search|web[_\s-]?fetch)|"
    r"我(?:现在|直接|将|会|需要|必须|要).{0,120}(?:执行|调用).{0,120}"
    r"(?:web[_\s-]?search|web[_\s-]?fetch|工具|tool|搜索|抓取|获取)|"
    r"(?:这是不对的|不应该这样|不再重复调用).{0,180}"
    r"(?:执行|调用|工具|web[_\s-]?search|web[_\s-]?fetch)|"
    r"现在我(?:直接)?执行\s*[:：]|"
    r"(?:搜索结果).{0,120}(?:犹豫|重复调用|不满意)"
    r")"
)
_INTERNAL_TOOL_DELIBERATION_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:"
    r"我|我因|我因为|我之|我之前|我刚|我刚才|"
    r"现在我|现在我直|现在我直接|现在我直接执|现在我直接执行|"
    r"这是|这是不|这是不对|这是不对的|"
    r"不再|不再重复|搜索结果|搜|搜索"
    r")$"
)
_INTERNAL_TOOL_REFERENCE_FRAGMENT_RE = re.compile(
    r"(?is)^\s*(?:和|与|及|、|,|，)?\s*web[_\s-]?(?:search|fetch)\s*[。.,，;；]?\s*$"
)


def _normalized_tool_names(known_tool_names: Iterable[str] | None = None) -> set[str]:
    names = set(DEFAULT_TEXTUAL_TOOL_NAMES)
    if known_tool_names is not None:
        names.update(str(name).strip().lower() for name in known_tool_names if str(name).strip())
    return names


def looks_like_textual_tool_call_artifact(
    text: object,
    *,
    known_tool_names: Iterable[str] | None = None,
) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if any(marker in lowered for marker in TEXTUAL_TOOL_ARTIFACT_MARKERS):
        return True
    if (
        _DSML_TOKEN_RE.search(lowered)
        or _BARE_DSML_TOKEN_RE.search(lowered)
        or _DSML_TOOL_MARKUP_RE.search(lowered)
    ):
        return True
    if _XMLISH_TOOL_CALL_RE.search(lowered):
        return True
    if _DEGRADED_TOOL_PROTOCOL_FRAGMENT_RE.search(lowered):
        return True
    if (
        _DEGRADED_PARAMETER_TAIL_RE.search(lowered)
        or _DEGRADED_TOOL_REFERENCE_RE.search(lowered)
        or _TOOL_RESULT_URI_RE.search(lowered)
    ):
        return True

    tool_names = _normalized_tool_names(known_tool_names)
    if any(
        match.group(1).lower() in tool_names for match in _BRACKET_TOOL_MARKER_RE.finditer(lowered)
    ):
        return True

    return bool(
        _INTERNAL_PROCESS_NARRATION_RE.search(lowered)
        or _INTERNAL_SEARCH_RESULT_NARRATION_RE.search(lowered)
        or _INTERNAL_CONTINUATION_LOOP_RE.search(lowered)
        or _INTERNAL_TOOL_DELIBERATION_RE.search(lowered)
        or _INTERNAL_TOOL_REFERENCE_FRAGMENT_RE.search(lowered)
    )


def looks_like_potential_textual_tool_call_prefix(text: object) -> bool:
    candidate = str(text or "").strip()
    if not candidate or len(candidate) > 512:
        return False
    return bool(
        _TOOL_CALL_PREFIX_RE.match(candidate)
        or _INTERNAL_TOOL_DELIBERATION_PREFIX_RE.match(candidate)
    )


def safe_visible_text_transition(
    current_text: str,
    value: object,
    *,
    pending_text: str = "",
) -> tuple[str, str]:
    delta = value if isinstance(value, str) else ""
    if not delta:
        return current_text, pending_text

    candidate_pending = f"{pending_text}{delta}"
    candidate_visible = f"{current_text}{candidate_pending}"
    if looks_like_textual_tool_call_artifact(
        candidate_pending
    ) or looks_like_textual_tool_call_artifact(candidate_visible):
        current_looks_internal = looks_like_textual_tool_call_artifact(
            current_text
        ) or looks_like_potential_textual_tool_call_prefix(current_text)
        return ("" if current_looks_internal else current_text), ""

    if looks_like_potential_textual_tool_call_prefix(candidate_pending):
        return current_text, candidate_pending

    safe_delta = (
        "" if looks_like_textual_tool_call_artifact(candidate_pending) else candidate_pending
    )
    return current_text + safe_delta, ""
