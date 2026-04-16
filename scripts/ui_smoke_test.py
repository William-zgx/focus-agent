from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from urllib import parse as urllib_parse
from urllib import request as urllib_request


DEFAULT_APP_URL = "http://127.0.0.1:8000/app/zh"
DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/healthz"
DEFAULT_MESSAGE = "你好，做一个 UI 冒烟测试，简短回复 OK 即可"


def _http_get_json(url: str) -> object:
    with urllib_request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_request_json(url: str, *, method: str) -> object:
    req = urllib_request.Request(url, method=method)
    with urllib_request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_health(url: str) -> None:
    payload = _http_get_json(url)
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise RuntimeError(f"Health check failed: {payload!r}")


def resolve_chrome_path(explicit: str | None) -> str:
    if explicit:
        return explicit

    candidates = (
        os.environ.get("CHROME_PATH"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("Google Chrome was not found. Pass --chrome-path or set CHROME_PATH.")


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_devtools(port: int, *, timeout_seconds: float = 15.0) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            payload = _http_get_json(f"http://127.0.0.1:{port}/json/version")
            if isinstance(payload, dict):
                return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for Chrome DevTools on port {port}: {last_error}")


def create_page_target(port: int, url: str) -> dict[str, object]:
    quoted_url = urllib_parse.quote(url, safe="")
    payload = _http_request_json(f"http://127.0.0.1:{port}/json/new?{quoted_url}", method="PUT")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected /json/new response: {payload!r}")
    return payload


class CdpWebSocket:
    def __init__(self, websocket_url: str):
        parsed = urllib_parse.urlparse(websocket_url)
        self._host = parsed.hostname or "127.0.0.1"
        self._port = int(parsed.port or 80)
        self._path = parsed.path or "/"
        if parsed.query:
            self._path += f"?{parsed.query}"
        self._sock = socket.create_connection((self._host, self._port), timeout=30)
        self._sock.settimeout(180)
        self._handshake()
        self._next_id = 0

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {self._host}:{self._port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        self._sock.sendall(request)
        response = self._sock.recv(4096)
        status_line = response.split(b"\r\n", 1)[0]
        if b"101" not in status_line:
            raise RuntimeError(response.decode("latin1", errors="replace"))

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def _recv_exact(self, size: int) -> bytes:
        buffer = bytearray()
        while len(buffer) < size:
            chunk = self._sock.recv(size - len(buffer))
            if not chunk:
                raise RuntimeError("WebSocket closed unexpectedly.")
            buffer.extend(chunk)
        return bytes(buffer)

    def _recv_frame(self) -> bytes:
        first_two = self._recv_exact(2)
        opcode = first_two[0] & 0x0F
        payload_length = first_two[1] & 0x7F
        masked = bool(first_two[1] & 0x80)
        if payload_length == 126:
            payload_length = struct.unpack("!H", self._recv_exact(2))[0]
        elif payload_length == 127:
            payload_length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(payload_length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 0x8:
            raise RuntimeError("WebSocket closed by peer.")
        return payload

    def send(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self._next_id += 1
        message_id = self._next_id
        body = json.dumps({"id": message_id, "method": method, "params": params or {}}).encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(body)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.extend([0x80 | 126])
            header.extend(struct.pack("!H", length))
        else:
            header.extend([0x80 | 127])
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        masked_payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(body))
        self._sock.sendall(bytes(header) + masked_payload)

        while True:
            message = json.loads(self._recv_frame().decode("utf-8"))
            if message.get("id") != message_id:
                continue
            error = message.get("error")
            if error:
                raise RuntimeError(str(error))
            result = message.get("result")
            return result if isinstance(result, dict) else {}


def build_smoke_expression(message: str) -> str:
    encoded_message = json.dumps(message, ensure_ascii=False)
    return rf"""
(async () => {{
  const smokeMessage = {encoded_message};
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, timeout = 20000, label = 'condition') => {{
    const started = Date.now();
    while (Date.now() - started < timeout) {{
      try {{
        const value = await predicate();
        if (value) return value;
      }} catch {{}}
      await sleep(100);
    }}
    throw new Error('Timed out waiting for ' + label);
  }};
  const text = (selector) => document.querySelector(selector)?.textContent?.trim() || '';
  const result = {{}};
  await waitFor(() => document.getElementById('composer-model-trigger'), 20000, 'model trigger');
  result.title = document.title;
  result.url = location.href;
  result.skillsButtonPresent = Boolean(document.getElementById('open-skills'));
  document.getElementById('composer-model-trigger').click();
  await waitFor(() => !document.getElementById('composer-model-panel')?.hidden, 20000, 'model panel open');
  result.modelPanelOpened = true;
  result.modelLabel = text('#composer-model-trigger-label');
  result.modelProvider = text('#composer-model-trigger-provider');
  result.modelOptionsCount = document.querySelectorAll('#composer-model-list > *').length;
  document.getElementById('composer-model-trigger').click();
  const composer = document.getElementById('stream-message');
  composer.value = smokeMessage;
  composer.dispatchEvent(new Event('input', {{ bubbles: true }}));
  document.getElementById('open-stream').click();
  await waitFor(() => document.querySelectorAll('.message-row.user').length > 0, 10000, 'user message render');
  const finalText = await waitFor(() => {{
    const rows = Array.from(document.querySelectorAll('.message-row.assistant .message-bubble, .message-row.system .message-bubble'));
    const last = rows.at(-1);
    const value = last && last.textContent.trim().length > 0 ? last.textContent.trim() : '';
    if (value && !value.includes('<｜DSML｜') && !value.includes('function_calls')) {{
      return value;
    }}
    return '';
  }}, 90000, 'assistant or system natural-language response');
  const responseRows = Array.from(document.querySelectorAll('.message-row.assistant, .message-row.system'));
  const lastRow = responseRows.at(-1);
  result.lastResponseText = finalText;
  result.responseRole = lastRow?.className || '';
  result.statusText = document.getElementById('status-text')?.textContent?.trim() || '';
  if (result.skillsButtonPresent) {{
    throw new Error('Skills directory button is still rendered on the page.');
  }}
  return JSON.stringify(result);
}})()
"""


def run_ui_smoke_test(
    *,
    app_url: str,
    health_url: str,
    chrome_path: str,
    message: str,
    keep_open: bool,
) -> dict[str, object]:
    ensure_health(health_url)
    port = pick_free_port()
    temp_dir = tempfile.TemporaryDirectory(prefix="focus-agent-ui-smoke-")
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
        target = create_page_target(port, app_url)
        websocket_url = str(target.get("webSocketDebuggerUrl") or "")
        if not websocket_url:
            raise RuntimeError(f"Missing webSocketDebuggerUrl in target payload: {target!r}")

        client = CdpWebSocket(websocket_url)
        try:
            client.send("Page.enable")
            client.send("Runtime.enable")
            client.send("Page.navigate", {"url": app_url})
            time.sleep(2.0)
            response = client.send(
                "Runtime.evaluate",
                {
                    "expression": build_smoke_expression(message),
                    "awaitPromise": True,
                    "returnByValue": True,
                },
            )
        finally:
            client.close()

        raw_value = (
            response.get("result", {})
            if isinstance(response.get("result"), dict)
            else {}
        )
        payload = raw_value.get("value", "")
        if not isinstance(payload, str) or not payload.strip():
            raise RuntimeError(f"Unexpected smoke-test payload: {response!r}")

        result = json.loads(payload)
        if result.get("__error"):
            raise RuntimeError(str(result["__error"]))
        return result
    finally:
        if keep_open:
            print(f"Chrome remains open with user data dir: {temp_dir.name}", file=sys.stderr)
        else:
            chrome_process.terminate()
            try:
                chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_process.kill()
                chrome_process.wait(timeout=5)
            temp_dir.cleanup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real-browser UI smoke test against the local Focus Agent app.")
    parser.add_argument("--app-url", default=DEFAULT_APP_URL, help="App URL to open in Chrome.")
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL, help="Health endpoint to verify before launching Chrome.")
    parser.add_argument("--chrome-path", default=None, help="Path to the Chrome executable.")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="Chat message to send during the smoke test.")
    parser.add_argument("--keep-open", action="store_true", help="Keep the dedicated Chrome window open after the smoke test.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_ui_smoke_test(
        app_url=str(args.app_url),
        health_url=str(args.health_url),
        chrome_path=resolve_chrome_path(args.chrome_path),
        message=str(args.message),
        keep_open=bool(args.keep_open),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
