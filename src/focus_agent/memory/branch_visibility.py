"""Which branch-originated memories a thread may see in its prompt.

Unreviewed branch work stays inside that branch (and its descendants, which
inherit its context). Other threads only see it once it was promoted through a
reviewed merge (``promoted_to_main``).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any


def visible_branch_ids(*, branch_id: str | None, state: Mapping[str, Any] | None) -> frozenset[str]:
    ids: set[str] = set()
    branch_meta = (state or {}).get("branch_meta")
    if isinstance(branch_meta, Mapping):
        ids.update(str(item) for item in branch_meta.get("ancestor_branch_ids") or [] if item)
        if branch_meta.get("branch_id"):
            ids.add(str(branch_meta["branch_id"]))
    if branch_id:
        ids.add(str(branch_id))
    return frozenset(ids)


def branch_origin_visible(record: Any, visible_ids: Collection[str]) -> bool:
    source = getattr(record, "source_branch_id", None)
    if not source or bool(getattr(record, "promoted_to_main", False)):
        return True
    return str(source) in visible_ids


__all__ = ["branch_origin_visible", "visible_branch_ids"]
