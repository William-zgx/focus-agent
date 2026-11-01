"""Paired analysis of branch A/B scores.

Pairs are (task, repeat): the same user messages under both arms. Reports the
mean per arm, the mean paired difference (branch - linear) with a 95%
task-level cluster bootstrap CI, and an exact two-sided sign test over tasks
(per-task mean difference across repeats). Also reports pass^k per arm.

Usage:
    .venv/bin/python scripts/branch_ab/analyze.py reports/branch_ab/deepseek/scores.*.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from math import comb
from pathlib import Path
from statistics import mean
from typing import Any

METRICS = {
    "judge_overall": lambda r: r["judge"].get("overall") if "error" not in r["judge"] else None,
    "judge_rubric_rate": lambda r: r["judge"].get("rubric_rate"),
    "judge_deliverable": lambda r: _bool(r["judge"].get("deliverable_given")),
    "judge_uses_rejected": lambda r: _bool(r["judge"].get("uses_rejected_material")),
    "regex_main_recall": lambda r: r["regex"]["main_recall"],
    "regex_detour_recall": lambda r: r["regex"]["detour_recall"],
    "regex_contaminated": lambda r: float(r["regex"]["contaminated"]),
    "regex_pass": lambda r: float(r["regex"]["regex_pass"]),
    "input_tokens": lambda r: r["usage"]["input_tokens"],
    "output_tokens": lambda r: r["usage"]["output_tokens"],
    "answer_chars": lambda r: r["answer_chars"],
}
LOWER_IS_BETTER = {"judge_uses_rejected", "regex_contaminated", "input_tokens", "output_tokens"}


def _bool(value: Any) -> float | None:
    return None if value is None else float(bool(value))


def _sign_test(diffs: list[float]) -> float:
    pos = sum(d > 0 for d in diffs)
    neg = sum(d < 0 for d in diffs)
    n = pos + neg
    if n == 0:
        return 1.0
    k = min(pos, neg)
    p = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * p)


def _bootstrap(per_task: dict[str, list[float]], iters: int = 5000, seed: int = 7):
    rng = random.Random(seed)
    tasks = list(per_task)
    stats = []
    for _ in range(iters):
        sample = [rng.choice(tasks) for _ in tasks]
        values = [d for task in sample for d in per_task[task]]
        stats.append(mean(values))
    stats.sort()
    return stats[int(0.025 * iters)], stats[int(0.975 * iters)]


def analyze(rows: list[dict[str, Any]], group: str | None = None) -> dict[str, Any]:
    by_key: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        by_key[(row["task_id"], row["repeat"])][row["arm"]] = row
    pairs = [arms for arms in by_key.values() if {"linear", "branch"} <= arms.keys()]
    result: dict[str, Any] = {"group": group or "all", "pairs": len(pairs)}
    for name, fn in METRICS.items():
        per_task: dict[str, list[float]] = defaultdict(list)
        arm_values = {"linear": [], "branch": []}
        for arms in pairs:
            a, b = fn(arms["linear"]), fn(arms["branch"])
            if a is None or b is None:
                continue
            arm_values["linear"].append(a)
            arm_values["branch"].append(b)
            per_task[arms["linear"]["task_id"]].append(b - a)
        if not per_task:
            continue
        diffs = [d for values in per_task.values() for d in values]
        low, high = _bootstrap(per_task)
        result[name] = {
            "linear": round(mean(arm_values["linear"]), 3),
            "branch": round(mean(arm_values["branch"]), 3),
            "diff": round(mean(diffs), 3),
            "ci95": [round(low, 3), round(high, 3)],
            "sign_p": round(_sign_test([mean(v) for v in per_task.values()]), 4),
            "tasks_better": sum(
                (mean(v) < 0) if name in LOWER_IS_BETTER else (mean(v) > 0)
                for v in per_task.values()
            ),
            "tasks_worse": sum(
                (mean(v) > 0) if name in LOWER_IS_BETTER else (mean(v) < 0)
                for v in per_task.values()
            ),
            "n_tasks": len(per_task),
        }
    # pass^k: a task passes only if every repeat passes (judge overall >= 4 and the judge
    # finds no adopted rejected material). Regex contamination stays a diagnostic only: it
    # also fires when an answer correctly says "X was ruled out".
    for arm in ("linear", "branch"):
        per_task_pass: dict[str, list[bool]] = defaultdict(list)
        for row in rows:
            if row["arm"] != arm or "error" in row["judge"]:
                continue
            ok = (row["judge"].get("overall") or 0) >= 4 and not row["judge"].get(
                "uses_rejected_material"
            )
            per_task_pass[row["task_id"]].append(ok)
        if per_task_pass:
            result[f"pass_k_{arm}"] = round(
                mean(all(values) for values in per_task_pass.values()), 3
            )
            result[f"pass_1_{arm}"] = round(
                mean(v for values in per_task_pass.values() for v in values), 3
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scores", nargs="+")
    parser.add_argument("--by", choices=["category", "language"], action="append", default=[])
    parser.add_argument("--json", help="Write the full analysis to this path.")
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for path in args.scores
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = [analyze(rows)]
    for field in args.by:
        for value in sorted({row[field] for row in rows}):
            report.append(analyze([r for r in rows if r[field] == value], f"{field}={value}"))
    for section in report:
        print(f"== {section['group']} (pairs={section['pairs']})")
        for key, value in section.items():
            if isinstance(value, dict):
                print(
                    f"  {key:22s} linear={value['linear']:<9} branch={value['branch']:<9} "
                    f"diff={value['diff']:<8} ci95={value['ci95']} sign_p={value['sign_p']} "
                    f"better/worse={value['tasks_better']}/{value['tasks_worse']} of {value['n_tasks']}"
                )
            elif key.startswith("pass_"):
                print(f"  {key:22s} {value}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
