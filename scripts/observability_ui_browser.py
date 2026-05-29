from __future__ import annotations

import json
import time

from ui_smoke_test import CdpWebSocket, collect_browser_diagnostics


def run_expression(client: CdpWebSocket, expression: str) -> dict[str, object]:
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
        raise RuntimeError(
            f"Unexpected browser evaluation response: {response!r}; diagnostics={diagnostics!r}"
        )
    return json.loads(payload)


def instrument_browser(client: CdpWebSocket, *, demo_access_token: str | None = None) -> None:
    client.send("Page.enable")
    client.send("Runtime.enable")
    if demo_access_token:
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
        {
            "source": """
window.__faFetches = [];
window.__faErrors = [];
const __faFetch = window.fetch.bind(window);
const __faFetchUrl = (input) => {
  if (typeof input === "string") return input;
  if (input && typeof input.url === "string") return input.url;
  return String(input);
};
window.fetch = async (...args) => {
  const url = __faFetchUrl(args[0]);
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


def wait_for_page_load(client: CdpWebSocket, url: str) -> None:
    client.send("Page.navigate", {"url": url})
    deadline = time.time() + 30
    last_state: object = None
    while time.time() < deadline:
        try:
            response = client.send(
                "Runtime.evaluate",
                {
                    "expression": """
JSON.stringify({
  href: location.href,
  readyState: document.readyState,
  hasBody: Boolean(document.body),
})
""",
                    "awaitPromise": True,
                    "returnByValue": True,
                },
            )
            raw_result = (
                response.get("result", {}) if isinstance(response.get("result"), dict) else {}
            )
            payload = raw_result.get("value")
            if isinstance(payload, str) and payload.strip():
                state = json.loads(payload)
                last_state = state
                if (
                    isinstance(state, dict)
                    and state.get("href") == url
                    and state.get("readyState") in {"interactive", "complete"}
                    and state.get("hasBody")
                ):
                    return
        except Exception as exc:  # noqa: BLE001 - navigation can briefly destroy the execution context.
            last_state = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for page load at {url}: {last_state!r}")


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
  const hasFetch = (pathname) =>
    fetches().some((item) => {{
      if (item.stage !== 'end' || !item.ok) return false;
      try {{
        return new URL(String(item.url), location.origin).pathname === pathname;
      }} catch {{
        return String(item.url).includes(pathname);
      }}
    }});
  await waitFor(
    () =>
      bodyText().includes('Trajectory operations overview') ||
      bodyText().includes('Trajectory 运行总览'),
    30000,
    'overview page title'
  );
  await waitFor(
    () =>
      hasFetch('/v1/observability/overview'),
    30000,
    'overview fetch'
  );
  const metricCards = document.querySelectorAll('.fa-trajectory-overview-metric-card').length;
  const columns = document.querySelectorAll('.fa-trajectory-overview-column').length;
  if (metricCards < 3 || columns < 3) {{
    throw new Error('Observability overview sections did not render.');
  }}
  return JSON.stringify({{
    url: location.href,
    metricCards,
    columns,
    request: seed.request_id,
  }});
}})()
"""


def build_trajectory_expression(
    seed: dict[str, object], *, evidence_state: str, promote: bool = False
) -> str:
    payload = json.dumps(seed, ensure_ascii=False)
    expected_state = json.dumps(evidence_state)
    should_promote = "true" if promote else "false"
    return rf"""
(async () => {{
  const seed = {payload};
  const expectedState = {expected_state};
  const shouldPromote = {should_promote};
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
  const hasFetch = (pathname) =>
    fetches().some((item) => {{
      if (item.stage !== 'end' || !item.ok) return false;
      try {{
        return new URL(String(item.url), location.origin).pathname === pathname;
      }} catch {{
        return String(item.url).includes(pathname);
      }}
    }});
  await waitFor(
    () =>
      bodyText().includes('High-density sample queue') ||
      bodyText().includes('高密度样本队列'),
    40000,
    'trajectory workbench title'
  );
  await waitFor(
    () =>
      hasFetch('/v1/observability/trajectory'),
    40000,
    'trajectory list fetch'
  );
  await waitFor(
    () =>
      hasFetch('/v1/observability/overview'),
    40000,
    'observability overview fetch'
  );
  await waitFor(
    () =>
      hasFetch('/v1/observability/trajectory/' + encodeURIComponent(seed.primary_turn_id)) ||
      fetches().some((item) => {{
        if (item.stage !== 'end' || !item.ok) return false;
        try {{
          const pathname = new URL(String(item.url), location.origin).pathname;
          return /^\/v1\/observability\/trajectory\/[^/]+$/.test(pathname);
        }} catch {{
          return String(item.url).includes('/v1/observability/trajectory/');
        }}
      }}),
    40000,
    'trajectory detail fetch'
  );
  const turnCards = document.querySelectorAll(
    '.fa-trajectory-workbench-sample-card, .fa-observability-turn-card'
  ).length;
  const correlationItems = Array.from(document.querySelectorAll('.fa-observability-correlation-item strong'))
    .map((item) => item.textContent || '');
  const requestInput = document.querySelector('input[placeholder="req-…"], input[placeholder="req-..."]');
  const traceInput = document.querySelector('input[placeholder="trace-…"], input[placeholder="trace-..."]');
  if (!requestInput || !traceInput) {{
    throw new Error('Request/trace filters were not rendered.');
  }}
  const railSections = await waitFor(
    () => {{
      const count = document.querySelectorAll('.fa-trajectory-workbench-rail-section').length;
      return count >= 4 ? count : 0;
    }},
    40000,
    'workbench right rail'
  );
  const actionControls = await waitFor(
    () => {{
      const actionPanel = document.querySelector('.fa-trajectory-workbench-action-panel');
      const batchActionPanel = document.querySelector('.fa-trajectory-workbench-batch-action-panel');
      const actionGrid = document.querySelector('.fa-observability-action-grid');
      const actionToggles = document.querySelector('.fa-observability-action-toggles');
      const commandBars = document.querySelectorAll('.fa-observability-command-bar').length;
      const replayButton = Array.from(document.querySelectorAll('button')).find((button) =>
        ['Run replay', '执行 Replay'].some((label) => (button.textContent || '').includes(label))
      );
      const promoteButton = Array.from(document.querySelectorAll('button')).find((button) =>
        ['Generate eval sample', 'Preview eval sample', '生成评测样本'].some((label) => (button.textContent || '').includes(label))
      );
      if (!actionPanel || !batchActionPanel || !actionGrid || !actionToggles || commandBars < 2 || !replayButton || !promoteButton) {{
        return null;
      }}
      return {{ commandBars, promoteButton }};
    }},
    40000,
    'replay/promote action controls'
  );
  const commandBars = actionControls.commandBars;
  const promoteButton = actionControls.promoteButton;
  let evidenceSelector = '.fa-observability-step-timeline';
  let evidenceLabel = 'timeline';
  if (expectedState === 'zero-step' || expectedState === 'missing-detail') {{
    evidenceSelector = '.fa-trajectory-workbench-zero-step';
    evidenceLabel = 'zero-step evidence';
  }}
  const evidenceNode = await waitFor(
    () => document.querySelector(evidenceSelector),
    40000,
    evidenceLabel
  );
  if (expectedState === 'failed') {{
    const dangerNotice = document.querySelector('.fa-inline-notice.is-danger');
    const warningPill = Array.from(document.querySelectorAll('.fa-observability-pill.is-warning'))
      .some((item) => (item.textContent || '').includes('fallback'));
    const dangerPill = Array.from(document.querySelectorAll('.fa-observability-pill.is-danger'))
      .some((item) => (item.textContent || '').includes('error'));
    const parallelPill = Array.from(document.querySelectorAll('.fa-observability-pill'))
      .some((item) => (item.textContent || '').includes('parallel 2'));
    if (!dangerNotice || !warningPill || !dangerPill || !parallelPill) {{
      throw new Error('Failed evidence state did not render error, fallback, and parallel signals.');
    }}
  }}
  let promoted = false;
  if (shouldPromote) {{
    promoteButton.click();
    await waitFor(
      () => fetches().some((item) => item.stage === 'end' && item.ok && String(item.url).includes('/promote')),
      40000,
      'promote action fetch'
    );
    await waitFor(
      () => (
        bodyText().includes('Promotion skeleton generated') ||
        bodyText().includes('Promotion skeleton preview generated') ||
        bodyText().includes('Promote skeleton 已生成') ||
        bodyText().includes('Promote skeleton 预览已生成')
      ),
      40000,
      'promotion success state'
    );
    promoted = true;
  }}
  if (expectedState === 'missing-detail') {{
    const rawMetaText = bodyText();
    if (!rawMetaText.includes('missing-detail') && !rawMetaText.includes('timeline evidence')) {{
      throw new Error('Missing-detail seed state did not render its sparse evidence context.');
    }}
  }}
  return JSON.stringify({{
    url: location.href,
    turnCards,
    correlationItems,
    railSections,
    commandBars,
    evidenceClass: evidenceNode.className,
    promoted,
  }});
}})()
"""
