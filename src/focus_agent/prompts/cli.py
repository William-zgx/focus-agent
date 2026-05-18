from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import get_registry


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="focus-agent-prompts")
    parser.add_argument("--library-dir", help="Override prompt library directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List prompt ids and versions.")
    diff_parser = subparsers.add_parser("diff", help="Diff two prompt versions.")
    diff_parser.add_argument("prompt_id")
    diff_parser.add_argument("old_version")
    diff_parser.add_argument("new_version")
    args = parser.parse_args(argv)

    registry = get_registry(args.library_dir)
    if args.command == "list":
        for prompt in registry.list():
            description = f" - {prompt.description}" if prompt.description else ""
            print(f"{prompt.id}@{prompt.version}{description}")
        return 0
    if args.command == "diff":
        print(registry.diff(args.prompt_id, args.old_version, args.new_version), end="")
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
