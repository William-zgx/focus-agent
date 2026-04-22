from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from urllib import parse as urllib_parse
from uuid import uuid4

from focus_agent.config import load_local_env_file
from focus_agent.observability.trajectory import SCHEMA_VERSION, TrajectoryStep, TurnTrajectoryRecord, utc_now
from focus_agent.repositories.postgres_trajectory_repository import PostgresTrajectoryRepository

from ui_smoke_test import (
    CdpWebSocket,
    collect_browser_diagnostics,
    create_page_target,
    ensure_health,
    pick_free_port,
    resolve_chrome_path,
    wait_for_devtools,
)


DEFAULT_APP_BASE_URL = "http://127.0.0.1:8000/app"
DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/healthz"
DEFAULT_RUNTIME_ENV_PATH = ".focus_agent/postgres/runtime.env"
DEFAULT_API_STARTUP_TIMEOUT_SECONDS = 45.0
ROOT_DIR = Path(__file__).resolve().parents[1]


def _is_local_url(url: str) -> bool:
    parsed = urllib_parse.urlparse(url)
    return (parsed.hostname or "").strip().lower() in {"127.0.0.1", "localhost"}


def _tail_text(path: Path, *, max_lines: int = 40) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def _wait_for_health(url: str, *, timeout_seconds: float = DEFAULT_API_STARTUP_TIMEOUT_SECONDS) -> None:
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


def seed_observability_record(database_uri: str) -> dict[str, str]:
    repo = PostgresTrajectoryRepository(database_uri)
    repo.setup()

    now = utc_now()
    seed = uuid4().hex
    request_id = f"req-smoke-{seed[:12]}"
    trace_id = uuid4().hex
    root_span_id = uuid4().hex[:16]
    turn_id = str(uuid4())
    thread_id = f"observability-smoke-{seed[:8]}"

    record = TurnTrajectoryRecord(
        id=turn_id,
        schema_version=SCHEMA_VERSION,
        kind="chat.turn",
        status="failed",
        thread_id=thread_id,
        root_thread_id=thread_id,
        user_id_hash=f"smoke-{seed[:8]}",
        scene="long_dialog_research",
        started_at=now,
        finished_at=now,
        request_id=request_id,
        trace_id=trace_id,
        root_span_id=root_span_id,
        environment="smoke",
        deployment="ui-smoke",
        app_version="ui-smoke",
        task_brief="Observability smoke seed",
        user_message="Observability smoke seed question",
        answer="Observability smoke seed answer",
        selected_model="smoke:model",
        metrics={
            "latency_ms": 321.0,
            "tool_calls": 1,
            "llm_calls": 1,
            "cache_hits": 0,
            "fallback_uses": 1,
        },
        error="Smoke seed error",
        trajectory=[
            TrajectoryStep(
                tool="web_search",
                args={"query": "focus-agent observability smoke"},
                observation="Smoke seed observation",
                duration_ms=123.0,
                error="Smoke seed error",
                fallback_used=True,
                fallback_group="web_search",
                runtime={
                    "provider": "smoke",
                    "model": "smoke:model",
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "span_id": root_span_id,
                },
            )
        ],
    )
    repo.record_turn(record)
    return {
        "turn_id": turn_id,
        "request_id": request_id,
        "trace_id": trace_id,
    }


def _run_expression(client: CdpWebSocket, expression: str) -> dict[str, object]:
    response = client.send(
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        },
    )
    raw_result = response.get("result", {}) if isinstance(response.get("result"), dict) else {}
    payload = raw_result.get("value", "")
    if not isinstance(payload, str) or not payload.strip():
        diagnostics = collect_browser_diagnostics(client)
        raise RuntimeError(f"Unexpected browser evaluation response: {response!r}; diagnostics={diagnostics!r}")
    return json.loads(payload)


def _instrument_browser(client: CdpWebSocket) -> None:
    client.send("Page.enable")
    client.send("Runtime.enable")
    client.send(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
window.__faFetches = [];
window.__faErrors = [];
const __faFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const url = String(args[0]);
  const init = args[1] || {};
  window.__faFetches.push({ stage: "start", url, method: init.method || "GET" });
  try {
    const response = await __faFetch(...args);
    window.__faFetches.push({ stage: "end", url, status: response.status, ok: response.ok });
    return response;
  } catch (error) {
    window.__faFetches.push({
      stage: "error",
      url,
      message: error && error.message ? error.message : String(error),
    });
    throw error;
  }
};
window.addEventListener("error", (event) => {
  window.__faErrors.push({
    type: "error",
    message: event.message,
    source: event.filename,
    lineno: event.lineno,
    colno: event.colno,
  });
});
window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  window.__faErrors.push({
    type: "unhandledrejection",
    message: reason && reason.message ? reason.message : String(reason),
  });
});
""",
        },
    )


def _wait_for_page_load(client: CdpWebSocket, url: str) -> None:
    client.send("Page.navigate", {"url": url})
    time.sleep(1.5)


def build_overview_expression(seed: dict[str, str]) -> str:
    payload = json.dumps(seed, ensure_ascii=False)
    return rf"""
(async () => {{
  const seed = {payload};
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, timeout = 30000, label = 'condition') => {{
    const started = Date.now();
    while (Date.now() - started < timeout) {{
      const value = await predicate();
      if (value) return value;
      await sleep(100);
    }}
    throw new Error('Timed out waiting for ' + label);
  }};
  const bodyText = () => document.body?.innerText || '';
  const fetches = () => window.__faFetches || [];
  await waitFor(
    () => bodyText().includes('Ops overview') || bodyText().includes('运营总览'),
    30000,
    'overview page title'
  );
  await waitFor(
    () =>
      fetches().some((item) => item.stage === 'end' && item.ok && String(item.url).includes('/v1/observability/overview')),
    30000,
    'overview fetch'
  );
  const cards = document.querySelectorAll('.fa-observability-overview-card').length;
  if (cards < 3) {{
    throw new Error('Observability overview cards did not render.');
  }}
  return JSON.stringify({{
    url: location.href,
    cards,
    request: seed.request_id,
  }});
}})()
"""


def build_trajectory_expression(seed: dict[str, str]) -> str:
    payload = json.dumps(seed, ensure_ascii=False)
    return rf"""
(async () => {{
  const seed = {payload};
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, timeout = 40000, label = 'condition') => {{
    const started = Date.now();
    while (Date.now() - started < timeout) {{
      const value = await predicate();
      if (value) return value;
      await sleep(100);
    }}
    throw new Error('Timed out waiting for ' + label);
  }};
  const bodyText = () => document.body?.innerText || '';
  const fetches = () => window.__faFetches || [];
  await waitFor(
    () => bodyText().includes('Sample explorer') || bodyText().includes('样本浏览器'),
    40000,
    'trajectory workbench title'
  );
  await waitFor(
    () =>
      fetches().some((item) => item.stage === 'end' && item.ok && String(item.url).includes('/v1/observability/trajectory?')),
    40000,
    'trajectory list fetch'
  );
  await waitFor(
    () =>
      fetches().some((item) => item.stage === 'end' && item.ok && String(item.url).includes('/v1/observability/overview')),
    40000,
    'observability overview fetch'
  );
  await waitFor(
    () =>
      fetches().some((item) => item.stage === 'end' && item.ok && String(item.url).includes(`/v1/observability/trajectory/${{seed.turn_id}}`)),
    40000,
    'trajectory detail fetch'
  );
  await waitFor(
    () =>
      Array.from(document.querySelectorAll('.fa-observability-correlation-item strong'))
        .map((item) => item.textContent || '')
        .some((value) => value.includes(seed.request_id) || value.includes(seed.trace_id)),
    40000,
    'correlation hooks'
  );
  const turnCards = document.querySelectorAll('.fa-observability-turn-card').length;
  const correlationItems = Array.from(document.querySelectorAll('.fa-observability-correlation-item strong'))
    .map((item) => item.textContent || '');
  const requestInput = document.querySelector('input[placeholder="req-…"], input[placeholder="req-..."]');
  const traceInput = document.querySelector('input[placeholder="trace-…"], input[placeholder="trace-..."]');
  if (!requestInput || !traceInput) {{
    throw new Error('Request/trace filters were not rendered.');
  }}
  return JSON.stringify({{
    url: location.href,
    turnCards,
    correlationItems,
  }});
}})()
"""


def run_observability_ui_smoke_test(
    *,
    app_base_url: str,
    health_url: str,
    database_uri: str | None,
    chrome_path: str,
    start_api_if_needed: bool,
) -> dict[str, object]:
    managed_api = _ensure_local_api(
        health_url=health_url,
        start_api_if_needed=start_api_if_needed,
    )
    try:
        database_uri = _resolve_database_uri(database_uri)
        seed = seed_observability_record(database_uri)
        request_query = urllib_parse.urlencode({"request": seed["request_id"]})
        overview_url = f"{app_base_url.rstrip('/')}/observability/overview?{request_query}"
        trajectory_url = f"{app_base_url.rstrip('/')}/observability/trajectory?{request_query}"

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
                _instrument_browser(client)
                _wait_for_page_load(client, overview_url)
                overview = _run_expression(client, build_overview_expression(seed))
                _wait_for_page_load(client, trajectory_url)
                trajectory = _run_expression(client, build_trajectory_expression(seed))
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
    parser.add_argument("--database-uri", default=None, help="Database URI used to seed observability records.")
    parser.add_argument("--chrome-path", default=None, help="Path to the Chrome executable.")
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
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
