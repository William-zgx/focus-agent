"""Score branch A/B runs: deterministic regex checks plus a blind LLM judge.

The judge sees the user's messages and the final answer only; it is never told
which arm produced the answer. Use a judge model different from the agent
model. Results are written next to the runs as ``scores.jsonl``.

Usage:
    .venv/bin/python scripts/branch_ab/score.py \
        --tasks tests/eval/datasets/branch_ab/tasks.jsonl \
        --runs reports/branch_ab/deepseek --judge moonshot:kimi-k2.6
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

JUDGE_PROMPT = """You are grading the final answer of an AI assistant at the end of a long work session.
Below is everything the USER said during the session, in order, followed by the assistant's FINAL answer to the user's last message. Earlier assistant replies are not shown. Judge only the final answer.

Grade it against the rubric. Treat as authoritative what the user established: the main goal and constraints, and the side investigation's final decision (later user statements override earlier ones; anything the user rejected or superseded must not be presented as part of the recommendation). A correct answer may hedge on facts the user never provided, but must not refuse to give the requested deliverable or treat the user's own settled decisions as unconfirmed.

## User messages
{user_messages}

## Final answer
{answer}

## Rubric
{rubric}

Return JSON only, no prose:
{{"criteria": [{{"criterion": str, "met": true|false, "reason": str}}], "deliverable_given": true|false, "uses_rejected_material": true|false, "overall": 1|2|3|4|5}}
overall: 5 = fully correct and complete deliverable; 4 = correct with a minor omission; 3 = usable but missing an important item or slightly wrong; 2 = mostly wrong, incomplete, or refuses/defers the deliverable; 1 = wrong."""


def _load(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def regex_score(task: dict[str, Any], answer: str) -> dict[str, Any]:
    def hit(patterns: list[str]) -> bool:
        return any(re.search(pattern, answer, re.IGNORECASE) for pattern in patterns)

    include = {item["id"]: hit(item["any_of"]) for item in task["must_include"]}
    exclude = {item["id"]: hit(item["any_of"]) for item in task["must_not_include"]}
    kinds = {item["id"]: item["kind"] for item in task["must_include"]}
    main = [ok for key, ok in include.items() if kinds[key] == "main_constraint"]
    detour = [ok for key, ok in include.items() if kinds[key] == "detour_detail"]
    return {
        "include": include,
        "exclude_violations": exclude,
        "main_recall": sum(main) / len(main) if main else None,
        "detour_recall": sum(detour) / len(detour) if detour else None,
        "include_recall": sum(include.values()) / len(include) if include else None,
        "contaminated": any(exclude.values()),
        "regex_pass": all(include.values()) and not any(exclude.values()),
    }


def _judge_model(model_id: str):
    os.environ.setdefault(
        "FOCUS_AGENT_LOCAL_ENV_FILE", str(REPO_ROOT / ".focus_agent" / "local.env")
    )
    os.environ.setdefault(
        "FOCUS_AGENT_MODEL_CATALOG_DOC", str(REPO_ROOT / ".focus_agent" / "models.toml")
    )
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from focus_agent.config import Settings
    from focus_agent.model_registry import create_chat_model

    settings = Settings.from_env()
    return create_chat_model(
        model_id, temperature=0, thinking_mode="disabled", settings=settings, timeout_seconds=180
    )


def _parse_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"judge returned no JSON: {text[:200]!r}")
    return json.loads(match.group(0))


def judge_score(model: Any, task: dict[str, Any], answer: str) -> dict[str, Any]:
    user_messages = "\n".join(
        f"{index}. {message}"
        for index, message in enumerate(
            [*task["main_turns"], *task["detour_turns"], task["return_turn"]], start=1
        )
    )
    prompt = JUDGE_PROMPT.format(
        user_messages=user_messages,
        answer=answer or "(empty)",
        rubric="\n".join(f"- {item}" for item in task["rubric"]),
    )
    last_error: Exception | None = None
    for _ in range(3):
        try:
            content = model.invoke(prompt).content
            text = content if isinstance(content, str) else json.dumps(content)
            parsed = _parse_json(text)
            criteria = parsed.get("criteria") or []
            parsed["rubric_rate"] = (
                sum(bool(item.get("met")) for item in criteria) / len(criteria)
                if criteria
                else None
            )
            return parsed
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    return {"error": repr(last_error)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--judge", required=True, help="Judge model id (not the agent model).")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", help="Defaults to <runs>/scores.<judge>.jsonl")
    args = parser.parse_args()

    tasks = {task["id"]: task for task in _load(Path(args.tasks))}
    runs_dir = Path(args.runs)
    runs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(runs_dir.glob("*__*__r*.json"))
    ]
    judge_tag = re.sub(r"[^A-Za-z0-9.-]+", "_", args.judge)
    out_path = Path(args.out) if args.out else runs_dir / f"scores.{judge_tag}.jsonl"
    done = {}
    if out_path.exists():
        for row in _load(out_path):
            if "error" not in (row.get("judge") or {}):
                done[(row["task_id"], row["arm"], row["repeat"])] = row
    model = _judge_model(args.judge)

    def score(run: dict[str, Any]) -> dict[str, Any]:
        key = (run["task_id"], run["arm"], run["repeat"])
        if key in done:
            return done[key]
        task = tasks[run["task_id"]]
        answer = run.get("final_answer") or ""
        row = {
            "task_id": run["task_id"],
            "category": run["category"],
            "language": run["language"],
            "arm": run["arm"],
            "repeat": run["repeat"],
            "model": run["model"],
            "status": run["status"],
            "usage": {k: run["usage"].get(k) for k in ("input_tokens", "output_tokens", "calls")},
            "answer_chars": len(answer),
            "regex": regex_score(task, answer),
            "judge_model": args.judge,
            "judge": judge_score(model, task, answer)
            if run["status"] == "ok"
            else {"error": "run failed"},
        }
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(score, [run for run in runs if run["task_id"] in tasks]))
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(rows)} scored -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
