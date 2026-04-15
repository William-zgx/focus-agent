from __future__ import annotations

import argparse
import json

from .core.branching import BranchRole, MergeDecision
from .core.request_context import RequestContext
from .config import load_local_env_document
from .engine.runtime import create_runtime


load_local_env_document()


def cmd_run(args) -> None:
    runtime = create_runtime()
    try:
        from .chat_service import ChatService

        service = ChatService(runtime)
        payload = service.send_message(thread_id=args.thread_id, user_id=args.user_id, message=args.message)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        runtime.close()


def cmd_resume(args) -> None:
    runtime = create_runtime()
    try:
        from .chat_service import ChatService

        service = ChatService(runtime)
        payload = service.resume(thread_id=args.thread_id, user_id=args.user_id, resume=args.resume)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        runtime.close()


def cmd_fork(args) -> None:
    runtime = create_runtime()
    try:
        record = runtime.branch_service.fork_branch(
            parent_thread_id=args.parent_thread_id,
            user_id=args.user_id,
            branch_name=args.branch_name,
            name_source=args.name_source,
            branch_role=BranchRole(args.branch_role),
        )
        print(record.model_dump_json(indent=2))
    finally:
        runtime.close()


def cmd_propose_merge(args) -> None:
    runtime = create_runtime()
    try:
        proposal = runtime.branch_service.prepare_merge_proposal(
            child_thread_id=args.child_thread_id,
            user_id=args.user_id,
        )
        print(proposal.model_dump_json(indent=2))
    finally:
        runtime.close()


def cmd_apply_merge(args) -> None:
    runtime = create_runtime()
    try:
        decision = MergeDecision(
            approved=args.approved,
            mode=args.mode,
            rationale=args.rationale,
            selected_artifacts=args.selected_artifacts or [],
        )
        record = runtime.repo.get_by_child_thread_id(args.child_thread_id)
        context = RequestContext(user_id=args.user_id, root_thread_id=args.root_thread_id or record.root_thread_id)
        imported = runtime.branch_service.apply_merge_decision(
            child_thread_id=args.child_thread_id,
            decision=decision,
            context=context,
        )
        print(imported.model_dump_json(indent=2) if imported else "null")
    finally:
        runtime.close()


def cmd_branch_tree(args) -> None:
    runtime = create_runtime()
    try:
        tree = runtime.branch_service.get_branch_tree(root_thread_id=args.root_thread_id)
        print(tree.model_dump_json(indent=2))
    finally:
        runtime.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Focus Agent demo CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--thread-id", required=True)
    run.add_argument("--user-id", required=True)
    run.add_argument("--message", required=True)
    run.set_defaults(func=cmd_run)

    resume = sub.add_parser("resume")
    resume.add_argument("--thread-id", required=True)
    resume.add_argument("--user-id", required=True)
    resume.add_argument("--resume", required=True)
    resume.set_defaults(func=cmd_resume)

    fork = sub.add_parser("fork")
    fork.add_argument("--parent-thread-id", required=True)
    fork.add_argument("--user-id", required=True)
    fork.add_argument("--branch-name")
    fork.add_argument("--name-source")
    fork.add_argument(
        "--branch-role",
        default=BranchRole.EXPLORE_ALTERNATIVES.value,
        choices=[role.value for role in BranchRole],
    )
    fork.set_defaults(func=cmd_fork)

    propose = sub.add_parser("propose-merge")
    propose.add_argument("--child-thread-id", required=True)
    propose.add_argument("--user-id", required=True)
    propose.set_defaults(func=cmd_propose_merge)

    apply_merge = sub.add_parser("apply-merge")
    apply_merge.add_argument("--child-thread-id", required=True)
    apply_merge.add_argument("--root-thread-id")
    apply_merge.add_argument("--user-id", required=True)
    apply_merge.add_argument("--approved", action="store_true")
    apply_merge.add_argument(
        "--mode",
        default="summary_only",
        choices=["none", "summary_only", "summary_plus_evidence", "selected_artifacts"],
    )
    apply_merge.add_argument("--rationale")
    apply_merge.add_argument("--selected-artifacts", nargs="*")
    apply_merge.set_defaults(func=cmd_apply_merge)

    tree = sub.add_parser("branch-tree")
    tree.add_argument("--root-thread-id", required=True)
    tree.set_defaults(func=cmd_branch_tree)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
