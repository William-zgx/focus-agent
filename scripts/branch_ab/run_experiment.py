"""Paired A/B experiment: linear thread vs. branch workflow on the same tasks.

Arm A (linear) sends main turns, detour turns and the return turn into one
thread. Arm B (branch) sends the detour turns into a child branch forked from
main, merges the approved conclusion back, then sends the return turn on main.
Only the answer to the return turn is scored (see ``score.py``).

Each (task, arm, repeat) runs in its own process with its own temporary state
directory, so runs cannot share memory, checkpoints or caches. Every model
call is captured with the exact messages it received.

Usage:
    .venv/bin/python scripts/branch_ab/run_experiment.py \
        --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
        --model deepseek:deepseek-v4-pro --repeats 3 --workers 6 \
        --out reports/branch_ab/deepseek
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
ARMS = ("linear", "branch")
_MERGE_MODES = {"summary_only", "summary_plus_evidence"}


def _isolated_env(state_dir: Path, model: str) -> dict[str, str]:
    """Settings that keep each run local, quiet and comparable across arms."""
    return {
        "FOCUS_AGENT_LOCAL_ENV_FILE": str(REPO_ROOT / ".focus_agent" / "local.env"),
        "FOCUS_AGENT_MODEL_CATALOG_DOC": str(REPO_ROOT / ".focus_agent" / "models.toml"),
        "FOCUS_AGENT_TOOL_CATALOG_DOC": str(REPO_ROOT / ".focus_agent" / "tools.toml"),
        "MODEL": model,
        "HELPER_MODEL": model,
        "DATABASE_URI": "",
        "FOCUS_AGENT_CHECKPOINT_BACKEND": "sqlite",
        "BRANCH_DB_PATH": str(state_dir / "branches.sqlite3"),
        "ARTIFACT_DIR": str(state_dir / "artifacts"),
        "LOCAL_CHECKPOINT_PATH": str(state_dir / "checkpoints.sqlite3"),
        "LOCAL_STORE_PATH": str(state_dir / "store.sqlite3"),
        "AGENT_ZVEC_DATA_DIR": str(state_dir / "zvec"),
        "AGENT_ZVEC_ENABLED": "false",
        "WORKSPACE_ROOT": str(state_dir / "workspace"),
        "FOCUS_AGENT_SANDBOX_BACKEND": "local",
        # Branch control must stay explicit in arm B and absent in arm A.
        "AGENT_BRANCH_RECOMMENDATION_ENABLED": "false",
        "AGENT_BRANCH_DECISION_ENABLED": "false",
        "AGENT_DELEGATION_ENABLED": "false",
        # External services that would add noise unrelated to the arms.
        "AGENT_MEMORY_EMBEDDING_ENABLED": "false",
        "TAVILY_API_KEY": "",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
    }


class _CapturingModel:
    """Wraps a chat model and records every invoke() input and output."""

    def __init__(self, model: Any, log: list[dict[str, Any]], *, model_id: str, source: str):
        self._model = model
        self._log = log
        self._model_id = model_id
        self._source = source

    def _record(self, payload: Any, result: Any, started: float, error: str | None) -> None:
        self._log.append(
            {
                "source": self._source,
                "model_id": self._model_id,
                "phase": _CURRENT_PHASE[0],
                "input": _serialize_messages(payload),
                "output": _serialize_message(result) if result is not None else None,
                "usage": _usage(result),
                "latency_s": round(time.monotonic() - started, 3),
                "error": error,
            }
        )

    def invoke(self, payload: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        try:
            result = self._model.invoke(payload, *args, **kwargs)
        except BaseException as exc:
            self._record(payload, None, started, f"{type(exc).__name__}: {exc}")
            raise
        self._record(payload, result, started, None)
        return result

    def bind_tools(self, *args: Any, **kwargs: Any) -> _CapturingModel:
        return _CapturingModel(
            self._model.bind_tools(*args, **kwargs),
            self._log,
            model_id=self._model_id,
            source=self._source,
        )

    def with_config(self, *args: Any, **kwargs: Any) -> _CapturingModel:
        return _CapturingModel(
            self._model.with_config(*args, **kwargs),
            self._log,
            model_id=self._model_id,
            source=self._source,
        )

    def with_structured_output(self, *args: Any, **kwargs: Any) -> Any:
        return _CapturingModel(
            self._model.with_structured_output(*args, **kwargs),
            self._log,
            model_id=self._model_id,
            source=self._source,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._model, name)


_CURRENT_PHASE = ["setup"]


def _serialize_message(message: Any) -> Any:
    if hasattr(message, "model_dump"):
        try:
            dumped = message.model_dump()
        except Exception:  # noqa: BLE001
            dumped = None
        if isinstance(dumped, dict):
            return {
                key: dumped.get(key)
                for key in ("type", "content", "tool_calls", "name", "additional_kwargs")
                if dumped.get(key) not in (None, [], {})
            } or dumped
    if isinstance(message, dict):
        return message
    return str(message)


def _serialize_messages(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_serialize_message(item) for item in payload]
    return _serialize_message(payload)


def _usage(result: Any) -> dict[str, int] | None:
    usage = getattr(result, "usage_metadata", None)
    if isinstance(usage, dict):
        return {
            key: int(usage.get(key) or 0)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
    return None


def _install_capture(log: list[dict[str, Any]]) -> None:
    import focus_agent.engine.graph.builder as graph_builder
    import focus_agent.engine.model_factory as model_factory
    import focus_agent.model_registry as model_registry
    import focus_agent.services.branches as branches_package

    original = model_registry.create_chat_model

    def factory_for(source: str):
        def create(model_id: str, *args: Any, **kwargs: Any) -> Any:
            return _CapturingModel(
                original(model_id, *args, **kwargs), log, model_id=model_id, source=source
            )

        return create

    graph_builder.create_chat_model = factory_for("agent")
    model_factory.create_chat_model = factory_for("agent")
    branches_package.create_chat_model = factory_for("branch_service")
    model_registry.create_chat_model = factory_for("other")


def _final_text(payload: dict[str, Any]) -> str:
    text = payload.get("assistant_message")
    if isinstance(text, str):
        return text
    if isinstance(text, dict):
        return str(text.get("content") or "")
    return str(text or "")


def _last_message_id(payload: dict[str, Any]) -> str | None:
    for message in reversed(payload.get("messages") or []):
        if isinstance(message, dict) and message.get("id"):
            return str(message["id"])
    return None


def run_one(task: dict[str, Any], arm: str, repeat: int, model: str, out_dir: str) -> dict:
    """Run one (task, arm, repeat) in this (fresh) process."""
    out_path = Path(out_dir) / f"{task['id']}__{arm}__r{repeat}.json"
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))
    state_dir = Path(tempfile.mkdtemp(prefix=f"branch-ab-{task['id']}-{arm}-"))
    (state_dir / "workspace").mkdir()
    os.environ.update(_isolated_env(state_dir, model))
    os.chdir(state_dir)
    sys.path.insert(0, str(REPO_ROOT / "src"))

    import logging

    log_path = out_path.with_suffix(".log")
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(handler)
    sys.stderr = open(log_path.with_suffix(".stderr"), "w", encoding="utf-8")  # noqa: SIM115

    calls: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    record: dict[str, Any] = {
        "task_id": task["id"],
        "category": task["category"],
        "language": task["language"],
        "arm": arm,
        "repeat": repeat,
        "model": model,
        "started_at": time.time(),
    }
    runtime = None
    try:
        _install_capture(calls)
        from focus_agent.config import Settings
        from focus_agent.core.branching import BranchRole, MergeDecision, MergeMode
        from focus_agent.core.request_context import RequestContext
        from focus_agent.engine.runtime import create_runtime
        from focus_agent.services.chat import ChatService

        settings = Settings.from_env()
        settings.web_search = replace(settings.web_search, enabled=False)
        runtime = create_runtime(settings)
        chat = ChatService(runtime)
        user_id = "branch-ab-user"
        main_thread = f"ab-{task['id']}-{arm}-r{repeat}-{uuid4().hex[:8]}"

        def settle(timeout_s: float = 180.0) -> None:
            # Real users pause between turns, so post-turn background work
            # (compaction, titles) finishes first. Wait for it in both arms.
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                snap = runtime.background_work.snapshot()
                if not snap["queue_depth"] and not snap["active_workers"]:
                    return
                time.sleep(0.2)

        def send(thread_id: str, phase: str, message: str) -> dict[str, Any]:
            settle()
            _CURRENT_PHASE[0] = phase
            started = time.monotonic()
            payload = chat.send_message(
                thread_id=thread_id, user_id=user_id, message=message, model=model
            )
            turns.append(
                {
                    "phase": phase,
                    "thread_id": thread_id,
                    "user": message,
                    "assistant": _final_text(payload),
                    "latency_s": round(time.monotonic() - started, 3),
                }
            )
            return payload

        for message in task["main_turns"]:
            last_main = send(main_thread, "main", message)

        if arm == "linear":
            for message in task["detour_turns"]:
                send(main_thread, "detour", message)
        else:
            settle()
            _CURRENT_PHASE[0] = "fork"
            branch = runtime.branch_service.fork_branch(
                parent_thread_id=main_thread,
                user_id=user_id,
                branch_name="side question",
                branch_role=BranchRole.DEEP_DIVE,
                fork_at_message_id=_last_message_id(last_main),
            )
            for message in task["detour_turns"]:
                send(branch.child_thread_id, "detour", message)
            settle()
            _CURRENT_PHASE[0] = "merge_proposal"
            proposal = runtime.branch_service.prepare_merge_proposal(
                child_thread_id=branch.child_thread_id, user_id=user_id
            )
            mode = proposal.recommended_import_mode
            if mode.value not in _MERGE_MODES:
                mode = MergeMode.SUMMARY_PLUS_EVIDENCE
            _CURRENT_PHASE[0] = "merge_apply"
            imported = runtime.branch_service.apply_merge_decision(
                child_thread_id=branch.child_thread_id,
                decision=MergeDecision(approved=True, mode=mode),
                context=RequestContext(user_id=user_id, root_thread_id=branch.root_thread_id),
            )
            record["merge"] = {
                "proposal": proposal.model_dump(mode="json"),
                "mode": mode.value,
                "imported": imported.model_dump(mode="json") if imported else None,
            }

        final = send(main_thread, "return", task["return_turn"])
        record["final_answer"] = _final_text(final)
        record["status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except Exception:  # noqa: BLE001
                pass
    record["turns"] = turns
    record["model_calls"] = calls
    record["usage"] = _sum_usage(calls)
    record["finished_at"] = time.time()
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


def _sum_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    total = {"input_tokens": 0, "output_tokens": 0, "calls": len(calls), "errors": 0}
    by_phase: dict[str, dict[str, int]] = {}
    for call in calls:
        if call.get("error"):
            total["errors"] += 1
        usage = call.get("usage") or {}
        phase = by_phase.setdefault(call["phase"], {"input_tokens": 0, "output_tokens": 0})
        for key in ("input_tokens", "output_tokens"):
            total[key] += usage.get(key, 0)
            phase[key] += usage.get(key, 0)
    total["by_phase"] = by_phase
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", nargs="*", help="Run only these task ids.")
    args = parser.parse_args()

    tasks = [
        json.loads(line)
        for line in Path(args.tasks).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.only:
        tasks = [task for task in tasks if task["id"] in set(args.only)]
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(task, arm, rep) for rep in range(args.repeats) for task in tasks for arm in ARMS]
    print(f"{len(jobs)} runs -> {out_dir}", flush=True)
    # A fresh process per run keeps module-level patches and caches isolated.
    with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as pool:
        futures = {
            pool.submit(run_one, task, arm, rep, args.model, str(out_dir)): (task["id"], arm, rep)
            for task, arm, rep in jobs
        }
        done = 0
        for future in as_completed(futures):
            done += 1
            task_id, arm, rep = futures[future]
            try:
                result = future.result()
                status = result.get("status")
                detail = result.get("error", "")[:160]
            except Exception as exc:  # noqa: BLE001
                status, detail = "crash", repr(exc)[:160]
            print(f"[{done}/{len(jobs)}] {task_id} {arm} r{rep}: {status} {detail}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
