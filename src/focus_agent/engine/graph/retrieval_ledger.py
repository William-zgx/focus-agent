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

from langchain.messages import ToolMessage

from ...core.tool_call_protocol import messages_since_latest_human
from ..graph_tool_messages import (
    artifact_source_refs,
    iter_tool_results,
    payload_published_at,
    prompt_observation_json,
    tool_message_failed,
    tool_message_json,
)

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
    payload = tool_message_json(message)
    return payload if isinstance(payload, Mapping) else {}


def _published_at(message: ToolMessage) -> str:
    return str(payload_published_at(_payload(message)) or "")[:10]


def collect_retrieval_ledger(messages: list[Any]) -> dict[str, RetrievalLedgerEntry]:
    """Successful retrieval calls since the latest human message, keyed by identity."""
    ledger: dict[str, RetrievalLedgerEntry] = {}
    # Publication date per fetched page (and its saved full text), so the note can
    # show that paging deeper into an out-of-window page is not worth a round.
    published_by_ref: dict[str, str] = {}
    for message, tool_name, args in iter_tool_results(
        messages_since_latest_human(list(messages or []))
    ):
        call_id = str(getattr(message, "tool_call_id", "") or "")
        key = retrieval_key(tool_name, args)
        if key is None:
            continue
        error = ""
        if tool_message_failed(message):
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
                for ref in artifact_source_refs(
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    payload=_payload(message),
                    prompt_payload=prompt_observation_json(message),
                ):
                    published_by_ref[ref] = published
                if args.get("url"):
                    published_by_ref[str(args["url"])] = published
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
