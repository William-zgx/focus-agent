from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from .graph_evidence import relevant_web_tool_call_ids
from .graph_tool_history_repair import _message_text


def _truncate_inline(value: Any, *, max_chars: int = 180) -> str:
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


def _latest_human_message_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def _latest_turn_messages(messages: list[Any]) -> list[Any]:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def _fallback_web_answer_from_tool_results(prompt_messages: list[Any]) -> str:
    latest_turn = _latest_turn_messages(prompt_messages)
    latest_user = _latest_human_message_text(latest_turn)
    payloads = _latest_relevant_web_payloads(latest_turn, latest_user)
    if not payloads:
        return ""
    chinese = bool(re.search(r"[\u4e00-\u9fff]", latest_user))
    main = _web_payload_main_answer(payloads, user_query=latest_user, chinese=chinese)
    if not main:
        return ""
    sources = _web_payload_sources(payloads)
    fetched_pages = _fetched_page_payloads(payloads)
    if chinese:
        answer = f"{'根据已抓取页面' if fetched_pages else '根据搜索结果'}，{main}"
        if sources:
            answer += "\n\n来源：\n" + "\n".join(f"- {source}" for source in sources[:4])
        return answer
    answer = (
        f"{'Based on fetched pages' if fetched_pages else 'Based on the search results'}, {main}"
    )
    if sources:
        answer += "\n\nSources:\n" + "\n".join(f"- {source}" for source in sources[:4])
    return answer


def _latest_relevant_web_payloads(latest_turn: list[Any], latest_user: str) -> list[dict[str, Any]]:
    relevant_web_call_ids = relevant_web_tool_call_ids(latest_turn, user_query=latest_user)
    pending_calls: dict[str, str] = {}
    payloads: list[dict[str, Any]] = []
    for message in latest_turn:
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or []:
                if not isinstance(call, dict):
                    continue
                call_id = str(call.get("id") or "")
                if call_id:
                    pending_calls[call_id] = str(call.get("name") or "")
            continue
        if not isinstance(message, ToolMessage):
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        tool_name = pending_calls.get(call_id, "")
        if relevant_web_call_ids is not None and call_id not in relevant_web_call_ids:
            continue
        parsed_payloads = []
        raw = _message_text(message)
        try:
            parsed_payloads.append(json.loads(raw))
        except json.JSONDecodeError:
            pass
        prompt_payload = _prompt_observation_payload(message)
        if prompt_payload is not None:
            parsed_payloads.append(prompt_payload)
        for payload in parsed_payloads:
            if not isinstance(payload, dict):
                continue
            if tool_name in {"web_search", "web_fetch"} or _looks_like_live_web_fallback_payload(
                payload
            ):
                payloads.append(payload)
    return payloads


def _looks_like_live_web_fallback_payload(payload: dict[str, Any]) -> bool:
    if payload.get("tool") in {"web_search", "web_fetch"}:
        return True
    if payload.get("provider") in {"tavily", "web", "search"}:
        return True
    if payload.get("url") or payload.get("final_url"):
        return True
    for result in _payload_results(payload):
        if result.get("url") or result.get("ref"):
            return True
    refs = payload.get("refs")
    return isinstance(refs, list) and any(str(ref).strip().startswith("http") for ref in refs)


def _web_payload_main_answer(
    payloads: list[dict[str, Any]],
    *,
    user_query: str,
    chinese: bool,
) -> str:
    weather_query = _looks_like_weather_query(user_query, payloads)
    if weather_query and chinese:
        weather = _chinese_weather_summary_from_payloads(payloads)
        if weather:
            return weather
    fetched_page_summary = _fetched_page_summary(_fetched_page_payloads(payloads), chinese=chinese)
    if fetched_page_summary:
        return fetched_page_summary
    for payload in payloads:
        answer = str(payload.get("answer") or "").strip()
        if answer:
            return _truncate_inline(answer, max_chars=420)
        summary = str(payload.get("summary") or "").strip()
        if summary and not _looks_like_internal_web_summary(summary):
            return _truncate_inline(summary, max_chars=420)
    for payload in payloads:
        result_text = _first_result_text(payload, prefer_chinese=chinese)
        if result_text:
            return _truncate_inline(result_text, max_chars=420)
    for payload in payloads:
        query = str(payload.get("query") or "").strip()
        if query:
            return f"查询：{_truncate_inline(query, max_chars=160)}"
    return ""


def _looks_like_internal_web_summary(value: str) -> bool:
    normalized = " ".join(str(value or "").lower().split())
    return bool(
        normalized
        and (
            "compressed into" in normalized
            or "artifact-like prompt reference" in normalized
            or "prompt reference" in normalized
        )
    )


def _fetched_page_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        payload
        for payload in payloads
        if str(payload.get("final_url") or "").strip()
        or (
            str(payload.get("url") or "").strip()
            and "content" in payload
            and not isinstance(payload.get("results"), list)
        )
    ]


def _fetched_page_summary(payloads: list[dict[str, Any]], *, chinese: bool) -> str:
    if not payloads:
        return ""
    lines: list[str] = []
    for payload in payloads[:3]:
        title = str(payload.get("title") or "").strip()
        url = str(payload.get("final_url") or payload.get("url") or "").strip()
        label = title or url or "抓取页面"
        excerpt = _representative_fetch_excerpt(str(payload.get("content") or ""))
        if excerpt:
            if chinese:
                lines.append(f"{label} 的可用正文摘录：{excerpt}")
            else:
                lines.append(f"Usable excerpt from {label}: {excerpt}")
            continue
        if chinese:
            lines.append(f"{label} 已抓取，但提取文本未包含可安全复述的正文。")
        else:
            lines.append(f"{label} was fetched, but the extracted text lacks a safe body excerpt.")
    return "\n".join(lines)


def _representative_fetch_excerpt(content: str) -> str:
    text = " ".join(str(content or "").split())
    if not text:
        return ""
    lowered = text.lower()
    for keyword in (
        "experimental support",
        "free-threaded",
        "temporary redirect",
        "must not",
        "must use",
        "same request method",
        "same method",
    ):
        index = lowered.find(keyword)
        if index < 0:
            continue
        start = max(
            0,
            max(text.rfind(marker, 0, index) for marker in (".", "。", "¶")) + 1,
        )
        return _truncate_inline(text[start : index + 360], max_chars=420)
    return ""


def _looks_like_weather_query(user_query: str, payloads: list[dict[str, Any]]) -> bool:
    text = " ".join(
        [
            user_query,
            *[str(payload.get("query") or "") for payload in payloads],
        ]
    ).lower()
    return bool(
        _contains_weather_marker(text) or re.search(r"\b(?:weather|forecast|temperature)\b", text)
    )


def _contains_weather_marker(text: str) -> bool:
    return any(marker in text for marker in ("天气", "气温", "预报", "降雨", "下雨"))


def _chinese_weather_summary_from_payloads(payloads: list[dict[str, Any]]) -> str:
    for payload in payloads:
        for result in _payload_results(payload):
            content = str(result.get("content") or result.get("snippet") or "").strip()
            if not content or not re.search(r"[\u4e00-\u9fff]", content):
                continue
            if not (_contains_weather_marker(content) or "最高气温" in content):
                continue
            concise = _extract_concise_weather_text(content)
            if concise:
                return concise
    return ""


def _extract_concise_weather_text(content: str) -> str:
    text = " ".join(content.split())
    match = re.search(
        r"今天白天[:：].{0,80}?最高气温\d+℃；今天夜间[:：].{0,80}?最低气温\d+℃[。.]?",
        text,
    )
    if match:
        return match.group(0).rstrip("。.") + "。"
    match = re.search(r"(?:今天|今日).{0,160}?(?:最高气温\d+℃|最低气温\d+℃).{0,80}?[。.]", text)
    if match:
        return match.group(0)
    return _truncate_inline(text, max_chars=260)


def _first_result_text(payload: dict[str, Any], *, prefer_chinese: bool) -> str:
    fallback = ""
    for result in _payload_results(payload):
        content = str(result.get("content") or result.get("snippet") or "").strip()
        title = str(result.get("title") or "").strip()
        text = " ".join(part for part in (title, content) if part)
        if not text:
            continue
        if prefer_chinese and re.search(r"[\u4e00-\u9fff]", text):
            return text
        if not fallback:
            fallback = text
    return fallback


def _web_payload_sources(payloads: list[dict[str, Any]]) -> list[str]:
    sources: list[str] = []
    fetched_pages = _fetched_page_payloads(payloads)
    source_payloads = fetched_pages or payloads
    for payload in source_payloads:
        title = _truncate_inline(str(payload.get("title") or "").strip(), max_chars=80)
        url = str(payload.get("final_url") or payload.get("url") or "").strip()
        domain = _source_domain(url)
        if title and domain and url:
            sources.append(f"{title}（{domain}）: {url}")
        elif url:
            sources.append(url)
        elif title:
            sources.append(title)
    for payload in source_payloads:
        reference = str(payload.get("reference") or "").strip()
        if reference:
            sources.extend(_reference_sources(reference))
        refs = payload.get("refs")
        if isinstance(refs, list):
            sources.extend(str(ref).strip() for ref in refs if str(ref).strip())
        for result in _payload_results(payload):
            title = _truncate_inline(str(result.get("title") or "").strip(), max_chars=80)
            url = str(result.get("url") or result.get("ref") or "").strip()
            if not title and not url:
                continue
            domain = _source_domain(url)
            if title and domain and url:
                sources.append(f"{title}（{domain}）: {url}")
            else:
                sources.append(title or url)
    return list(dict.fromkeys(sources))


def _reference_sources(reference: str) -> list[str]:
    text = reference.strip()
    if text.lower().startswith("refs="):
        text = text[5:]
    return [item.strip() for item in re.split(r"[,\\s]+", text) if item.strip()]


def _payload_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [result for result in results if isinstance(result, dict)]


def _source_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return parsed.netloc or parsed.path.split("/", 1)[0]


def _looks_like_web_observation_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("tool") in {"web_search", "web_fetch"}:
        return True
    if isinstance(payload.get("results"), list) and (
        payload.get("provider") or payload.get("query")
    ):
        return True
    return bool(payload.get("url") or payload.get("final_url")) and (
        "content" in payload or "text" in payload or "summary" in payload
    )


def _prompt_observation_payload(message: ToolMessage) -> Any | None:
    artifact = getattr(message, "artifact", None)
    if not isinstance(artifact, dict):
        return None
    prompt_observation = artifact.get("prompt_observation")
    if not isinstance(prompt_observation, str) or not prompt_observation.strip():
        return None
    try:
        return json.loads(prompt_observation)
    except json.JSONDecodeError:
        return None


__all__ = [
    "_fallback_web_answer_from_tool_results",
    "_latest_relevant_web_payloads",
    "_looks_like_live_web_fallback_payload",
    "_web_payload_main_answer",
    "_looks_like_internal_web_summary",
    "_fetched_page_payloads",
    "_fetched_page_summary",
    "_representative_fetch_excerpt",
    "_looks_like_weather_query",
    "_contains_weather_marker",
    "_chinese_weather_summary_from_payloads",
    "_extract_concise_weather_text",
    "_first_result_text",
    "_web_payload_sources",
    "_reference_sources",
    "_payload_results",
    "_source_domain",
    "_looks_like_web_observation_payload",
    "_prompt_observation_payload",
]
