"""Local provider and isolated API processes for browser regression checks."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT = 45.0
AUTH_SECRET = "review-fixes-browser-smoke-secret-012345678901"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ModelFixture:
    """A deterministic provider fixture; no external model calls leave localhost."""

    def __init__(self, port: int, log: list[dict[str, Any]]) -> None:
        self.port = port
        self.log = log
        self.server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:
                del format, args

            def _json(self, payload: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/healthz":
                    self._json({"status": "ok"})
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/chat/completions":
                    self._json({"error": "not found"}, 404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length) or b"{}")
                messages = request.get("messages") or []
                prompt = "\n".join(
                    str(item.get("content", "")) for item in messages if isinstance(item, dict)
                )
                user_messages = [
                    str(item.get("content", ""))
                    for item in messages
                    if isinstance(item, dict)
                    and str(item.get("role") or item.get("type") or "").lower() in {"user", "human"}
                ]
                scenario_prompt = user_messages[-1] if user_messages else prompt
                is_main_model = request.get("model") == "browser-smoke"
                fail = is_main_model and "FAIL_BROWSER" in scenario_prompt
                fixture.log.append(
                    {
                        "prompt": prompt[-2000:],
                        "user_message": scenario_prompt,
                        "stream": bool(request.get("stream")),
                        "model": request.get("model"),
                        "status": 500 if fail else 200,
                    }
                )
                if fail:
                    self._json({"error": {"message": "deterministic browser failure"}}, 500)
                    return
                slow = is_main_model and (
                    "SLOW_BROWSER" in scenario_prompt or "HANDOFF_SLOW" in scenario_prompt
                )
                content = "OK 处理中" if slow else "OK"
                if not request.get("stream"):
                    if slow:
                        time.sleep(8)
                    self._json(
                        {
                            "id": "review-fixes-browser",
                            "object": "chat.completion",
                            "created": int(time.time()),
                            "model": "browser-smoke",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {"role": "assistant", "content": content},
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 1,
                                "completion_tokens": 1,
                                "total_tokens": 2,
                            },
                        }
                    )
                    fixture.log.append(
                        {
                            "request_finished": True,
                            "user_message": scenario_prompt,
                            "model": request.get("model"),
                        }
                    )
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                chunks = [content]
                for chunk in chunks:
                    payload = {
                        "id": "review-fixes-browser",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "browser-smoke",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": chunk},
                                "finish_reason": None,
                            }
                        ],
                    }
                    self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                    self.wfile.flush()
                if slow:
                    time.sleep(8)
                stop = {
                    "id": "review-fixes-browser",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "browser-smoke",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                try:
                    self.wfile.write(f"data: {json.dumps(stop)}\n\ndata: [DONE]\n\n".encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    fixture.log.append({"client_cancelled": True, "prompt": prompt[-2000:]})
                finally:
                    fixture.log.append(
                        {
                            "request_finished": True,
                            "user_message": scenario_prompt,
                            "model": request.get("model"),
                        }
                    )

        return Handler

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def wait_http(url: str, timeout: float = DEFAULT_TIMEOUT) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib_request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"timed out waiting for {url}: {last}")


def start_api(
    *, port: int, fixture_port: int, data_dir: Path, output_dir: Path
) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env.update(
        {
            "API_HOST": "127.0.0.1",
            "API_PORT": str(port),
            "AUTH_ENABLED": "true",
            "AUTH_DEMO_TOKENS_ENABLED": "true",
            "AUTH_JWT_SECRET": AUTH_SECRET,
            "DATABASE_URI": "",
            "FOCUS_AGENT_LOCAL_ENV_FILE": str(data_dir / "missing.local.env"),
            "FOCUS_AGENT_MODEL_CATALOG_DOC": str(REPO_ROOT / "docs/models.example.toml"),
            "FOCUS_AGENT_TOOL_CATALOG_DOC": str(REPO_ROOT / "docs/tools.example.toml"),
            "FOCUS_AGENT_CHECKPOINT_BACKEND": "sqlite",
            "LOCAL_CHECKPOINT_PATH": str(data_dir / "checkpoint.sqlite3"),
            "LOCAL_STORE_PATH": str(data_dir / "store.sqlite3"),
            "BRANCH_DB_PATH": str(data_dir / "branches.sqlite3"),
            "ARTIFACT_DIR": str(data_dir / "artifacts"),
            "WEB_APP_DIST_DIR": str(REPO_ROOT / "apps/web/dist"),
            "WEB_APP_DEV_SERVER_URL": "",
            "MODEL": "openai:browser-smoke",
            "HELPER_MODEL": "openai:browser-helper",
            "OPENAI_API_KEY": "local-browser-fixture",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{fixture_port}/v1",
            "AGENT_MEMORY_EMBEDDING_ENABLED": "false",
            "AGENT_MEMORY_EMBEDDING_AUTO_PULL": "false",
            "AGENT_MEMORY_EMBEDDING_BACKEND": "disabled",
            "AGENT_MEMORY_VECTOR_SEARCH_MODE": "off",
            "AGENT_ZVEC_ENABLED": "false",
            "TRAJECTORY_ENABLED": "false",
            "WORKSPACE_ROOT": str(data_dir),
            "FOCUS_AGENT_SKILLS_ENABLED": "false",
            "AGENT_BRANCH_RECOMMENDATION_ENABLED": "false",
            "AGENT_BRANCH_DECISION_ENABLED": "true",
            "AGENT_BRANCH_DECISION_MODE": "execute",
            "AGENT_BRANCH_DECISION_SPLIT_THRESHOLD": "0.30",
            "NO_PROXY": "127.0.0.1,localhost",
            "PYTHONPATH": str(REPO_ROOT / "src"),
        }
    )
    log = (output_dir / "api.log").open("wb")
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, str(Path(__file__).resolve())],
        cwd=REPO_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    process._review_log = log  # type: ignore[attr-defined]
    try:
        wait_http(f"http://127.0.0.1:{port}/healthz")
    except Exception:
        stop_process(process)
        raise
    return process


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
    log = getattr(process, "_review_log", None)
    if log is not None:
        log.close()


def serve_fixture_api() -> None:
    import uvicorn
    from fastapi import Header, HTTPException

    from focus_agent.api.main import app

    # Only this isolated test entry point exposes setup; production has no such route.
    # V2 streaming does not schedule the legacy post-turn evaluator.
    @app.post("/__browser_fixture/audit/{thread_id}")
    def evaluate_audit(
        thread_id: str, payload: dict[str, str], x_fixture_secret: str = Header()
    ) -> dict[str, bool]:
        if x_fixture_secret != AUTH_SECRET:
            raise HTTPException(status_code=403)
        app.state.runtime.branch_decision_service.evaluate_thread_turn(
            thread_id=thread_id,
            root_thread_id=payload["root_thread_id"],
            user_id="browser-review",
            request_id="browser-audit",
        )
        return {"evaluated": True}

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["API_PORT"]))


if __name__ == "__main__":
    serve_fixture_api()
