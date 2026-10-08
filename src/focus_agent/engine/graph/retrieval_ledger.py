"""Per-turn record of web retrieval that already succeeded.

Repeating an identical search, page fetch, or artifact page read in a later
round only re-adds the same observation to the context. The ledger lets the
tool executor suppress those repeats and tells the model what it has already
retrieved so it moves on to unread sources or answers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from langchain.messages import AIMessage, ToolMessage

from ..graph_tool_history_repair import _messages_since_latest_human, _tool_message_is_failure

_LEDGER_NOTE_MAX_ENTRIES = 20
# Fetch failures that will not change on retry within the same turn.
_PERMANENT_FETCH_FAILURE = re.compile(
    r"\b(?:401|403|404|410)\b|forbidden|not found|blocked by access policy|"
    r"access challenge|not readable text",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RetrievalLedgerEntry:
    tool_name: str
    tool_call_id: str
    label: str
    error: str = ""


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _normalize_url(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    path = parts.path.rstrip("/") if parts.path not in {"", "/"} else ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _domains(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list | tuple):
        return []
    return sorted({_normalize_text(item) for item in value if _normalize_text(item)})


def retrieval_key(tool_name: str, args: Mapping[str, Any] | None) -> str | None:
    """Identity of a retrieval call; None for tools the ledger does not track."""
    args = args if isinstance(args, Mapping) else {}
    if tool_name == "web_search":
        identity: dict[str, Any] = {
            "query": _normalize_text(args.get("query")),
            "time_range": _normalize_text(args.get("time_range")),
            "include_domains": _domains(args.get("include_domains")),
            "exclude_domains": _domains(args.get("exclude_domains")),
        }
    elif tool_name == "web_fetch":
        identity = {"url": _normalize_url(args.get("url")), "max_chars": args.get("max_chars")}
    elif tool_name == "artifact_read":
        identity = {
            "artifact_id": str(args.get("artifact_id") or "").strip(),
            "offset": args.get("offset"),
            "limit": args.get("limit"),
            "query": _normalize_text(args.get("query")),
        }
    else:
        return None
    return f"{tool_name}:{json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str)}"


def _label(tool_name: str, args: Mapping[str, Any]) -> str:
    if tool_name == "web_search":
        label = f'web_search "{" ".join(str(args.get("query") or "").split())}"'
        if args.get("time_range"):
            label += f" (time_range={args['time_range']})"
        return label
    if tool_name == "web_fetch":
        return f"web_fetch {str(args.get('url') or '').strip()}"
    label = f"artifact_read {str(args.get('artifact_id') or '').strip()}"
    if args.get("query"):
        return f'{label} query="{args["query"]}"'
    return f"{label} offset={args.get('offset') or 0}"


def _payload(message: ToolMessage) -> Mapping[str, Any]:
    try:
        payload = json.loads(str(message.content or ""))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _published_at(message: ToolMessage) -> str:
    return str(_payload(message).get("published_at") or "").strip()[:10]


def _artifact_ref(message: ToolMessage) -> str:
    return str(_payload(message).get("artifact_ref") or "").strip()


def collect_retrieval_ledger(messages: list[Any]) -> dict[str, RetrievalLedgerEntry]:
    """Successful retrieval calls since the latest human message, keyed by identity."""
    calls: dict[str, tuple[str, Mapping[str, Any]]] = {}
    ledger: dict[str, RetrievalLedgerEntry] = {}
    # Publication date per fetched page (and its saved full text), so the note can
    # show that paging deeper into an out-of-window page is not worth a round.
    published_by_ref: dict[str, str] = {}
    for message in _messages_since_latest_human(list(messages or [])):
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or ():
                if not isinstance(call, Mapping):
                    continue
                call_id = str(call.get("id") or "").strip()
                args = call.get("args")
                if call_id:
                    calls[call_id] = (
                        str(call.get("name") or "").strip(),
                        args if isinstance(args, Mapping) else {},
                    )
            continue
        if not isinstance(message, ToolMessage):
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        if call_id not in calls:
            continue
        tool_name, args = calls[call_id]
        key = retrieval_key(tool_name, args)
        if key is None:
            continue
        error = ""
        if _tool_message_is_failure(message):
            # Transient failures (timeouts, 5xx) may succeed on retry; only remember
            # fetches that will fail the same way again.
            text = str(message.content or "")
            if tool_name != "web_fetch" or not _PERMANENT_FETCH_FAILURE.search(text):
                continue
            error = " ".join(text.split())[:160]
        label = _label(tool_name, args)
        if tool_name == "web_fetch" and not error:
            published = _published_at(message)
            if published:
                label += f" [published {published}]"
                for ref in (str(args.get("url") or ""), _artifact_ref(message)):
                    if ref:
                        published_by_ref[ref] = published
        elif tool_name == "artifact_read":
            published = published_by_ref.get(str(args.get("artifact_id") or ""))
            if published:
                label += f" [page published {published}]"
        previous = ledger.get(key)
        if previous is None or (previous.error and not error):
            ledger[key] = RetrievalLedgerEntry(
                tool_name=tool_name,
                tool_call_id=call_id,
                label=label,
                error=error,
            )
    return ledger


def retrieval_ledger_note(ledger: Mapping[str, RetrievalLedgerEntry]) -> str:
    if not ledger:
        return ""
    entries = list(ledger.values())
    lines = [
        f"- {entry.label}" + (" (failed permanently; do not retry)" if entry.error else "")
        for entry in entries[-_LEDGER_NOTE_MAX_ENTRIES:]
    ]
    if len(entries) > _LEDGER_NOTE_MAX_ENTRIES:
        lines.insert(0, f"- ... {len(entries) - _LEDGER_NOTE_MAX_ENTRIES} earlier calls")
    return (
        "Already retrieved in this turn (identical repeats are rejected; their results "
        "are above):\n"
        + "\n".join(lines)
        + "\nDo not repeat these. Read a source you have not read yet, search a genuinely "
        "different angle, or answer from the evidence collected. Do not keep paging through "
        "a page whose publication date falls outside the requested time window."
    )
