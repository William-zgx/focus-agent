from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from .tool_execution_types import ToolExecutionInput


@dataclass(slots=True)
class ToolResultCacheStore:
    max_entries_per_scope: int = 1024
    turn: OrderedDict[str, str] = field(default_factory=OrderedDict)
    thread: OrderedDict[str, str] = field(default_factory=OrderedDict)
    branch: OrderedDict[str, str] = field(default_factory=OrderedDict)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def get(self, key: str) -> str | None:
        with self._lock:
            cache = self._cache_for_key(key)
            value = cache.get(key)
            if value is not None:
                cache.move_to_end(key)
            return value

    def set(self, key: str, value: str) -> None:
        with self._lock:
            cache = self._cache_for_key(key)
            cache[key] = value
            cache.move_to_end(key)
            self._trim_cache(cache)

    def invalidate_namespace(self, namespace: str | None) -> None:
        if not namespace:
            return
        with self._lock:
            cache = self._cache_for_namespace(namespace)
            prefix = f"{namespace}:"
            for key in list(cache):
                if key.startswith(prefix):
                    del cache[key]

    def _cache_for_key(self, key: str) -> dict[str, str]:
        return self._cache_for_scope(key.split(":", 1)[0])

    def _cache_for_namespace(self, namespace: str) -> dict[str, str]:
        return self._cache_for_scope(namespace.split(":", 1)[0])

    def _cache_for_scope(self, scope: str) -> dict[str, str]:
        normalized = scope.strip().lower()
        if normalized == "turn":
            return self.turn
        if normalized == "branch":
            return self.branch
        return self.thread

    def _trim_cache(self, cache: OrderedDict[str, str]) -> None:
        limit = max(1, int(self.max_entries_per_scope or 1))
        while len(cache) > limit:
            cache.popitem(last=False)


def build_cache_scope_key(
    *,
    scope: str,
    root_thread_id: str | None = None,
    branch_id: str | None = None,
    turn_id: str | None = None,
) -> str:
    normalized_scope = (scope or "thread").strip().lower()
    if normalized_scope == "branch" and branch_id:
        return f"branch:{branch_id}"
    if normalized_scope == "turn":
        return f"turn:{root_thread_id or branch_id or 'default'}:{turn_id or 'default'}"
    return f"thread:{root_thread_id or branch_id or 'default'}"


def cache_key(item: ToolExecutionInput, cache_scope_key: str | None) -> str | None:
    if not item.runtime.cacheable:
        return None
    scope_key = cache_scope_key or "thread:default"
    args_json = json.dumps(item.args, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{scope_key}|{item.tool_name}|{args_json}".encode()).hexdigest()
    return f"{scope_key}:{digest}"


def invalidate_after_side_effect(
    *,
    cache_store: ToolResultCacheStore | None,
    invalidation_scope_keys: list[str],
) -> None:
    if cache_store is None:
        return
    for scope_key in invalidation_scope_keys:
        cache_store.invalidate_namespace(scope_key)
