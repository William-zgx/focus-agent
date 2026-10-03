#!/usr/bin/env python3
"""Real-Chromium regression flow for the review fixes.

The script owns a temporary API process, SQLite state directory, and local
OpenAI-compatible model fixture.  It deliberately uses the built web app and
the repository's raw CDP client so the checks cover browser state, HTTP calls,
and persisted thread state together.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from observability_ui_browser import run_expression
from review_fixes_browser_fixture import (
    AUTH_SECRET,
    ModelFixture,
    free_port,
    start_api,
    stop_process,
)
from ui_smoke_test import (
    CdpWebSocket,
    chrome_runtime_flags,
    create_page_target,
    resolve_chrome_path,
    wait_for_devtools,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def http_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = urllib_request.Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib_request.urlopen(request, timeout=15) as response:
            return int(response.status), json.loads(response.read().decode() or "null")
    except urllib_error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            pass
        return int(exc.code), body


def evaluate(client: CdpWebSocket, expression: str) -> Any:
    wrapped = f"""
    (async () => {{
      const value = await ({expression});
      return JSON.stringify(value === undefined ? null : value);
    }})()
    """
    try:
        return run_expression(client, wrapped)
    except Exception as exc:
        raise RuntimeError(f"browser expression failed: {exc}") from exc


def screenshot(client: CdpWebSocket, path: Path) -> None:
    payload = client.send("Page.captureScreenshot", {"format": "png"}).get("data")
    if not isinstance(payload, str):
        raise RuntimeError("Chrome did not return a screenshot")
    path.write_bytes(base64.b64decode(payload))


def install_browser_probe(client: CdpWebSocket, token: str) -> None:
    client.send("Page.enable")
    client.send("Runtime.enable")
    client.send(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": f"localStorage.setItem('focus-agent-token', {json.dumps(token)});"
            "window.__reviewFetches=[]; window.__reviewErrors=[];"
            "const reviewFetch=window.fetch.bind(window);"
            "window.fetch=async (...args)=>{const input=args[0],init=args[1]||{};"
            "const url=typeof input==='string'?input:(input&&input.url)||String(input);"
            "const item={stage:'start',url,method:init.method||'GET',body:typeof init.body==='string'?init.body.slice(0,20000):null,time:Date.now()};"
            "window.__reviewFetches.push(item); try{const response=await reviewFetch(...args);"
            "window.__reviewFetches.push({stage:'end',url,status:response.status,ok:response.ok,time:Date.now()});return response;"
            "}catch(error){window.__reviewFetches.push({stage:'error',url,message:String(error),time:Date.now()});throw error;}};"
            "addEventListener('error',e=>window.__reviewErrors.push({type:'error',message:e.message}));"
            "addEventListener('unhandledrejection',e=>window.__reviewErrors.push({type:'unhandledrejection',message:String(e.reason)}));",
        },
    )


def browser_ready(client: CdpWebSocket, url: str) -> None:
    client.send("Page.navigate", {"url": url})
    expression = """
    (async () => {
      const started = Date.now();
      while (Date.now() - started < 30000) {
        if (document.querySelector('textarea') && document.body) return true;
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      throw new Error('thread composer did not render');
    })()
    """
    if evaluate(client, expression) is not True:
        raise RuntimeError("browser did not render the thread composer")


def spa_navigate(client: CdpWebSocket, url: str) -> None:
    expression = f"""
    (() => {{
      const target = new URL({json.dumps(url)});
      if (location.pathname === target.pathname) return true;
      const nodes = Array.from(document.querySelectorAll('.fa-branch-graph-node'));
      if (nodes.length !== 2) throw new Error('expected the root and handoff branch in the tree');
      const button = nodes.find((node) => !node.classList.contains('is-active'));
      if (!button) throw new Error('inactive branch button missing');
      button.click();
      return true;
    }})()
    """
    if evaluate(client, expression) is not True:
        raise RuntimeError(f"SPA navigation did not reach {url}")
    wait_browser(
        client,
        f"location.pathname === new URL({json.dumps(url)}).pathname",
        "branch tree navigation",
    )


def thread_url(base_url: str, thread_id: str, root_thread_id: str | None = None) -> str:
    return f"{base_url.rstrip('/')}/app/c/{root_thread_id or thread_id}/t/{thread_id}?lang=en"


def send_from_browser(client: CdpWebSocket, message: str) -> dict[str, Any]:
    encoded = json.dumps(message, ensure_ascii=False)
    expression = f"""
    (async () => {{
      const message = {encoded};
      const buttons = Array.from(document.querySelectorAll('button'));
      const match = (item, labels) => labels.some((label) =>
        [item.textContent || '', item.getAttribute('aria-label') || '', item.getAttribute('title') || '']
          .map((value) => value.trim()).includes(label));
      const textarea = document.querySelector('textarea');
      if (!textarea) throw new Error('composer textarea missing');
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
      setter?.call(textarea, message);
      textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
      const send = () => Array.from(document.querySelectorAll('button')).find((item) =>
        match(item, ['Send', 'Send message', '发送', '发送消息']) && !item.disabled);
      const started = Date.now();
      while (Date.now() - started < 10000 && !send()) await new Promise((resolve) => setTimeout(resolve, 50));
      const button = send();
      if (!button) throw new Error('send button did not enable');
      button.click();
      return {{ message, startedAt: Date.now() }};
    }})()
    """
    result = evaluate(client, expression)
    return result if isinstance(result, dict) else {"message": message}


def wait_browser(client: CdpWebSocket, condition: str, label: str, timeout: int = 30000) -> Any:
    expression = f"""
    (async () => {{
      const started = Date.now();
      while (Date.now() - started < {timeout}) {{
        if ({condition}) return true;
        await new Promise((resolve) => setTimeout(resolve, 100));
      }}
      throw new Error('timed out waiting for {label}');
    }})()
    """
    return evaluate(client, expression)


def browser_fetches(client: CdpWebSocket) -> list[dict[str, Any]]:
    result = evaluate(client, "window.__reviewFetches || []")
    return result if isinstance(result, list) else []


def body_text(client: CdpWebSocket) -> str:
    result = evaluate(client, "document.body?.innerText || ''")
    return str(result or "")


def persist_snapshot(base_url: str, thread_id: str, token: str) -> dict[str, Any]:
    status, payload = http_json(base_url, f"/v1/threads/{thread_id}", token=token)
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"thread state failed ({status}): {payload!r}")
    return payload


def message_count(state: dict[str, Any], content: str) -> int:
    return sum(
        1
        for item in state.get("messages", [])
        if isinstance(item, dict) and str(item.get("content") or "") == content
    )


def action_by_id(state: dict[str, Any], action_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in state.get("branch_actions", []) if item.get("action_id") == action_id),
        None,
    )


def run_flow(*, chrome_path: str, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix="focus-agent-review-browser-data-"))
    model_log: list[dict[str, Any]] = []
    fixture = ModelFixture(free_port(), model_log)
    api: subprocess.Popen[bytes] | None = None
    chrome: subprocess.Popen[bytes] | None = None
    client: CdpWebSocket | None = None
    result: dict[str, Any] = {"status": "failed", "output_dir": str(output_dir), "evidence": {}}
    try:
        fixture.start()
        api_port = free_port()
        api = start_api(
            port=api_port, fixture_port=fixture.port, data_dir=data_dir, output_dir=output_dir
        )
        base_url = f"http://127.0.0.1:{api_port}"
        ready_status, readiness = http_json(base_url, "/readyz")
        if ready_status != 200 or not readiness.get("ready"):
            raise RuntimeError(f"isolated API was not ready: {readiness}")
        token_status, token_payload = http_json(
            base_url,
            "/v1/auth/demo-token",
            method="POST",
            payload={
                "user_id": "browser-review",
                "tenant_id": "browser-review",
                "scopes": ["chat", "branches"],
            },
        )
        if token_status != 200 or not isinstance(token_payload, dict):
            raise RuntimeError(f"demo token failed ({token_status}): {token_payload!r}")
        token = str(token_payload["access_token"])
        conversation_status, conversation = http_json(
            base_url,
            "/v1/conversations",
            method="POST",
            token=token,
            payload={"title": "Browser review flow"},
        )
        if conversation_status not in {200, 201} or not isinstance(conversation, dict):
            raise RuntimeError(f"conversation creation failed: {conversation!r}")
        thread_id = str(conversation.get("root_thread_id") or conversation.get("thread_id"))
        if not thread_id:
            raise RuntimeError(f"conversation omitted thread id: {conversation!r}")

        cdp_port = free_port()
        user_data = Path(tempfile.mkdtemp(prefix="focus-agent-review-browser-chrome-"))
        chrome = subprocess.Popen(  # noqa: S603
            [
                chrome_path,
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_data}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-search-engine-choice-screen",
                "--window-size=1440,1000",
                *chrome_runtime_flags(),
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        wait_for_devtools(cdp_port)
        target = create_page_target(cdp_port, "about:blank")
        websocket_url = str(target.get("webSocketDebuggerUrl") or "")
        if not websocket_url:
            raise RuntimeError(f"Chrome target omitted websocket: {target!r}")
        client = CdpWebSocket(websocket_url, timeout_seconds=180)
        install_browser_probe(client, token)
        browser_ready(client, thread_url(base_url, thread_id))
        screenshot(client, output_dir / "01-thread-ready.png")

        evidence: dict[str, Any] = {
            "api_base_url": base_url,
            "thread_id": thread_id,
            "readiness": readiness,
        }
        result["evidence"] = evidence
        ordinary = "普通发送 SLOW_BROWSER"
        send_from_browser(client, ordinary)
        wait_browser(
            client,
            "Boolean(document.querySelector('.fa-composer-shell.is-streaming') || document.querySelector('button[aria-label=\"Stop generation\"]') || document.querySelector('button[aria-label=\"停止生成\"]'))",
            "ordinary processing state",
            10000,
        )
        screenshot(client, output_dir / "02-ordinary-processing.png")
        wait_browser(
            client,
            "!(document.querySelector('.fa-composer-shell.is-streaming'))",
            "ordinary completion",
            30000,
        )
        wait_browser(
            client,
            "(document.body.innerText || '').includes('OK')",
            "ordinary assistant response",
            30000,
        )
        ordinary_state = persist_snapshot(base_url, thread_id, token)
        ordinary_count = message_count(ordinary_state, ordinary)
        if ordinary_count != 1:
            raise RuntimeError(f"ordinary user message persisted {ordinary_count} times")
        evidence["ordinary_send"] = {
            "processing_seen": True,
            "message_persisted_count": ordinary_count,
            "state": ordinary_state,
        }

        failure = "FAIL_BROWSER deterministic failure"
        send_from_browser(client, failure)
        wait_browser(
            client,
            "(document.body.innerText || '').includes('This turn failed') || (document.body.innerText || '').includes('本轮执行失败')",
            "failure rendering",
            30000,
        )
        screenshot(client, output_dir / "03-failure.png")
        failure_state = persist_snapshot(base_url, thread_id, token)
        failure_provider_status = any(item.get("status") == 500 for item in model_log)
        if not failure_provider_status:
            raise RuntimeError(
                "failure flow did not reach the deterministic provider with HTTP 500"
            )
        evidence["failure"] = {
            "ui_text": "This turn failed"
            if "This turn failed" in body_text(client)
            else "本轮执行失败",
            "provider_error_seen": failure_provider_status,
            "state": failure_state,
        }

        cancel = "SLOW_BROWSER cancel this turn"
        send_from_browser(client, cancel)
        wait_browser(
            client,
            "Boolean(document.querySelector('.fa-composer-shell.is-streaming'))",
            "cancel processing state",
            10000,
        )
        deadline = time.time() + 15
        while not any(
            item.get("model") == "browser-smoke" and cancel in item.get("user_message", "")
            for item in model_log
        ):
            if time.time() >= deadline:
                raise RuntimeError("cancel task did not reach the local model")
            time.sleep(0.1)
        screenshot(client, output_dir / "04-cancel-processing.png")
        stop_expression = """
        (() => {
          const button = Array.from(document.querySelectorAll('button')).find((item) =>
            ['Stop generation', '停止生成'].includes((item.getAttribute('aria-label') || '').trim())
          );
          if (!button) return false;
          button.click();
          return true;
        })()
        """
        if evaluate(client, stop_expression) is not True:
            raise RuntimeError("stop button was not available for cancellation")
        wait_browser(
            client,
            "!document.querySelector('.fa-composer-shell.is-streaming')",
            "cancel cleanup",
            15000,
        )
        screenshot(client, output_dir / "05-cancelled.png")
        # Cancellation is cooperative: let the in-flight model call unwind
        # before starting another turn that would contend for its thread lease.
        deadline = time.time() + 15
        while not any(
            item.get("model") == "browser-smoke"
            and item.get("request_finished")
            and cancel in item.get("user_message", "")
            for item in model_log
        ):
            if time.time() >= deadline:
                raise RuntimeError("cancelled provider request did not unwind")
            time.sleep(0.1)
        cancel_fetches = browser_fetches(client)
        run_cancel_urls = [
            str(item.get("url"))
            for item in cancel_fetches
            if item.get("stage") == "end"
            and "/runs/" in str(item.get("url"))
            and "/threads/" not in str(item.get("url"))
            and str(item.get("url")).endswith("/cancel")
        ]
        if not run_cancel_urls:
            raise RuntimeError("active run cancellation request was not observed")
        cancelled_run_id = run_cancel_urls[-1].split("/runs/")[1].split("/")[0]
        run_status, cancelled_run = http_json(base_url, f"/v2/runs/{cancelled_run_id}", token=token)
        if run_status != 200 or cancelled_run.get("run", {}).get("status") != "interrupted":
            raise RuntimeError(f"cancelled run did not become interrupted: {cancelled_run}")
        cancel_state = persist_snapshot(base_url, thread_id, token)
        cancel_endpoint_seen = any(
            item.get("stage") == "end" and "/runs/cancel" in str(item.get("url"))
            for item in cancel_fetches
        )
        provider_client_cancelled = any(item.get("client_cancelled") for item in model_log)
        if not cancel_endpoint_seen:
            raise RuntimeError(
                f"cancel flow lacked cancellation evidence: endpoint={cancel_endpoint_seen}, provider={provider_client_cancelled}"
            )
        evidence["cancel"] = {
            "run_status": cancelled_run["run"]["status"],
            "cancel_endpoint_seen": cancel_endpoint_seen,
            "provider_client_cancelled": provider_client_cancelled,
            "state": cancel_state,
        }

        branch_message = "请新建子分支：浏览器验证，继续验证 HANDOFF_SLOW carried message"
        send_from_browser(client, branch_message)
        wait_browser(
            client,
            "document.querySelector('.fa-branch-action-card.is-pending')",
            "pending branch action",
            30000,
        )
        screenshot(client, output_dir / "06-branch-action-pending.png")
        source_state = persist_snapshot(base_url, thread_id, token)
        actions = [
            item
            for item in source_state.get("branch_actions", [])
            if item.get("status") == "pending"
        ]
        if len(actions) != 1:
            raise RuntimeError(f"expected one persisted pending branch action: {actions!r}")
        if actions[0].get("recommendation_user_visible") is False:
            raise RuntimeError("handoff action unexpectedly became audit-only")
        action_id = str(actions[0]["action_id"])
        action_button = evaluate(
            client,
            "(() => Array.from(document.querySelectorAll('.fa-branch-action-card.is-pending button')).find((item) => !item.disabled)?.textContent || '')()",
        )
        if not action_button:
            raise RuntimeError("branch action did not expose an enabled confirmation button")
        evaluate(
            client,
            "(() => Array.from(document.querySelectorAll('.fa-branch-action-card.is-pending button')).find((item) => !item.disabled)?.click() || true)()",
        )
        wait_browser(
            client,
            "location.pathname.includes('/t/') && location.pathname !== "
            + json.dumps(f"/app/c/{thread_id}/t/{thread_id}"),
            "branch navigation",
            30000,
        )
        target_thread_id = str(evaluate(client, "location.pathname.split('/t/')[1].split('/')[0]"))
        wait_browser(
            client,
            "Boolean(document.querySelector('.fa-composer-shell.is-streaming'))",
            "carried handoff processing",
            30000,
        )
        screenshot(client, output_dir / "07-carried-handoff-processing.png")
        target_state_during = persist_snapshot(base_url, target_thread_id, token)
        handoff = str(actions[0]["handoff_message"])
        dom_handoff_count = int(
            evaluate(
                client,
                f"Array.from(document.querySelectorAll('.fa-message-row.is-user .fa-message-bubble, .fa-message-row.user .fa-message-bubble')).filter((item) => (item.textContent || '').trim() === {json.dumps(handoff)}).length",
            )
        )
        wait_browser(
            client,
            "!document.querySelector('.fa-composer-shell.is-streaming')",
            "carried handoff completion",
            30000,
        )
        target_state = persist_snapshot(base_url, target_thread_id, token)
        if dom_handoff_count != 1:
            raise RuntimeError(f"optimistic handoff rendered {dom_handoff_count} copies")
        if (
            message_count(target_state_during, handoff) != 1
            or message_count(target_state, handoff) != 1
        ):
            raise RuntimeError("persisted handoff message was missing or duplicated")
        carried_fetch_seen = any(
            item.get("stage") == "start"
            and target_thread_id in str(item.get("url"))
            and "branch_handoff_auto_run" in str(item.get("body"))
            for item in browser_fetches(client)
        )
        if not carried_fetch_seen:
            raise RuntimeError("carried handoff stream request was not observed in the browser")
        if any(
            target_thread_id in str(item.get("url"))
            and str(item.get("url")).endswith("/runs/cancel")
            for item in browser_fetches(client)
        ):
            raise RuntimeError("source navigation incorrectly cancelled the target handoff")
        if not str(target_state.get("assistant_message") or "").startswith("OK"):
            raise RuntimeError("handoff target did not complete its answer")
        evidence["branch_handoff"] = {
            "action_id": action_id,
            "source_action": action_by_id(source_state, action_id),
            "target_thread_id": target_thread_id,
            "handoff_message": handoff,
            "dom_handoff_count_during_processing": dom_handoff_count,
            "persisted_handoff_count_during_processing": message_count(
                target_state_during, handoff
            ),
            "persisted_handoff_count_after_completion": message_count(target_state, handoff),
            "carried_request_seen": carried_fetch_seen,
            "target_state": target_state,
        }

        audit = "Please explore an alternative deterministic path"
        spa_navigate(client, thread_url(base_url, target_thread_id, thread_id))
        wait_browser(
            client,
            "location.pathname.includes(" + json.dumps(f"/t/{target_thread_id}") + ")",
            "audit route",
            15000,
        )
        wait_browser(client, "document.querySelector('textarea')", "audit composer", 15000)
        send_from_browser(client, audit)
        wait_browser(
            client,
            "!(document.querySelector('.fa-composer-shell.is-streaming'))",
            "audit source completion",
            30000,
        )
        setup_request = urllib_request.Request(
            f"{base_url}/__browser_fixture/audit/{target_thread_id}",
            data=json.dumps({"root_thread_id": thread_id}).encode(),
            headers={"Content-Type": "application/json", "X-Fixture-Secret": AUTH_SECRET},
            method="POST",
        )
        with urllib_request.urlopen(setup_request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError("audit fixture setup failed")
        audit_state = persist_snapshot(base_url, target_thread_id, token)
        audit_actions = [
            item
            for item in audit_state.get("branch_actions", [])
            if item.get("status") == "pending"
        ]
        if not audit_actions:
            raise RuntimeError(f"audit-only pending action was not persisted: {audit_state!r}")
        audit_action = next(
            (item for item in audit_actions if item.get("recommendation_user_visible") is False),
            None,
        )
        if audit_action is None:
            raise RuntimeError(
                f"pending action did not carry audit-only metadata: {audit_actions!r}"
            )
        result["browser_fetches_before_audit_reload"] = browser_fetches(client)
        browser_ready(client, thread_url(base_url, target_thread_id, thread_id))
        wait_browser(
            client,
            "document.querySelector('.fa-branch-action-card.is-pending')",
            "audit-only card",
            30000,
        )
        screenshot(client, output_dir / "08-audit-only-pending.png")
        disabled = bool(
            evaluate(
                client,
                "Boolean(Array.from(document.querySelectorAll('.fa-branch-action-card.is-pending button')).length && Array.from(document.querySelectorAll('.fa-branch-action-card.is-pending button')).every((item) => item.disabled))",
            )
        )
        if not disabled:
            raise RuntimeError("audit-only pending card exposed an enabled action button")
        audit_id = str(audit_action["action_id"])
        execute_status, execute_payload = http_json(
            base_url,
            f"/v1/threads/{target_thread_id}/branch-actions/{audit_id}/execute",
            method="POST",
            token=token,
        )
        if execute_status not in {400, 403}:
            raise RuntimeError(
                f"audit-only backend execute was not rejected: {execute_status} {execute_payload!r}"
            )
        audit_after_reject = persist_snapshot(base_url, target_thread_id, token)
        persisted_audit_action = action_by_id(audit_after_reject, audit_id)
        if not persisted_audit_action or persisted_audit_action.get("status") != "pending":
            raise RuntimeError("audit-only action changed after rejected execute")
        evidence["audit_only"] = {
            "dom_buttons_disabled": disabled,
            "execute_status": execute_status,
            "execute_payload": execute_payload,
            "still_pending_after_backend_reject": persisted_audit_action,
        }

        switch_source = "SLOW_BROWSER source switch probe"
        spa_navigate(client, thread_url(base_url, thread_id))
        wait_browser(
            client,
            "location.pathname.includes(" + json.dumps(f"/t/{thread_id}") + ")",
            "source switch route",
            15000,
        )
        wait_browser(client, "document.querySelector('textarea')", "source switch composer", 15000)
        send_from_browser(client, switch_source)
        wait_browser(
            client,
            "Boolean(document.querySelector('.fa-composer-shell.is-streaming'))",
            "source switch processing",
            10000,
        )
        deadline = time.time() + 15
        while not any(
            item.get("model") == "browser-smoke" and switch_source in item.get("user_message", "")
            for item in model_log
        ):
            if time.time() >= deadline:
                raise RuntimeError("source switch task did not reach the local model")
            time.sleep(0.1)
        source_fetch_count_before = len(browser_fetches(client))
        spa_navigate(client, thread_url(base_url, target_thread_id, thread_id))
        wait_browser(
            client,
            "location.pathname.includes(" + json.dumps(f"/t/{target_thread_id}") + ")",
            "target switch route",
            15000,
        )
        wait_browser(
            client,
            "window.__reviewFetches.some((item) => item.stage === 'end' && String(item.url).includes('/runs/cancel'))",
            "source cancellation request",
            15000,
        )
        switch_fetches = browser_fetches(client)[source_fetch_count_before:]
        source_cancel_seen = any(
            item.get("stage") == "end" and "/runs/cancel" in str(item.get("url"))
            for item in switch_fetches
        )
        if not source_cancel_seen:
            raise RuntimeError("SPA branch switch did not cancel the previous source stream")
        evidence["branch_switch"] = {
            "source_thread_id": thread_id,
            "target_thread_id": target_thread_id,
            "source_cancel_endpoint_seen": source_cancel_seen,
            "target_route": str(evaluate(client, "location.pathname")),
        }
        result["status"] = "passed"
        result["evidence"] = evidence
        result["model_fixture_requests"] = model_log
        result["browser_fetches"] = browser_fetches(client)
        result["browser_errors"] = evaluate(client, "window.__reviewErrors || []")
        (output_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result
    except Exception as exc:
        result["error"] = str(exc)
        if client is not None:
            result["browser_fetches"] = browser_fetches(client)
            screenshot(client, output_dir / "failure.png")
        raise
    finally:
        if client is not None:
            client.close()
        if chrome is not None and chrome.poll() is None:
            try:
                os.killpg(chrome.pid, signal.SIGTERM)
                chrome.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(chrome.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        stop_process(api)
        fixture.close()
        if result.get("status") != "passed":
            result["model_fixture_requests"] = model_log
            (output_dir / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        shutil.rmtree(data_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome-path", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    try:
        chrome_path = Path(resolve_chrome_path(args.chrome_path))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if not (REPO_ROOT / "apps/web/dist/index.html").is_file():
        raise SystemExit("apps/web/dist/index.html is missing; run `pnpm web:build` first")
    output_dir = args.output_dir or Path(
        tempfile.mkdtemp(prefix="focus-agent-review-browser-result-")
    )
    try:
        payload = run_flow(chrome_path=str(chrome_path), output_dir=output_dir)
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {"status": "failed", "error": str(exc), "output_dir": str(output_dir)},
                ensure_ascii=False,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": payload["status"],
                "output_dir": str(output_dir),
                "scenarios": list(payload["evidence"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
