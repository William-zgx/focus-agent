#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from focus_agent.engine.local_persistence import PersistentInMemorySaver, PersistentSQLiteSaver


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate focus-agent LangGraph checkpoints from pickle to SQLite."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source langgraph-checkpoints.pkl path.",
    )
    parser.add_argument(
        "--target",
        help="Target SQLite path. Defaults to the source path with a .sqlite3 suffix.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and count source checkpoints without writing SQLite state.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow writing to an existing non-empty SQLite checkpoint database.",
    )
    return parser.parse_args(argv)


def _target_has_checkpoint_rows(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'checkpoint_storage'
                """
            ).fetchone()
            if row is None:
                return False
            count = conn.execute("SELECT COUNT(*) FROM checkpoint_storage").fetchone()[0]
            return int(count) > 0
    except sqlite3.DatabaseError:
        return True


def _put_config_for_checkpoint_tuple(checkpoint_tuple: object) -> dict[str, object]:
    configurable = dict(checkpoint_tuple.config["configurable"])
    configurable.pop("checkpoint_id", None)
    parent_config = checkpoint_tuple.parent_config
    if parent_config:
        parent_checkpoint_id = parent_config["configurable"].get("checkpoint_id")
        if parent_checkpoint_id is not None:
            configurable["checkpoint_id"] = parent_checkpoint_id
    return {"configurable": configurable}


def migrate(source: Path, target: Path, *, dry_run: bool, force: bool) -> dict[str, object]:
    if not source.exists():
        raise FileNotFoundError(f"source checkpoint pickle does not exist: {source}")
    if not dry_run and not force and _target_has_checkpoint_rows(target):
        raise FileExistsError(
            f"target SQLite checkpoint database already has rows: {target}; use --force"
        )

    source_saver = PersistentInMemorySaver(source)
    target_saver: PersistentSQLiteSaver | None = None
    migrated_count = 0
    pending_write_count = 0
    try:
        tuples = list(source_saver.list(None))
        if not dry_run:
            target_saver = PersistentSQLiteSaver(target)
        for checkpoint_tuple in tuples:
            pending_write_count += len(checkpoint_tuple.pending_writes)
            if dry_run:
                continue
            saved_config = target_saver.put(
                _put_config_for_checkpoint_tuple(checkpoint_tuple),
                checkpoint_tuple.checkpoint,
                checkpoint_tuple.metadata,
                checkpoint_tuple.checkpoint.get("channel_versions", {}),
            )
            if checkpoint_tuple.pending_writes:
                by_task: dict[str, list[tuple[str, object]]] = {}
                for task_id, channel, value in checkpoint_tuple.pending_writes:
                    by_task.setdefault(str(task_id), []).append((str(channel), value))
                for task_id, writes in by_task.items():
                    target_saver.put_writes(saved_config, writes, task_id)
            migrated_count += 1
    finally:
        source_saver.close()
        if target_saver is not None:
            target_saver.close()

    return {
        "status": "dry-run" if dry_run else "completed",
        "source": str(source),
        "target": str(target),
        "source_checkpoint_count": len(tuples),
        "migrated_checkpoint_count": migrated_count,
        "pending_write_count": pending_write_count,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = Path(args.source).expanduser()
    target = Path(args.target).expanduser() if args.target else source.with_suffix(".sqlite3")
    try:
        report = migrate(source, target, dry_run=args.dry_run, force=args.force)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "failed", "reason": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
