from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Protocol, Sequence

from .repositories.postgres_trajectory_repository import PostgresTrajectoryRepository


class TrajectoryReadRepository(Protocol):
    def list_turns(
        self,
        *,
        filters: dict[str, Any],
        limit: int,
        offset: int,
    ) -> Iterable[Any]:
        ...

    def get_turn(self, turn_id: str) -> Any:
        ...

    def export_turns(
        self,
        *,
        filters: dict[str, Any],
        limit: int | None,
        offset: int,
    ) -> Iterable[Any]:
        ...

    def stats(self, *, filters: dict[str, Any]) -> Any:
        ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="focus-agent-trajectory",
        description="Inspect persisted trajectory observability records.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--database-uri",
        help="PostgreSQL connection string. Defaults to the DATABASE_URI environment variable.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list",
        help="List trajectory turns as JSON.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_common_filters(list_parser)
    list_parser.add_argument("--limit", type=_non_negative_int, default=50)
    list_parser.add_argument("--offset", type=_non_negative_int, default=0)

    show_parser = subparsers.add_parser(
        "show",
        help="Show a single trajectory turn as JSON.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    show_parser.add_argument("turn_id", help="Trajectory turn id.")

    export_parser = subparsers.add_parser(
        "export",
        help="Export trajectory turns as JSONL.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_common_filters(export_parser)
    export_parser.add_argument("--limit", type=_non_negative_int)
    export_parser.add_argument("--offset", type=_non_negative_int, default=0)
    export_parser.add_argument(
        "--output",
        "-o",
        help="Write JSONL to this path instead of stdout.",
    )

    stats_parser = subparsers.add_parser(
        "stats",
        help="Show aggregate trajectory stats as JSON.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_common_filters(stats_parser)

    return parser


def _add_common_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--thread-id")
    parser.add_argument("--root-thread-id")
    parser.add_argument(
        "--status",
        action="append",
        help="Repeatable filter for turn status.",
    )
    parser.add_argument(
        "--scene",
        action="append",
        help="Repeatable filter for scene names.",
    )
    parser.add_argument(
        "--branch-role",
        action="append",
        help="Repeatable filter for branch roles.",
    )
    parser.add_argument(
        "--tool",
        action="append",
        help="Repeatable filter for tool names observed in trajectory steps.",
    )
    parser.add_argument(
        "--model",
        action="append",
        help="Repeatable filter for selected model values.",
    )
    parser.add_argument("--started-after", help="Inclusive ISO-8601 lower bound for started_at.")
    parser.add_argument("--started-before", help="Exclusive ISO-8601 upper bound for started_at.")
    parser.add_argument(
        "--fallback-used",
        action="store_true",
        help="Only include turns with at least one fallback tool call.",
    )
    parser.add_argument(
        "--cache-hit",
        action="store_true",
        help="Only include turns with at least one cache hit.",
    )
    parser.add_argument(
        "--has-error",
        action="store_true",
        help="Only include turns with a turn-level or step-level error.",
    )


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def create_repository(database_uri: str) -> TrajectoryReadRepository:
    return PostgresTrajectoryRepository(database_uri)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    database_uri = _resolve_database_uri(args, parser)
    repo = create_repository(database_uri)

    try:
        if args.command == "list":
            return _run_list(repo, args)
        if args.command == "show":
            return _run_show(repo, args)
        if args.command == "export":
            return _run_export(repo, args)
        if args.command == "stats":
            return _run_stats(repo, args)
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    parser.error(f"unsupported command: {args.command}")
    return 2


def _resolve_database_uri(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    database_uri = args.database_uri or os.environ.get("DATABASE_URI")
    if database_uri:
        return database_uri
    parser.error("DATABASE_URI is required. Pass --database-uri or export DATABASE_URI.")
    return ""


def _run_list(repo: TrajectoryReadRepository, args: argparse.Namespace) -> int:
    filters = _build_filters(args)
    method = _require_repo_method(repo, "list_turns")
    items = [_json_ready(item) for item in method(filters=filters, limit=args.limit, offset=args.offset)]
    _print_json(
        {
            "items": items,
            "count": len(items),
            "filters": filters,
            "limit": args.limit,
            "offset": args.offset,
        }
    )
    return 0


def _run_show(repo: TrajectoryReadRepository, args: argparse.Namespace) -> int:
    method = _require_repo_method(repo, "get_turn")
    _print_json({"item": _json_ready(method(args.turn_id))})
    return 0


def _run_export(repo: TrajectoryReadRepository, args: argparse.Namespace) -> int:
    filters = _build_filters(args)
    method = _require_repo_method(repo, "export_turns")
    records = method(filters=filters, limit=args.limit, offset=args.offset)
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            _write_jsonl(records, handle)
        return 0

    _write_jsonl(records, sys.stdout)
    return 0


def _run_stats(repo: TrajectoryReadRepository, args: argparse.Namespace) -> int:
    filters = _build_filters(args)
    method = _require_repo_method(repo, "stats")
    _print_json({"filters": filters, "stats": _json_ready(method(filters=filters))})
    return 0


def _require_repo_method(repo: TrajectoryReadRepository, name: str) -> Any:
    method = getattr(repo, name, None)
    if callable(method):
        return method
    raise RuntimeError(f"trajectory repository does not implement '{name}'")


def _build_filters(args: argparse.Namespace) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if getattr(args, "thread_id", None):
        filters["thread_id"] = args.thread_id
    if getattr(args, "root_thread_id", None):
        filters["root_thread_id"] = args.root_thread_id
    if getattr(args, "status", None):
        filters["status"] = list(args.status)
    if getattr(args, "scene", None):
        filters["scene"] = list(args.scene)
    if getattr(args, "branch_role", None):
        filters["branch_role"] = list(args.branch_role)
    if getattr(args, "tool", None):
        filters["tool"] = list(args.tool)
    if getattr(args, "model", None):
        filters["selected_model"] = list(args.model)
    if getattr(args, "started_after", None):
        filters["started_after"] = args.started_after
    if getattr(args, "started_before", None):
        filters["started_before"] = args.started_before
    if getattr(args, "fallback_used", False):
        filters["fallback_used"] = True
    if getattr(args, "cache_hit", False):
        filters["cache_hit"] = True
    if getattr(args, "has_error", False):
        filters["has_error"] = True
    return filters


def _write_jsonl(records: Iterable[Any], handle: Any) -> None:
    for record in records:
        handle.write(json.dumps(_json_ready(record), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _print_json(payload: Any) -> None:
    print(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2, sort_keys=True))


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    if is_dataclass(value):
        return _json_ready(asdict(value))
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
