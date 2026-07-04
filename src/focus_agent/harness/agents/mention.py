"""@mention parsing utilities for harness messages.

The UI allows users to address a specific agent (e.g. ``@coder fix this``).
This module exposes small helpers that parse @mentions out of a user message,
extract the primary (first / best matching) agent reference, and produce a
"clean" message with the @token stripped for LLM consumption while preserving
the original for display.

Design notes:
- Mentions look like ``@<name>`` where ``<name>`` is made of word characters,
  hyphens, and underscores.
- Matching against the registry is case-insensitive and also checks display
  aliases registered on agent manifests (when present).
- All functions are pure / side-effect free so they can be used at the API
  boundary before the message reaches the graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# A mention is an @ token followed by a word-ish identifier.
_MENTION_RE = re.compile(r"@([A-Za-z0-9_\-]+)")


@dataclass(frozen=True, slots=True)
class Mention:
    """A single @mention parsed from a message."""

    name: str
    # Character offsets within the original text (start of the '@', end after name).
    start: int
    end: int
    # Whether the registry resolved this mention to a known agent.
    resolved: bool = False
    # Canonical agent id, if resolved.
    agent_id: str | None = None


def parse_mentions(text: str) -> list[Mention]:
    """Return all ``@name`` mentions in ``text`` in source order.

    The returned mentions are not yet resolved against an agent registry.
    """
    if not text:
        return []
    mentions: list[Mention] = []
    for match in _MENTION_RE.finditer(text):
        mentions.append(
            Mention(
                name=match.group(1),
                start=match.start(),
                end=match.end(),
            )
        )
    return mentions


def _registry_entries(registry: Any) -> list[tuple[str, frozenset[str]]]:
    """Normalize an agent/tool registry to a list of (id, aliases) pairs.

    Supports registries exposing any of the following shapes:

    - ``registry.by_name`` -> dict[str, AgentDescriptor] with optional
      ``aliases`` / ``display_name`` attributes.
    - ``registry.list_visible()`` -> iterable of agent-like objects with
      ``name``/``id`` and optional aliases.
    - ``registry.agents`` / ``registry.list_agents()`` / ``registry.manifests``
      as fallbacks.

    The returned aliases are lowercased for case-insensitive matching.
    """
    entries: list[tuple[str, frozenset[str]]] = []

    def _add(agent_id: str, aliases: Iterable[str] = ()) -> None:
        cleaned = {str(agent_id).lower()}
        for alias in aliases:
            if not alias:
                continue
            cleaned.add(str(alias).lower())
        entries.append((str(agent_id), frozenset(cleaned)))

    def _from_obj(obj: Any, default_id: str | None = None) -> None:
        agent_id = (
            getattr(obj, "name", None)
            or getattr(obj, "id", None)
            or getattr(obj, "agent_id", None)
            or default_id
        )
        if not agent_id:
            return
        aliases: list[str] = []
        for attr in ("aliases", "display_name", "display_aliases", "nicknames"):
            value = getattr(obj, attr, None)
            if isinstance(value, str):
                aliases.append(value)
            elif isinstance(value, (list, tuple, set, frozenset)):
                aliases.extend(str(v) for v in value if v)
        if isinstance(obj, dict):
            for key in ("name", "id", "agent_id"):
                if key in obj and obj[key]:
                    agent_id = obj[key]
            for key in ("aliases", "display_name", "display_aliases", "nicknames"):
                value = obj.get(key)
                if isinstance(value, str):
                    aliases.append(value)
                elif isinstance(value, (list, tuple, set)):
                    aliases.extend(str(v) for v in value if v)
        _add(str(agent_id), aliases)

    # Try the most common shapes.
    by_name = getattr(registry, "by_name", None)
    if isinstance(by_name, dict):
        for name, obj in by_name.items():
            _from_obj(obj, default_id=str(name))
        if entries:
            return entries

    for method_name in ("list_visible", "list_agents", "agents", "manifests"):
        attr = getattr(registry, method_name, None)
        if callable(attr):
            try:
                iterable = attr()
            except TypeError:
                iterable = attr
        else:
            iterable = attr
        if isinstance(iterable, (list, tuple, set, frozenset)) or (
            hasattr(iterable, "__iter__") and not isinstance(iterable, (str, bytes, dict))
        ):
            for obj in iterable:
                _from_obj(obj)
            if entries:
                return entries
    return entries


def resolve_mentions(text: str, registry: Any | None) -> list[Mention]:
    """Parse mentions and resolve them against ``registry``.

    Unknown mentions are still returned (``resolved=False``) so the caller can
    surface autocomplete suggestions / warnings if desired.
    """
    mentions = parse_mentions(text)
    if not mentions or registry is None:
        return mentions
    entries = _registry_entries(registry)
    if not entries:
        return mentions
    lookup: dict[str, str] = {}
    for agent_id, aliases in entries:
        for alias in aliases:
            lookup[alias] = agent_id
    resolved: list[Mention] = []
    for m in mentions:
        agent_id = lookup.get(m.name.lower())
        if agent_id is not None:
            resolved.append(
                Mention(
                    name=m.name,
                    start=m.start,
                    end=m.end,
                    resolved=True,
                    agent_id=agent_id,
                )
            )
        else:
            resolved.append(m)
    return resolved


def extract_primary_agent(
    text: str,
    registry: Any | None = None,
) -> tuple[str | None, str]:
    """Extract the primary addressed agent and a cleaned message.

    Returns ``(agent_id, clean_message)`` where ``clean_message`` has the
    primary @mention token removed. The primary agent is the first *resolved*
    mention in source order; if no mention resolves we fall back to the first
    @token verbatim (so callers can still honor explicit routing even without a
    populated registry). If no mentions are present ``agent_id`` is ``None``
    and ``clean_message`` equals the input.

    The clean message collapses repeated whitespace introduced by stripping
    the @token and trims surrounding whitespace.
    """
    mentions = resolve_mentions(text, registry) if registry is not None else parse_mentions(text)
    if not mentions:
        return None, text
    primary = mentions[0]
    for m in mentions:
        if m.resolved:
            primary = m
            break
    start, end = primary.start, primary.end
    clean = text[:start] + text[end:]
    # Collapse runs of whitespace that result from stripping the token.
    clean = re.sub(r"[ \t]+", " ", clean).strip()
    agent_id = primary.agent_id or primary.name
    return agent_id, clean


def strip_mentions(text: str) -> str:
    """Strip **all** @mention tokens from ``text``.

    Useful when the caller wants a mention-free payload but does not care
    about routing.
    """
    mentions = parse_mentions(text)
    if not mentions:
        return text
    pieces: list[str] = []
    cursor = 0
    for m in mentions:
        pieces.append(text[cursor : m.start])
        cursor = m.end
    pieces.append(text[cursor:])
    return re.sub(r"[ \t]+", " ", "".join(pieces)).strip()


def list_available_agents(registry: Any | None) -> list[dict[str, Any]]:
    """Return a JSON-serializable list of agents exposed by ``registry``.

    This is the shape the frontend consumes for @mention autocomplete:
    ``[{"id": "...", "name": "...", "description": "..."}]``.
    """
    if registry is None:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent_id, aliases in _registry_entries(registry):
        if agent_id in seen:
            continue
        seen.add(agent_id)
        out.append(
            {
                "id": agent_id,
                "name": agent_id,
                "aliases": sorted(a for a in aliases if a != agent_id.lower()),
            }
        )
    return out


__all__ = [
    "Mention",
    "extract_primary_agent",
    "list_available_agents",
    "parse_mentions",
    "resolve_mentions",
    "strip_mentions",
]
