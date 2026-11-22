from __future__ import annotations

from focus_agent.memory.models import MemoryStatus


def parent_guard(db, params):
    row = db.memories.get(str(params["memory_id"]))
    if (
        row
        and row["status"] != MemoryStatus.FORGOTTEN.value
        and row["deleted_at"] is None
        and str(params["memory_id"]) not in db.tombstones
    ):
        return {
            "fingerprint": row["fingerprint"],
            "status": row["status"],
            "deleted_at": row["deleted_at"],
            "tombstoned": False,
        }
    return None


def memory_record_row(db, params):
    row = db.memories.get(str(params[0]))
    return {"data_json": row["data_json"], "updated_at": row["updated_at"]} if row else None


def existing_memory_row(db, params):
    matches = [
        row
        for row in db.memories.values()
        if row["namespace"] == params["namespace"]
        and row["status"] != MemoryStatus.FORGOTTEN.value
        and row["deleted_at"] is None
        and (
            row["fingerprint"] == params["fingerprint"]
            or row["semantic_key"] == params["semantic_key"]
        )
        and (not params.get("kind") or row["kind"] == params["kind"])
        and (not params.get("scope") or row["scope"] == params["scope"])
    ]
    matches.sort(key=lambda row: row["updated_at"], reverse=True)
    if not matches:
        return None
    return {"data_json": matches[0]["data_json"], "updated_at": matches[0]["updated_at"]}
