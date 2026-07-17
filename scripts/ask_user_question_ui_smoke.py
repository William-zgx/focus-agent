#!/usr/bin/env python3
"""Real-browser smoke test for ask_user_question interrupt UI.

Starts against local Focus Agent app (default Vite + API), injects a synthetic
ask_user_question interrupt into thread state responses, then drives the form
through validation and submit paths via Chrome DevTools Protocol.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from ui_smoke_test import (  # noqa: E402
    CdpWebSocket,
    chrome_runtime_flags,
    create_demo_access_token,
    create_page_target,
    ensure_health,
    pick_free_port,
    resolve_chrome_path,
    wait_for_devtools,
)

DEFAULT_APP_URL = "http://127.0.0.1:5173/app/"
DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/healthz"
REPORT_PATH = ROOT / "reports" / "ui-smoke" / "ask-user-question.json"

FETCH_PATCH_SOURCE = r"""
(() => {
  if (window.__faAskUserQuestionFetchPatched) return;
  window.__faAskUserQuestionFetchPatched = true;
  window.__faAskUserQuestionSmoke = {
    resumeBodies: [],
    threadPatches: 0,
    threadUrls: [],
    cardSeen: false,
  };
  const MOCK_INTERRUPT = {
    kind: 'ask_user_question',
    interrupt_id: 'ask-user-question:smoke-call:ui-smoke-digest',
    tool_name: 'ask_user_question',
    tool_call_id: 'smoke-call',
    policy_version: 'ask_user_question.v1',
    created_at: new Date().toISOString(),
    questions: [
      {
        id: 'q0',
        question: 'Which auth mode should we use for the smoke test?',
        header: 'Auth',
        multi_select: false,
        options: [
          { label: 'OAuth', description: 'Browser login flow' },
          { label: 'API key', description: 'Service credentials' },
        ],
      },
      {
        id: 'q1',
        question: 'Which surfaces need coverage?',
        header: 'Scope',
        multi_select: true,
        options: [
          { label: 'Web', description: 'Desktop web app' },
          { label: 'Mobile', description: 'Android client' },
        ],
      },
    ],
  };
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const input = args[0];
    const init = args[1] || {};
    const url = typeof input === 'string' ? input : String(input && input.url ? input.url : input);
    const method = String(init.method || 'GET').toUpperCase();

    if (url.includes('/runs/resume/stream') && method === 'POST') {
      let bodyTextValue = '';
      try {
        bodyTextValue =
          typeof init.body === 'string'
            ? init.body
            : init.body
              ? await new Response(init.body).text()
              : '';
      } catch (error) {
        bodyTextValue = String(error);
      }
      try {
        window.__faAskUserQuestionSmoke.resumeBodies.push(JSON.parse(bodyTextValue || '{}'));
      } catch {
        window.__faAskUserQuestionSmoke.resumeBodies.push({ raw: bodyTextValue });
      }
      // Short-circuit resume so we can assert the payload without full agent loop.
      return new Response(
        'event: run.closed\ndata: {"reason":"ui-smoke-short-circuit"}\n\n',
        {
          status: 200,
          headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
          },
        },
      );
    }

    const response = await originalFetch(...args);
    const pathOnly = url.split('?')[0];
    if (method === 'GET' && /\/v1\/threads\/[^/]+$/.test(pathOnly)) {
      try {
        const clone = response.clone();
        const payload = await clone.json();
        if (payload && typeof payload === 'object') {
          payload.interrupts = [MOCK_INTERRUPT];
          window.__faAskUserQuestionSmoke.threadPatches += 1;
          window.__faAskUserQuestionSmoke.threadUrls.push(pathOnly);
          return new Response(JSON.stringify(payload), {
            status: response.status,
            statusText: response.statusText,
            headers: { 'Content-Type': 'application/json' },
          });
        }
      } catch {
        // fall through
      }
    }
    return response;
  };
})();
"""


def build_expression() -> str:
    return r"""
(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const bodyText = () => document.body?.innerText || '';
  const includesAny = (text, labels) => labels.some((label) => text.includes(label));
  const findButton = (...labels) =>
    Array.from(document.querySelectorAll('button')).find((button) =>
      labels.some((label) => (button.textContent || '').trim().includes(label)),
    ) || null;
  const clickButton = (...labels) => {
    const button = findButton(...labels);
    if (!button) throw new Error('Missing button: ' + labels.join(' | '));
    button.click();
    return button;
  };
  const waitFor = async (predicate, timeoutMs, label) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const value = predicate();
      if (value) return value;
      await sleep(150);
    }
    throw new Error('Timed out waiting for ' + label + ' @ ' + location.href);
  };
  const hasThreadRoute = () => /^\/app\/c\/[^/]+\/t\/[^/]+/.test(location.pathname);

  const result = { steps: [], assertions: {} };

  const newConversationLabels = ['New', 'New conversation', '新建', '新建对话'];
  const demoLoginLabels = ['Demo 登录'];
  const isLoginPage = () =>
    includesAny(bodyText(), ['账号登录', '使用用户名与密码完成身份确认']) &&
    findButton(...demoLoginLabels);
  if (isLoginPage()) {
    throw new Error('Reached login page; demo token injection failed.');
  }

  await waitFor(() => findButton(...newConversationLabels), 25000, 'conversation sidebar');
  result.steps.push('sidebar-ready');
  result.title = document.title;
  result.url = location.href;

  // Ensure fetch patch exists even if new-document inject missed.
  if (!window.__faAskUserQuestionFetchPatched) {
    throw new Error('Fetch patch was not installed before page load.');
  }

  const currentThreadPath = location.pathname;
  const originalPrompt = window.prompt;
  window.prompt = () => 'AskUserQuestion UI Smoke';
  try {
    clickButton(...newConversationLabels);
  } finally {
    window.prompt = originalPrompt;
  }
  await waitFor(
    () => hasThreadRoute() && location.pathname !== currentThreadPath,
    25000,
    'new conversation route',
  );
  result.threadPath = location.pathname;
  result.steps.push('thread-opened');

  await waitFor(() => document.querySelector('textarea'), 25000, 'thread composer');

  // Wait for patched thread GET + card render (no full page navigation).
  const card = await waitFor(
    () => document.querySelector('.fa-ask-user-question-card'),
    30000,
    'ask user question card',
  );
  window.__faAskUserQuestionSmoke.cardSeen = true;
  result.steps.push('card-visible');
  result.assertions.cardTitle = Boolean(
    bodyText().includes('A few choices need your input') ||
      bodyText().includes('需要你确认几个选择'),
  );
  result.assertions.hasAuthQuestion = bodyText().includes('Which auth mode should we use');
  result.assertions.hasScopeQuestion = bodyText().includes('Which surfaces need coverage');
  result.assertions.threadPatches = window.__faAskUserQuestionSmoke.threadPatches > 0;

  // Validation: submit empty form should surface local error and not resume.
  const submitButton = Array.from(card.querySelectorAll('button')).find((button) =>
    /Submit answers|提交答案/.test(button.textContent || ''),
  );
  if (!submitButton) throw new Error('Submit button missing');
  submitButton.click();
  await sleep(250);
  const validationError = card.querySelector('.fa-ask-user-question-card-error');
  result.assertions.validationBlocksEmptySubmit = Boolean(
    validationError && (validationError.textContent || '').trim(),
  );
  result.assertions.resumeNotSentOnInvalid =
    window.__faAskUserQuestionSmoke.resumeBodies.length === 0;
  result.steps.push('empty-submit-validated');

  // Select single-choice OAuth.
  const oauthInput = Array.from(card.querySelectorAll('input')).find((input) => {
    const label = input.closest('label');
    return label && (label.textContent || '').includes('OAuth');
  });
  if (!oauthInput) throw new Error('OAuth option missing');
  oauthInput.click();

  // Multi-select Web + Other with custom text.
  const webInput = Array.from(card.querySelectorAll('input')).find((input) => {
    const label = input.closest('label');
    const text = label?.textContent || '';
    return text.includes('Web') && text.includes('Desktop web');
  });
  if (!webInput) throw new Error('Web option missing');
  webInput.click();

  const otherInputs = Array.from(card.querySelectorAll('input')).filter((input) => {
    const label = input.closest('label');
    const text = label?.textContent || '';
    return text.includes('Other') || text.includes('其他');
  });
  const scopeOther = otherInputs[otherInputs.length - 1];
  if (!scopeOther) throw new Error('Other option missing');
  scopeOther.click();
  await sleep(120);
  const otherText = card.querySelector('.fa-ask-user-question-other-input');
  if (!otherText) throw new Error('Other free-text input missing');
  otherText.focus();
  // React-controlled input: set native value setter.
  const nativeSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    'value',
  )?.set;
  if (nativeSetter) {
    nativeSetter.call(otherText, 'CLI coverage required');
  } else {
    otherText.value = 'CLI coverage required';
  }
  otherText.dispatchEvent(new Event('input', { bubbles: true }));
  otherText.dispatchEvent(new Event('change', { bubbles: true }));
  result.steps.push('options-selected');

  result.assertions.selectedCount =
    card.querySelectorAll('.fa-ask-user-question-option.is-selected').length >= 2;

  submitButton.click();
  await waitFor(
    () => window.__faAskUserQuestionSmoke.resumeBodies.length >= 1,
    15000,
    'resume payload capture',
  );
  result.steps.push('resume-captured');

  const resumePayload = window.__faAskUserQuestionSmoke.resumeBodies[0] || {};
  const resume = resumePayload.resume || resumePayload;
  result.resume = resume;
  result.assertions.resumeKind = resume.kind === 'ask_user_question';
  result.assertions.resumeToolCallId = resume.tool_call_id === 'smoke-call';
  result.assertions.resumeInterruptId =
    resume.interrupt_id === 'ask-user-question:smoke-call:ui-smoke-digest';
  const answers = Array.isArray(resume.answers) ? resume.answers : [];
  result.assertions.answerCount = answers.length === 2;
  const q0 = answers.find((item) => item.question_id === 'q0') || {};
  const q1 = answers.find((item) => item.question_id === 'q1') || {};
  result.assertions.q0SelectedOAuth =
    Array.isArray(q0.selected_labels) && q0.selected_labels.includes('OAuth');
  result.assertions.q1SelectedWeb =
    Array.isArray(q1.selected_labels) && q1.selected_labels.includes('Web');
  result.assertions.q1SelectedOther =
    Array.isArray(q1.selected_labels) &&
    q1.selected_labels.map((label) => String(label).toLowerCase()).includes('other');
  result.assertions.q1OtherText = String(q1.other_text || '').includes('CLI coverage required');

  const failed = Object.entries(result.assertions)
    .filter(([, value]) => value !== true)
    .map(([key, value]) => ({ key, value }));
  result.ok = failed.length === 0;
  result.failedAssertions = failed;
  result.smokeMeta = {
    threadPatches: window.__faAskUserQuestionSmoke.threadPatches,
    threadUrls: window.__faAskUserQuestionSmoke.threadUrls,
    resumeCount: window.__faAskUserQuestionSmoke.resumeBodies.length,
  };
  if (!result.ok) {
    throw new Error('Ask-user-question UI smoke assertions failed: ' + JSON.stringify(failed));
  }
  return JSON.stringify(result);
})()
"""


def run_smoke(
    *,
    app_url: str,
    health_url: str,
    chrome_path: str,
    keep_open: bool,
) -> dict[str, object]:
    ensure_health(health_url)
    demo_access_token = create_demo_access_token(health_url)
    if not demo_access_token:
        raise RuntimeError(
            "Could not mint demo access token. Ensure AUTH_DEMO_TOKENS_ENABLED=true."
        )

    port = pick_free_port()
    temp_dir = tempfile.TemporaryDirectory(prefix="focus-agent-ask-user-question-ui-smoke-")
    chrome_process = subprocess.Popen(  # noqa: S603
        [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={temp_dir.name}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-search-engine-choice-screen",
            *chrome_runtime_flags(),
            "--window-size=1440,1100",
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
            raise RuntimeError(f"Missing webSocketDebuggerUrl: {target!r}")
        client = CdpWebSocket(websocket_url, timeout_seconds=180.0)
        try:
            client.send("Page.enable")
            client.send("Runtime.enable")
            # Token + fetch patch must be installed before first document scripts run.
            client.send(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": (
                        "try { window.localStorage.setItem("
                        f"'focus-agent-token', {json.dumps(demo_access_token)}"
                        "); } catch {}"
                    ),
                },
            )
            client.send(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": FETCH_PATCH_SOURCE},
            )
            client.send("Page.navigate", {"url": app_url})
            time.sleep(2.5)
            response = client.send(
                "Runtime.evaluate",
                {
                    "expression": build_expression(),
                    "awaitPromise": True,
                    "returnByValue": True,
                },
            )
            raw_value = (
                response.get("result", {}) if isinstance(response.get("result"), dict) else {}
            )
            # CDP may put exception text here.
            if response.get("exceptionDetails"):
                details = response["exceptionDetails"]
                raise RuntimeError(f"Browser evaluation exception: {details!r}")
            payload = raw_value.get("value", "")
            if not isinstance(payload, str) or not payload.strip():
                raise RuntimeError(f"Unexpected smoke payload: {response!r}")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", default=DEFAULT_APP_URL)
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL)
    parser.add_argument("--chrome-path", default=None)
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument(
        "--report-path",
        default=str(REPORT_PATH),
        help="Where to write the JSON report.",
    )
    args = parser.parse_args()
    result = run_smoke(
        app_url=str(args.app_url),
        health_url=str(args.health_url),
        chrome_path=resolve_chrome_path(args.chrome_path),
        keep_open=bool(args.keep_open),
    )
    report_path = Path(str(args.report_path))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nWrote report: {report_path}", file=sys.stderr)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
