from __future__ import annotations

# ruff: noqa: E402
import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from focus_agent.services.agent_team import AgentTeamService


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def run_benchmark(*, sessions: int, iterations: int, hold_ms: float) -> dict[str, object]:
    service = AgentTeamService()
    lock_waits_ms: list[float] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        session_id = f"bench-session-{index}"
        for _ in range(iterations):
            started = time.perf_counter()
            with service._scheduler_lock(session_id):  # noqa: SLF001 - benchmark public behavior.
                waited = (time.perf_counter() - started) * 1000.0
                if hold_ms > 0:
                    time.sleep(hold_ms / 1000.0)
            with lock:
                lock_waits_ms.append(waited)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(sessions)]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "sessions": sessions,
        "iterations_per_session": iterations,
        "hold_ms": hold_ms,
        "samples": len(lock_waits_ms),
        "elapsed_ms": elapsed_ms,
        "p50_lock_wait_ms": statistics.median(lock_waits_ms) if lock_waits_ms else 0.0,
        "p95_lock_wait_ms": _p95(lock_waits_ms),
        "max_lock_wait_ms": max(lock_waits_ms) if lock_waits_ms else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark agent-team per-session scheduler locks.")
    parser.add_argument("--sessions", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--hold-ms", type=float, default=1.0)
    args = parser.parse_args()
    report = run_benchmark(
        sessions=max(1, int(args.sessions or 1)),
        iterations=max(1, int(args.iterations or 1)),
        hold_ms=max(0.0, float(args.hold_ms or 0.0)),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
