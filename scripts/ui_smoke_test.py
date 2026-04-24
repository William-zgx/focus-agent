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


DEFAULT_APP_URL = "http://127.0.0.1:5173/app/"
DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/healthz"
DEFAULT_MESSAGE = "请简短回复 OK"


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
  const bodyText = () => document.body?.innerText || '';
  const messageBubbles = (selector) =>
    Array.from(document.querySelectorAll(selector))
      .map((item) => item.textContent?.trim() || '')
      .filter(Boolean);
  const latestUserBubbleText = () => {{
    const values = messageBubbles('.fa-message-row.is-user .fa-message-bubble, .fa-message-row.user .fa-message-bubble');
    return values.at(-1) || '';
  }};
  const latestAssistantBubbleText = () => {{
    const values = messageBubbles('.fa-message-row.is-assistant .fa-message-bubble, .fa-message-row.assistant .fa-message-bubble');
    return values.at(-1) || '';
  }};
  const includesAny = (text, labels) => labels.some((label) => text.includes(label));
  const buttonMatches = (item, labels) => {{
    const candidates = [
      item.textContent?.trim() || '',
      item.getAttribute('aria-label') || '',
      item.getAttribute('title') || '',
    ].map((value) => value.trim());
    return labels.some((label) => candidates.includes(label));
  }};
  const findButton = (...labels) => Array.from(document.querySelectorAll('button')).find(
    (item) => buttonMatches(item, labels)
  );
  const findEnabledButton = (...labels) => Array.from(document.querySelectorAll('button')).find(
    (item) => buttonMatches(item, labels) && !item.disabled
  );
  const clickButton = (...labels) => {{
    const button = findButton(...labels);
    if (!button) throw new Error('Missing button: ' + labels.join(' / '));
    button.click();
  }};
  const clickEnabledButton = (...labels) => {{
    const button = findEnabledButton(...labels);
    if (!button) throw new Error('Missing enabled button: ' + labels.join(' / '));
    button.click();
  }};
  const openReviewFlow = async () => {{
    const entryLabels = ['Generate conclusion', '生成结论', '生成分支结论'];
    const readyLabels = ['Merge conclusion', '合并结论'];
    const proposalLabels = ['Generate conclusion', '生成带回结论'];
    await waitFor(() => findEnabledButton(...entryLabels), 20000, 'review entry action');
    clickEnabledButton(...entryLabels);
    await waitFor(() => {{
      if (location.pathname.endsWith('/review')) return 'route-ready';
      if (findEnabledButton(...readyLabels)) return 'proposal-ready';
      if (findEnabledButton(...proposalLabels)) return 'proposal-modal';
      return '';
    }}, 120000, 'review route or prepared proposal');
    if (!location.pathname.endsWith('/review')) {{
      if (findEnabledButton(...proposalLabels)) {{
        clickEnabledButton(...proposalLabels);
      }} else {{
        clickEnabledButton(...readyLabels);
      }}
      await waitFor(() => location.pathname.endsWith('/review'), 120000, 'review route');
    }}
  }};
  const setTextareaValue = (value) => {{
    const textarea = document.querySelector('textarea');
    if (!textarea) throw new Error('Message composer was not found.');
    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
    descriptor?.set?.call(textarea, value);
    textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
    return textarea;
  }};
  const hasThreadRoute = () => /^\/app\/c\/[^/]+\/t\/[^/]+/.test(location.pathname);
  const result = {{}};
  const newConversationLabels = ['New', 'New conversation', '新建', '新建对话'];
  const newBranchLabels = ['Fork branch', 'New branch', '新建分支', '创建分支'];
  const sendLabels = ['Send', 'Send message', '发送', '发送消息'];
  const failedConversationLabels = ['Failed to load conversations.', '加载对话失败。'];
  const loadingConversationLabels = ['Loading conversations...', '正在加载对话...'];
  const mergeFormLabels = ['Summary', '摘要'];
  await waitFor(() => findButton(...newConversationLabels), 20000, 'conversation sidebar');
  result.title = document.title;
  result.url = location.href;
  await waitFor(
    () =>
      includesAny(bodyText(), failedConversationLabels) ||
      hasThreadRoute() ||
      !includesAny(bodyText(), loadingConversationLabels),
    20000,
    'initial conversation state'
  );
  if (includesAny(bodyText(), failedConversationLabels)) {{
    throw new Error('Conversation list failed to load.');
  }}
  const currentThreadPath = location.pathname;
  const originalPrompt = window.prompt;
  window.prompt = () => 'Smoke Test';
  try {{
    clickButton(...newConversationLabels);
  }} finally {{
    window.prompt = originalPrompt;
  }}
  await waitFor(
    () => hasThreadRoute() && location.pathname !== currentThreadPath,
    20000,
    'new conversation route'
  );
  result.threadPath = location.pathname;
  await waitFor(
    () => document.querySelector('textarea') && findButton(...newBranchLabels),
    20000,
    'thread page ready'
  );
  setTextareaValue(smokeMessage);
  await waitFor(() => {{
    const button = findButton(...sendLabels);
    return button && !button.disabled ? button : null;
  }}, 5000, 'send button enabled');
  clickButton(...sendLabels);
  await waitFor(() => latestUserBubbleText().includes(smokeMessage), 10000, 'user message render');
  const finalText = await waitFor(() => {{
    const text = latestAssistantBubbleText();
    const hasAssistantReply =
      text &&
      text !== 'Focus Agent' &&
      !text.includes('<｜DSML｜') &&
      !text.includes('function_calls');
    if (hasAssistantReply) {{
      return text;
    }}
    return '';
  }}, 90000, 'assistant natural-language response');
  result.lastResponseText = finalText;
  await waitFor(() => {{
    const button = findEnabledButton(...newBranchLabels);
    return button || null;
  }}, 20000, 'new branch button enabled');
  clickEnabledButton(...newBranchLabels);
  await waitFor(() => hasThreadRoute() && location.pathname !== result.threadPath, 20000, 'branch route');
  result.branchPath = location.pathname;
  await openReviewFlow();
  await waitFor(() => includesAny(bodyText(), mergeFormLabels), 120000, 'merge review form');
  result.reviewPath = location.pathname;
  return JSON.stringify(result);
}})()
"""


def collect_browser_diagnostics(client: CdpWebSocket) -> dict[str, object]:
    diagnostic_response = client.send(
        "Runtime.evaluate",
        {
            "expression": """
JSON.stringify({
  body: document.body?.innerText || "",
  fetches: window.__faFetches || [],
  errors: window.__faErrors || [],
  console: window.__faConsole || [],
})
""",
            "awaitPromise": True,
            "returnByValue": True,
        },
    )
    diagnostic_result = (
        diagnostic_response.get("result", {})
        if isinstance(diagnostic_response.get("result"), dict)
        else {}
    )
    diagnostic_payload = diagnostic_result.get("value", "")
    if isinstance(diagnostic_payload, str) and diagnostic_payload.strip():
        parsed = json.loads(diagnostic_payload)
        if isinstance(parsed, dict):
            return parsed
    return {}


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
        target = create_page_target(port, "about:blank")
        websocket_url = str(target.get("webSocketDebuggerUrl") or "")
        if not websocket_url:
            raise RuntimeError(f"Missing webSocketDebuggerUrl in target payload: {target!r}")

        client = CdpWebSocket(websocket_url)
        try:
            client.send("Page.enable")
            client.send("Runtime.enable")
            client.send(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
window.__faFetches = [];
window.__faErrors = [];
window.__faConsole = [];
const __faConsoleError = console.error.bind(console);
console.error = (...args) => {
  window.__faConsole.push(args.map((item) => String(item)));
  __faConsoleError(...args);
};
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

            raw_value = (
                response.get("result", {})
                if isinstance(response.get("result"), dict)
                else {}
            )
            payload = raw_value.get("value", "")
            if not isinstance(payload, str) or not payload.strip():
                diagnostics = {}
                try:
                    diagnostics = collect_browser_diagnostics(client)
                except Exception as exc:  # noqa: BLE001
                    diagnostics = {"diagnostic_error": str(exc)}
                raise RuntimeError(f"Unexpected smoke-test payload: {response!r}; diagnostics={diagnostics!r}")

            result = json.loads(payload)
            if result.get("__error"):
                raise RuntimeError(str(result["__error"]))
            return result
        finally:
            client.close()
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
