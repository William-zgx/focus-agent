"""Per-turn record of retrieval calls already made in the current turn."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from focus_agent.engine.tools.messages import iter_tool_results, tool_message_failed

from ...core.tool_call_protocol import messages_since_latest_human

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


def collect_retrieval_ledger(messages: list[Any]) -> dict[str, RetrievalLedgerEntry]:
    """Retrieval calls since the latest human message, keyed by identity."""
    ledger: dict[str, RetrievalLedgerEntry] = {}
    for message, tool_name, args in iter_tool_results(
        messages_since_latest_human(list(messages or []))
    ):
        call_id = str(getattr(message, "tool_call_id", "") or "")
        key = retrieval_key(tool_name, args)
        if key is None:
            continue
        error = ""
        if tool_message_failed(message):
            # Transient failures may succeed on retry; only remember fetches that
            # will fail the same way again.
            text = str(message.content or "")
            if tool_name != "web_fetch" or not _PERMANENT_FETCH_FAILURE.search(text):
                continue
            error = " ".join(text.split())[:160]
        previous = ledger.get(key)
        if previous is None or (previous.error and not error):
            ledger[key] = RetrievalLedgerEntry(
                tool_name=tool_name,
                tool_call_id=call_id,
                error=error,
            )
    return ledger
