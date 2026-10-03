from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

from focus_agent.api.route_utils import lifespan as lifespan_module
from focus_agent.runtime.lifecycle import (
    is_shutting_down,
    register_shutdown_hook,
    reset_shutdown_state,
    trigger_shutdown,
    unregister_shutdown_hook,
)


def test_trigger_shutdown_sets_flag_and_runs_registered_hooks() -> None:
    reset_shutdown_state()
    calls: list[str] = []

    async def hook() -> None:
        calls.append("hook")

    register_shutdown_hook(hook)
    try:
        asyncio.run(trigger_shutdown())
        assert is_shutting_down() is True
        assert calls == ["hook"]
    finally:
        unregister_shutdown_hook(hook)
        reset_shutdown_state()


def test_reset_shutdown_state_clears_drain_flag_between_app_lifespans() -> None:
    reset_shutdown_state()
    assert is_shutting_down() is False


def test_app_lifespan_leaves_uvicorn_signal_handlers_alone(monkeypatch) -> None:
    signal_calls: list[object] = []

    class FakeSettings:
        @classmethod
        def from_env(cls):
            return cls()

    class FakeRuntime:
        def start_durable_background_worker(self, _chat_service) -> None:
            return None

        def close(self) -> None:
            return None

    async def close_async_http_client() -> None:
        return None

    monkeypatch.setattr(lifespan_module, "Settings", FakeSettings)
    monkeypatch.setattr(lifespan_module, "validate_jwt_secret_for_environment", lambda _s: None)
    monkeypatch.setattr(lifespan_module, "create_runtime", lambda _s: FakeRuntime())
    monkeypatch.setattr(lifespan_module, "ChatService", lambda _runtime: object())
    monkeypatch.setattr(lifespan_module, "close_async_http_client", close_async_http_client)
    monkeypatch.setattr(lifespan_module, "close_sync_http_client", lambda: None)
    monkeypatch.setattr(lifespan_module, "shutdown_thread_pool", lambda: None)
    monkeypatch.setattr(
        lifespan_module,
        "install_signal_handlers",
        lambda *args, **kwargs: signal_calls.append((args, kwargs)),
        raising=False,
    )

    async def run_lifespan() -> None:
        app = SimpleNamespace(state=SimpleNamespace())
        async with lifespan_module.app_lifespan(app):
            assert app.state.runtime is not None

    try:
        asyncio.run(run_lifespan())
    finally:
        reset_shutdown_state()

    assert signal_calls == []


def test_uvicorn_sigterm_stops_isolated_child_process(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cleanup_marker = tmp_path / "runtime-closed"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    child_code = textwrap.dedent(
        """
        import sys
        from pathlib import Path

        import uvicorn
        from fastapi import FastAPI

        import focus_agent.api.route_utils.lifespan as lifespan_module


        class FakeSettings:
            @classmethod
            def from_env(cls):
                return cls()


        class FakeRuntime:
            def close(self):
                Path(sys.argv[2]).write_text("closed", encoding="utf-8")
                return None

            def start_durable_background_worker(self, _chat_service):
                return None


        class FakeChatService:
            def __init__(self, _runtime):
                pass


        async def _close_async_http_client():
            return None


        lifespan_module.Settings = FakeSettings
        lifespan_module.validate_jwt_secret_for_environment = lambda _settings: None
        lifespan_module.create_runtime = lambda _settings: FakeRuntime()
        lifespan_module.ChatService = FakeChatService
        lifespan_module.close_async_http_client = _close_async_http_client
        lifespan_module.close_sync_http_client = lambda: None
        lifespan_module.shutdown_thread_pool = lambda: None

        app = FastAPI(lifespan=lifespan_module.app_lifespan)

        @app.get("/probe")
        async def probe():
            return {"ok": True}


        uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="critical")
        """
    )
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = str(repo_root / "src")
    process = subprocess.Popen(
        [sys.executable, "-c", child_code, str(port), str(cleanup_marker)],
        cwd=repo_root,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout is not None else ""
                raise AssertionError(f"isolated uvicorn child exited early: {output}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/probe", timeout=0.5
                        ) as response:
                            if response.status == 200:
                                break
                    except (OSError, URLError):
                        pass
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("isolated uvicorn child did not start")

        process.send_signal(signal.SIGTERM)
        try:
            return_code = process.wait(timeout=5.0)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError("isolated uvicorn child did not stop after SIGTERM") from exc
        assert return_code in {0, -signal.SIGTERM}
        assert cleanup_marker.read_text(encoding="utf-8") == "closed"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
