from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib import parse as urllib_parse
from uuid import uuid4

from observability_ui_browser import (
    build_overview_expression,
    build_trajectory_expression,
    instrument_browser,
    run_expression,
    wait_for_page_load,
)
from observability_ui_smoke_helpers import _tail_text
from ui_smoke_test import (
    CdpWebSocket,
    chrome_runtime_flags,
    create_demo_access_token,
    create_page_target,
    ensure_health,
    pick_free_port,
    resolve_chrome_path,
    wait_for_devtools,
)

from focus_agent.config import load_local_env_file
from focus_agent.observability.trajectory import (
    SCHEMA_VERSION,
    TrajectoryStep,
    TurnTrajectoryRecord,
    utc_now,
)
from focus_agent.repositories.postgres_trajectory_repository import PostgresTrajectoryRepository

DEFAULT_APP_BASE_URL = "http://127.0.0.1:8000/app"
DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/healthz"
DEFAULT_RUNTIME_ENV_PATH = ".focus_agent/postgres/runtime.env"
DEFAULT_API_STARTUP_TIMEOUT_SECONDS = 45.0
ROOT_DIR = Path(__file__).resolve().parents[1]
SCENARIOS = ("success", "failed", "zero-step", "missing-detail", "all")


def _is_local_url(url: str) -> bool:
    parsed = urllib_parse.urlparse(url)
    return (parsed.hostname or "").strip().lower() in {"127.0.0.1", "localhost"}


def _wait_for_health(
    url: str, *, timeout_seconds: float = DEFAULT_API_STARTUP_TIMEOUT_SECONDS
) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            ensure_health(url)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for API health at {url}: {last_error}")


def _terminate_managed_api(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    except Exception:  # noqa: BLE001
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            process.kill()
        process.wait(timeout=5)


def _ensure_local_api(
    *,
    health_url: str,
    start_api_if_needed: bool,
) -> tuple[subprocess.Popen[str], Path] | None:
    try:
        ensure_health(health_url)
        return None
    except Exception as health_error:  # noqa: BLE001
        if not start_api_if_needed:
            raise
        if not _is_local_url(health_url):
            raise RuntimeError(
                f"Health probe failed for non-local URL {health_url}: {health_error}"
            ) from health_error

    log_dir = Path(tempfile.mkdtemp(prefix="focus-agent-observability-api-"))
    log_path = log_dir / "api.log"
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        ["./scripts/run-api.sh"],
        cwd=ROOT_DIR,
        env={
            **os.environ,
            "SERVE_SCRIPT_NAME": "observability-ui-smoke",
            # Force FastAPI to serve the built frontend directly during smoke runs
            # instead of redirecting /app to a Vite dev server from local.env.
            "WEB_APP_DEV_SERVER_URL": "",
        },
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    log_handle.close()

    try:
        _wait_for_health(health_url)
        return process, log_path
    except Exception as exc:  # noqa: BLE001
        _terminate_managed_api(process)
        raise RuntimeError(
            f"Failed to auto-start local API for observability smoke: {exc}\n\n"
            f"Recent API log:\n{_tail_text(log_path)}"
        ) from exc


def _resolve_database_uri(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("DATABASE_URI"):
        return str(os.environ["DATABASE_URI"])
    runtime_env_path = Path(DEFAULT_RUNTIME_ENV_PATH)
    if runtime_env_path.exists():
        loaded = load_local_env_file(runtime_env_path, environ={})
        database_uri = loaded.get("DATABASE_URI")
        if database_uri:
            return database_uri
    raise RuntimeError(
        "DATABASE_URI is required for the observability UI smoke. "
        "Start the API via `make api` or pass --database-uri."
    )


def _scenario_names(scenario: str) -> tuple[str, ...]:
    normalized = scenario.strip().lower()
    if normalized == "all":
        return ("success", "failed", "zero-step", "missing-detail")
    if normalized in SCENARIOS:
        return (normalized,)
    raise ValueError(f"Unsupported observability smoke scenario: {scenario}")


def _build_seed_record(
    *,
    name: str,
    now,
    request_id: str,
    seed: str,
) -> TurnTrajectoryRecord:
    trace_id = uuid4().hex
    root_span_id = uuid4().hex[:16]
    turn_id = str(uuid4())
    thread_id = f"observability-smoke-{name}-{seed[:8]}"
    base_metrics = {
        "latency_ms": 321.0,
        "tool_calls": 1,
        "llm_calls": 1,
        "cache_hits": 0,
        "fallback_uses": 0,
    }
    base_kwargs = {
        "id": turn_id,
        "schema_version": SCHEMA_VERSION,
        "kind": "chat.turn",
        "thread_id": thread_id,
        "root_thread_id": thread_id,
        "user_id_hash": f"smoke-{seed[:8]}",
        "scene": "long_dialog_research",
        "started_at": now,
        "finished_at": now,
        "request_id": request_id,
        "trace_id": trace_id,
        "root_span_id": root_span_id,
        "environment": "smoke",
        "deployment": "ui-smoke",
        "app_version": "ui-smoke",
        "task_brief": f"Observability smoke {name} seed",
        "user_message": f"Observability smoke {name} seed question",
        "answer": f"Observability smoke {name} seed answer",
        "selected_model": "smoke:model",
        "metrics": dict(base_metrics),
    }

    def record_kwargs(**overrides):
        return {**base_kwargs, **overrides}

    if name == "success":
        return TurnTrajectoryRecord(
            **record_kwargs(
                status="succeeded",
                metrics={
                    **base_metrics,
                    "latency_ms": 187.0,
                    "tool_calls": 2,
                    "cache_hits": 1,
                },
                trajectory=[
                    TrajectoryStep(
                        tool="read_file",
                        args={"path": "README.md"},
                        observation="Smoke success read observation",
                        duration_ms=44.0,
                        cache_hit=True,
                        runtime={
                            "provider": "smoke",
                            "model": "smoke:model",
                            "request_id": request_id,
                            "trace_id": trace_id,
                            "span_id": root_span_id,
                        },
                    ),
                    TrajectoryStep(
                        tool="search_code",
                        args={"query": "observability"},
                        observation="Smoke success search observation",
                        duration_ms=71.0,
                        parallel_batch_size=2,
                        runtime={
                            "provider": "smoke",
                            "model": "smoke:model",
                            "request_id": request_id,
                            "trace_id": trace_id,
                            "span_id": root_span_id,
                        },
                    ),
                ],
            ),
        )
    if name == "zero-step":
        return TurnTrajectoryRecord(
            **record_kwargs(
                status="succeeded",
                task_brief="Observability smoke zero-step seed",
                user_message="Observability smoke zero-step seed question",
                answer="Observability smoke zero-step answer without tool evidence",
                metrics={**base_metrics, "latency_ms": 52.0, "tool_calls": 0},
                trajectory=[],
            ),
        )
    if name == "missing-detail":
        return TurnTrajectoryRecord(
            **record_kwargs(
                trace_id=None,
                root_span_id=None,
                selected_model=None,
                status="missing_detail",
                task_brief="Observability smoke missing-detail seed",
                user_message="Observability smoke missing-detail seed question",
                answer="",
                error="Smoke missing-detail seed intentionally omits timeline evidence.",
                metrics={**base_metrics, "latency_ms": 0.0, "tool_calls": 0},
                plan_meta={"smoke_evidence_state": "missing_detail"},
                trajectory=[],
            ),
        )
    return TurnTrajectoryRecord(
        **record_kwargs(
            status="failed",
            metrics={**base_metrics, "fallback_uses": 1},
            error="Smoke seed error",
            trajectory=[
                TrajectoryStep(
                    tool="web_search",
                    args={"query": "focus-agent observability smoke"},
                    observation="Smoke failed seed observation",
                    duration_ms=123.0,
                    error="Smoke seed error",
                    fallback_used=True,
                    fallback_group="web_search",
                    parallel_batch_size=2,
                    runtime={
                        "provider": "smoke",
                        "model": "smoke:model",
                        "request_id": request_id,
                        "trace_id": trace_id,
                        "span_id": root_span_id,
                    },
                )
            ],
        ),
    )


def seed_observability_records(database_uri: str, *, scenario: str = "all") -> dict[str, object]:
    repo = PostgresTrajectoryRepository(database_uri)
    repo.setup()

    now = utc_now()
    seed = uuid4().hex
    request_id = f"req-smoke-{seed[:12]}"
    records = [
        _build_seed_record(name=name, now=now, request_id=request_id, seed=seed)
        for name in _scenario_names(scenario)
    ]
    for record in records:
        repo.record_turn(record)
    return {
        "scenario": scenario,
        "request_id": request_id,
        "turn_ids": {
            name: record.id for name, record in zip(_scenario_names(scenario), records, strict=True)
        },
        "trace_ids": {
            name: record.trace_id
            for name, record in zip(_scenario_names(scenario), records, strict=True)
        },
        "primary_turn_id": records[0].id,
        "record_count": len(records),
    }


def seed_observability_record(database_uri: str) -> dict[str, object]:
    return seed_observability_records(database_uri, scenario="failed")


def run_observability_ui_smoke_test(
    *,
    app_base_url: str,
    health_url: str,
    database_uri: str | None,
    chrome_path: str,
    start_api_if_needed: bool,
    scenario: str = "all",
) -> dict[str, object]:
    managed_api = _ensure_local_api(
        health_url=health_url,
        start_api_if_needed=start_api_if_needed,
    )
    try:
        database_uri = _resolve_database_uri(database_uri)
        seed = seed_observability_records(database_uri, scenario=scenario)
        demo_access_token = create_demo_access_token(health_url)
        request_query = urllib_parse.urlencode({"request": seed["request_id"]})
        overview_url = f"{app_base_url.rstrip('/')}/observability/overview?{request_query}"
        turn_ids = dict(seed.get("turn_ids") or {})

        port = pick_free_port()
        temp_dir = tempfile.TemporaryDirectory(prefix="focus-agent-observability-ui-smoke-")
        chrome_process = subprocess.Popen(  # noqa: S603
            [
                chrome_path,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={temp_dir.name}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-search-engine-choice-screen",
                *chrome_runtime_flags(),
                "--new-window",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_devtools(port)
            target = create_page_target(port, "about:blank")
            websocket_url = str(target.get("webSocketDebuggerUrl") or "")
            if not websocket_url:
                raise RuntimeError(f"Missing webSocketDebuggerUrl in target payload: {target!r}")

            client = CdpWebSocket(websocket_url)
            try:
                instrument_browser(client, demo_access_token=demo_access_token)
                wait_for_page_load(client, overview_url)
                overview = run_expression(client, build_overview_expression(seed))
                trajectory: dict[str, object] = {}
                for name in _scenario_names(scenario):
                    turn_id = turn_ids.get(name)
                    if not turn_id:
                        continue
                    query = urllib_parse.urlencode({"request": seed["request_id"], "turn": turn_id})
                    trajectory_url = f"{app_base_url.rstrip('/')}/observability/trajectory?{query}"
                    wait_for_page_load(client, trajectory_url)
                    trajectory[name] = run_expression(
                        client,
                        build_trajectory_expression(
                            seed,
                            evidence_state=name,
                            promote=name == "success",
                        ),
                    )
                return {
                    "seed": seed,
                    "overview": overview,
                    "trajectory": trajectory,
                }
            finally:
                client.close()
        finally:
            chrome_process.terminate()
            try:
                chrome_process.wait(timeout=5)
            except Exception:  # noqa: BLE001
                chrome_process.kill()
                chrome_process.wait(timeout=5)
            temp_dir.cleanup()
    finally:
        if managed_api is not None:
            process, _ = managed_api
            _terminate_managed_api(process)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a real-browser observability UI smoke test against the local Focus Agent app."
    )
    parser.add_argument("--app-base-url", default=DEFAULT_APP_BASE_URL, help="App base URL.")
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL, help="Health endpoint.")
    parser.add_argument(
        "--database-uri", default=None, help="Database URI used to seed observability records."
    )
    parser.add_argument("--chrome-path", default=None, help="Path to the Chrome executable.")
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="all",
        help="Seed and exercise a single observability evidence scenario or all scenarios.",
    )
    parser.add_argument(
        "--no-start-api",
        action="store_true",
        help="Do not auto-start the local API if the health probe fails.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_observability_ui_smoke_test(
        app_base_url=str(args.app_base_url),
        health_url=str(args.health_url),
        database_uri=args.database_uri,
        chrome_path=resolve_chrome_path(args.chrome_path),
        start_api_if_needed=not bool(args.no_start_api),
        scenario=str(args.scenario),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
