from __future__ import annotations

# ruff: noqa: E402
import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from langgraph.checkpoint.base import empty_checkpoint

from focus_agent.engine.local_persistence import PersistentInMemorySaver, PersistentSQLiteSaver


def _checkpoint(index: int) -> dict:
    checkpoint = empty_checkpoint()
    checkpoint["id"] = f"checkpoint-{index}"
    checkpoint["channel_values"] = {"turn": index, "answer": f"answer-{index}"}
    checkpoint["channel_versions"] = {"turn": str(index), "answer": str(index)}
    return checkpoint


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def _file_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _saver_for_backend(backend: str, path: Path):
    if backend == "pickle":
        return PersistentInMemorySaver(path)
    if backend == "sqlite":
        return PersistentSQLiteSaver(path)
    raise ValueError(f"unsupported checkpoint backend: {backend}")


def run_benchmark(*, backend: str, path: Path, turns: int, sample_every: int) -> dict[str, object]:
    if backend == "pickle":
        os.environ.setdefault("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", "bench-checkpoint-local-hmac-key-32")
    saver = _saver_for_backend(backend, path)
    durations_ms: list[float] = []
    size_samples: list[dict[str, int]] = []
    try:
        for index in range(1, turns + 1):
            started = time.perf_counter()
            saver.put(
                {"configurable": {"thread_id": "bench-thread", "checkpoint_ns": ""}},
                _checkpoint(index),
                {"source": "bench_checkpoint", "turn": index},
                {"turn": str(index), "answer": str(index)},
            )
            durations_ms.append((time.perf_counter() - started) * 1000.0)
            if index % sample_every == 0 or index == turns:
                if hasattr(saver, "close"):
                    saver.close()
                size_samples.append({"turn": index, "bytes": _file_size(path)})
                saver = _saver_for_backend(backend, path)
    finally:
        if hasattr(saver, "close"):
            saver.close()

    return {
        "backend": backend,
        "path": str(path),
        "turns": turns,
        "p50_write_ms": statistics.median(durations_ms) if durations_ms else 0.0,
        "p95_write_ms": _p95(durations_ms),
        "max_write_ms": max(durations_ms) if durations_ms else 0.0,
        "final_bytes": _file_size(path),
        "size_samples": size_samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark local checkpoint persistence writes.")
    parser.add_argument("--turns", type=int, default=500)
    parser.add_argument("--backend", choices=("pickle", "sqlite"), default="pickle")
    parser.add_argument("--path", type=Path)
    parser.add_argument("--sample-every", type=int, default=100)
    args = parser.parse_args()

    turns = max(1, int(args.turns or 1))
    sample_every = max(1, int(args.sample_every or 1))
    if args.path is None:
        suffix = ".sqlite3" if args.backend == "sqlite" else ".pkl"
        with tempfile.TemporaryDirectory(prefix="focus-agent-checkpoint-bench-") as tmp:
            report = run_benchmark(
                backend=args.backend,
                path=Path(tmp) / f"langgraph-checkpoints{suffix}",
                turns=turns,
                sample_every=sample_every,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

    report = run_benchmark(
        backend=args.backend,
        path=args.path.expanduser(),
        turns=turns,
        sample_every=sample_every,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
