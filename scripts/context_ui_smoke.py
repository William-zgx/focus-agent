#!/usr/bin/env python3
"""Real-Chrome, real-provider multi-turn context acceptance (no response fixtures)."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from observability_ui_browser import instrument_browser, run_expression, wait_for_page_load
from ui_smoke_test import (
    CdpWebSocket,
    chrome_runtime_flags,
    collect_browser_diagnostics,
    create_demo_access_token,
    create_page_target,
    ensure_health,
    pick_free_port,
    resolve_chrome_path,
    wait_for_devtools,
)

HELPERS = r"""
window.qa = {
  sleep: ms => new Promise(resolve => setTimeout(resolve, ms)),
  button: (...labels) => [...document.querySelectorAll('button')].find(button =>
    labels.some(label => [button.textContent?.trim(), button.getAttribute('aria-label'),
      button.title].includes(label)) && !button.disabled),
  assistants: () => [...document.querySelectorAll(
    '.fa-message-row.is-assistant .fa-message-bubble, .fa-message-row.assistant .fa-message-bubble'
  )].map(node => node.textContent.trim()),
  setDraft(value) {
    const input = document.querySelector('textarea');
    if (!input) throw new Error('Composer missing');
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  },
  async wait(predicate, label, timeout = 30000) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      const result = await predicate();
      if (result) return result;
      await this.sleep(150);
    }
    throw new Error('Timed out: ' + label);
  },
  async state() {
    const thread = location.pathname.split('/t/')[1]?.split('/')[0];
    const token = localStorage.getItem('focus-agent-token');
    const response = await fetch('/v1/threads/' + encodeURIComponent(thread), {
      headers: token ? {Authorization: 'Bearer ' + token} : {}
    });
    if (!response.ok) throw new Error('Thread state HTTP ' + response.status);
    return response.json();
  },
  async send(message) {
    const previous = this.assistants();
    this.setDraft(message);
    const send = await this.wait(() => this.button('发送消息','发送','Send message','Send'), 'send enabled');
    send.click();
    await this.sleep(500);
    let candidate = '', stable = 0;
    const start = Date.now();
    while (Date.now() - start < 180000) {
      const stop = this.button('停止生成','Stop generation');
      const streaming = stop || document.querySelector('.fa-composer-shell.is-streaming');
      const replies = this.assistants();
      const text = replies.at(-1) || '';
      if (!streaming && document.body.innerText.includes('本轮执行失败。')) {
        throw new Error('Run failed: ' + document.body.innerText.slice(-2500));
      }
      if (!streaming && text && (replies.length > previous.length || text !== previous.at(-1))) {
        stable = text === candidate ? stable + 250 : 0;
        candidate = text;
        if (stable >= 1000) {
          const state = await this.state();
          const latestHuman = [...(state.messages || [])].reverse().find(item => item.type === 'human');
          if (latestHuman?.content === message) return {response: text, state};
        }
      } else stable = 0;
      await this.sleep(250);
    }
    throw new Error('Provider response exceeded 180s');
  }
};
JSON.stringify({ready: true})
"""


def evaluate(client: CdpWebSocket, body: str) -> dict:
    return run_expression(client, f"(async () => {{ {body} }})()")


def save_screenshot(client: CdpWebSocket, path: Path) -> None:
    result = client.send(
        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
    )
    path.write_bytes(base64.b64decode(str(result["data"])))


def response_json(text: str) -> dict:
    # Rendered code blocks include the language and copy-button labels.
    return json.loads(text[text.index("{") : text.rindex("}") + 1])


def run(args: argparse.Namespace) -> int:
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "status": "running",
        "browser_used": True,
        "requested_model": args.model,
        "mode": "injected_compact_error" if args.fault_injection_only else "real_provider",
        "response_fixture_used": args.fault_injection_only,
        "steps": [],
    }

    def record(name: str, result: dict) -> None:
        diagnostics = collect_browser_diagnostics(client)
        result["browser_errors"] = diagnostics.get("errors", [])
        result["console_errors"] = diagnostics.get("console", [])
        result["failed_fetches"] = [
            item
            for item in diagnostics.get("fetches", [])
            if item.get("stage") == "error" or (item.get("stage") == "end" and not item.get("ok"))
        ]
        if result["browser_errors"] or result["failed_fetches"] or result["console_errors"]:
            raise AssertionError(f"Browser error or failed HTTP request at {name}")
        report["steps"].append({"name": name, **result})
        (out / "context-ui.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(name, "passed", flush=True)

    ensure_health(args.health_url)
    token = create_demo_access_token(args.health_url)
    port = pick_free_port()
    with tempfile.TemporaryDirectory(
        prefix="focus-agent-context-chrome-", ignore_cleanup_errors=True
    ) as profile:
        chrome = subprocess.Popen(
            [
                resolve_chrome_path(args.chrome_path),
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                *chrome_runtime_flags(),
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        client = None
        try:
            wait_for_devtools(port)
            page = create_page_target(port, "about:blank")
            client = CdpWebSocket(str(page["webSocketDebuggerUrl"]), timeout_seconds=240)
            instrument_browser(client, demo_access_token=token)
            if args.fault_injection_only:
                client.send(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": """
                  window.__faInjected409 = 0;
                  const realFetch = window.fetch;
                  window.fetch = (...args) => {
                    if (String(args[0]?.url || args[0]).includes('/context/compact')) {
                      window.__faInjected409++;
                      return Promise.resolve(new Response(JSON.stringify({detail: {code: 409, message: 'QA injected busy thread'}}), {
                        status: 409, headers: {'content-type': 'application/json'}
                      }));
                    }
                    return realFetch(...args);
                  };
                """
                    },
                )
            client.send(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
              window.__faConsole = [];
              const originalConsoleError = console.error.bind(console);
              console.error = (...args) => {
                window.__faConsole.push(args.map(String)); originalConsoleError(...args);
              };
            """
                },
            )
            client.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1440,
                    "height": 1000,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            origin = args.app_url.rstrip("/").split("/app")[0]
            wait_for_page_load(
                client,
                origin + args.resume_thread_path if args.resume_thread_path else args.app_url,
            )
            run_expression(client, HELPERS)
            record(
                "resume-conversation" if args.resume_thread_path else "new-conversation",
                evaluate(
                    client,
                    "await qa.wait(() => document.querySelector('textarea'), 'resumed composer'); await qa.sleep(700); return JSON.stringify({path: location.pathname});"
                    if args.resume_thread_path
                    else """
              const button = await qa.wait(() => qa.button('新建对话','新建','New conversation','New'), 'new');
              const old = location.pathname;
              button.click();
              await qa.wait(() => location.pathname !== old && location.pathname.includes('/t/'), 'new route');
              await qa.wait(() => document.querySelector('textarea'), 'composer');
              const thread = location.pathname.split('/t/')[1];
              await qa.wait(() => (window.__faFetches || []).some(item => item.stage === 'end' && item.ok &&
                String(item.url).endsWith('/v1/threads/' + thread)), 'initial thread loaded');
              await qa.sleep(300);
              return JSON.stringify({path: location.pathname});
            """,
                ),
            )
            model = json.dumps(args.model)
            if args.fault_injection_only:
                report["provider_used"] = False
                record(
                    "injected-409-error-ui",
                    evaluate(
                        client,
                        """
                      qa.setDraft('仅用于预览，不发送。'.repeat(15000));
                    const compact = await qa.wait(() => document.querySelector('.fa-context-meter-compact:not(:disabled)'), 'compact');
                    compact.click();
                    await qa.wait(() => document.body.innerText.includes('QA injected busy thread'), 'visible error');
                    await qa.sleep(700);
                    qa.setDraft('');
                    if ((window.__faErrors || []).length) throw new Error('Unhandled error after injected 409');
                      if (window.__faInjected409 !== 1) throw new Error('HTTP409 was not injected exactly once');
                      return JSON.stringify({injectedRequests: window.__faInjected409, errorVisible: true, unhandledRejections: 0});
                """,
                    ),
                )
                save_screenshot(client, out / "injected-409.png")
                report["status"] = "passed"
                return 0
            record(
                "select-model",
                evaluate(
                    client,
                    f"""
              document.querySelector('.fa-composer-model-trigger').click();
              const option = await qa.wait(() => document.querySelector(
                '.fa-composer-model-option[data-model-id=' + CSS.escape({model}) + ']'), 'model option');
              option.click();
              await qa.wait(() => document.querySelector('.fa-composer-model-trigger')?.getAttribute('aria-expanded') === 'false', 'model panel closed');
              document.querySelector('.fa-composer-model-trigger').click();
              const selected = await qa.wait(() => document.querySelector(
                '.fa-composer-model-option.is-selected[data-model-id=' + CSS.escape({model}) + ']'), 'selected model');
              const toggle = selected?.querySelector('[aria-pressed]');
              if (toggle?.getAttribute('aria-pressed') === 'true') toggle.click();
              await qa.sleep(200);
              document.querySelector('.fa-composer-model-trigger').click();
              return JSON.stringify({{model: selected?.getAttribute('data-model-id')}});
            """,
                ),
            )
            if args.tool_observation_workspace:
                from focus_agent.capabilities.default_tool_modules.workspace import (
                    _format_numbered_lines,
                )

                workspace = args.tool_observation_workspace
                workspace.mkdir(parents=True, exist_ok=True)
                filename = f"qa-observation-{uuid4().hex}.txt"
                marker = f"OBS-{uuid4().hex}"
                lines = [
                    f"{index}: " + "这是用于工具原文回读验证的非敏感资料。" * 5
                    for index in range(300)
                ]
                lines[200] = f"校验码：{marker}"
                (workspace / filename).write_text("\n".join(lines) + "\n")
                prompt = (
                    f"Use read_file(path={filename!r}, start_line=1, end_line=300) "
                    "to inspect this workspace file. Report its total line count."
                )
                first = evaluate(
                    client, f"return JSON.stringify(await qa.send({json.dumps(prompt)}));"
                )
                record("read-large-file", first)
                calls = [
                    call
                    for message in first["state"]["messages"]
                    for call in message.get("tool_calls") or []
                    if call.get("name") == "read_file"
                    and call.get("args", {}).get("path") == filename
                    and call.get("args", {}).get("start_line", 1) == 1
                    and call.get("args", {}).get("end_line") == 300
                ]
                if not calls:
                    raise AssertionError("Provider did not read the requested full range")
                call = calls[-1]
                raw = json.dumps(
                    {
                        "path": filename,
                        "start_line": 1,
                        "end_line": 300,
                        "total_lines": 300,
                        "content": _format_numbered_lines(lines, start_line=1),
                        "truncated": False,
                    },
                    ensure_ascii=False,
                )
                offset = raw.index(marker) - 80
                reference = f"tool-observation://read_file/{quote(call['id'], safe='')}"
                prompt = (
                    f"Use artifact_read(artifact_id={reference!r}, offset={offset}, limit=300) "
                    "to retrieve the saved observation page. Report the verification code in that page."
                )
                second = evaluate(
                    client, f"return JSON.stringify(await qa.send({json.dumps(prompt)}));"
                )
                readbacks = [
                    call
                    for message in second["state"]["messages"]
                    for call in message.get("tool_calls") or []
                    if call.get("name") == "artifact_read"
                    and call["args"].get("artifact_id") == reference
                    and call["args"].get("offset") == offset
                    and call["args"].get("limit") == 300
                ]
                if not readbacks or marker not in second["response"]:
                    raise AssertionError("Provider did not retrieve and report the requested page")
                readback_ids = {call["id"] for call in readbacks}
                if not any(
                    message.get("tool_call_id") in readback_ids
                    and marker in str(message.get("content", ""))
                    and message.get("status") != "error"
                    for message in second["state"]["messages"]
                ):
                    raise AssertionError("No successful tool result contains the verification code")
                record("read-observation-page", second)
                save_screenshot(client, out / "tool-readback.png")
                report["scenario"] = "tool_observation_readback"
                report["status"] = "passed"
                return 0
            prompts = [
                "这是上下文验收：为一个方案设计Agent设计两周验证计划。主支预算上限8万元，禁止上传敏感数据，原始证据编号 E-930 必须保留。不要调用工具，每次回答60字以内。请确认三条约束。",
                "请给出两个候选压缩方案并说明一个取舍，仍然不要调用工具，60字以内。",
                "请列出压缩质量的两个可测量指标，60字以内。",
                "请描述第一周的验收任务，60字以内。",
                "请描述第二周的验收任务，60字以内。",
                "增加验收指标：必须验证主支和子支隔离。请确认，60字以内。",
                "再增加验收指标：压缩后刷新浏览器不得丢失原始消息。请确认，60字以内。",
            ]
            for index, prompt in enumerate([] if args.resume_thread_path else prompts):
                result = evaluate(
                    client, f"return JSON.stringify(await qa.send({json.dumps(prompt)}));"
                )
                record(f"main-turn-{index + 1}", result)
            before = evaluate(client, "return JSON.stringify(await qa.state());")
            # A deliberately UNSENT large draft exposes the existing high-usage-only UI action.
            record(
                "compact-via-ui",
                evaluate(
                    client,
                    """
              qa.setDraft('仅用于预览，不发送。'.repeat(15000));
              const compact = await qa.wait(() => document.querySelector('.fa-context-meter-compact:not(:disabled)'),
                'high-usage compact action', 45000);
              compact.click();
              await qa.wait(() => (window.__faFetches || []).some(item => item.stage === 'end' && item.ok &&
                String(item.url).includes('/context/compact')), 'compact response');
              qa.setDraft('');
              await qa.sleep(700);
              return JSON.stringify(await qa.state());
            """,
                ),
            )
            after = report["steps"][-1]
            if before.get("messages", []) != after.get("messages", []):
                raise AssertionError("Compaction changed the raw transcript")
            if not after.get("context_usage", {}).get(
                "last_compacted_at"
            ) or "Context compaction snapshot:" not in after.get("rolling_summary", ""):
                raise AssertionError("Compaction snapshot/timestamp missing")
            result = evaluate(
                client,
                """
              return JSON.stringify(await qa.send('现在仅复述主支预算、敏感数据限制和证据编号，不调用工具，60字以内。'));
            """,
            )
            if not all(value in result["response"] for value in ("8", "E-930")):
                raise AssertionError("Main constraints/evidence not recalled after compaction")
            record("recall-after-compaction", result)
            main_path = report["steps"][0]["path"]
            save_screenshot(client, out / "main-desktop.png")
            record(
                "fork-branch",
                evaluate(
                    client,
                    """
              const old = location.pathname;
              (await qa.wait(() => qa.button('Fork branch','New branch','新建分支','创建分支'), 'fork')).click();
              await qa.wait(() => location.pathname !== old, 'branch route');
              await qa.wait(() => document.querySelector('textarea'), 'branch composer');
              return JSON.stringify({path: location.pathname});
            """,
                ),
            )
            child_path = report["steps"][-1]["path"]
            result = evaluate(
                client,
                """
              return JSON.stringify(await qa.send('当前子支单独方案预算改为9万元，仍禁止上传敏感数据。仅回答JSON {"budget_wan":9}，不要提主支预算，不调用工具。'));
            """,
            )
            if response_json(result["response"]).get("budget_wan") != 9:
                raise AssertionError("Branch-local constraint missing")
            record("child-local-constraint", result)
            save_screenshot(client, out / "child-desktop.png")
            wait_for_page_load(client, args.app_url.rstrip("/").split("/app")[0] + main_path)
            run_expression(client, HELPERS)
            evaluate(
                client,
                "await qa.wait(() => document.querySelector('textarea') && qa.assistants().some(text => text.includes('E-930')), 'restored transcript and composer'); return JSON.stringify({ready:true});",
            )
            result = evaluate(
                client,
                """
              return JSON.stringify(await qa.send('回到主支，仅用JSON回答本主支预算和证据编号，字段budget_wan和evidence，不调用工具。'));
            """,
            )
            recalled = response_json(result["response"])
            if recalled.get("budget_wan") != 8 or recalled.get("evidence") != "E-930":
                raise AssertionError("Child context polluted main branch")
            record("parent-after-child-and-reload", result)
            client.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 390,
                    "height": 844,
                    "deviceScaleFactor": 1,
                    "mobile": True,
                },
            )
            record(
                "mobile-layout",
                evaluate(
                    client,
                    """
              await qa.sleep(300);
              return JSON.stringify({width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
                composerVisible: Boolean(document.querySelector('textarea')), childPath: """
                    + json.dumps(child_path)
                    + """});
            """,
                ),
            )
            save_screenshot(client, out / "main-mobile.png")
            layout = report["steps"][-1]
            if layout["scrollWidth"] > layout["width"] or not layout["composerVisible"]:
                raise AssertionError("Mobile viewport overflows or composer is missing")
            diagnostics = collect_browser_diagnostics(client)
            report["browser_errors"] = diagnostics.get("errors", [])
            report["failed_fetches"] = [
                item
                for item in diagnostics.get("fetches", [])
                if item.get("stage") == "error"
                or (item.get("stage") == "end" and not item.get("ok"))
            ]
            if report["browser_errors"] or report["failed_fetches"]:
                raise AssertionError("Browser errors or failed HTTP requests recorded")
            report["status"] = "passed"
            return 0
        except Exception as exc:  # noqa: BLE001 - retain browser evidence on failure.
            report["status"] = "failed"
            report["error"] = str(exc)
            if client is not None:
                report["diagnostics"] = collect_browser_diagnostics(client)
                save_screenshot(client, out / "failure.png")
            return 1
        finally:
            (out / "context-ui.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            )
            if client is not None:
                client.close()
            chrome.terminate()
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill()
                chrome.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", default="http://127.0.0.1:5173/app/")
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/healthz")
    parser.add_argument("--chrome-path")
    parser.add_argument(
        "--fault-injection-only",
        action="store_true",
        help="Only inject a compact HTTP409; no provider requests are made.",
    )
    parser.add_argument(
        "--resume-thread-path",
        help="Continue on a previous smoke thread with seven completed turns.",
    )
    parser.add_argument(
        "--tool-observation-workspace",
        type=Path,
        help="Run real-provider tool readback instead; create a synthetic file in this dedicated API workspace.",
    )
    parser.add_argument(
        "--model", required=True, help="Existing model catalog ID; real provider used."
    )
    parser.add_argument("--out-dir", type=Path, default=Path("reports/context-ui-smoke"))
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
