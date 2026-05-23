#!/usr/bin/env python3
"""Capture a small, authenticated set of documentation screenshots."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib import request as urllib_request

import psycopg
from ui_smoke_test import (
    CdpWebSocket,
    create_page_target,
    ensure_health,
    pick_free_port,
    resolve_chrome_path,
    wait_for_devtools,
)

from focus_agent.core.productivity import FocusNote, FocusTask

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_APP_BASE_URL = "http://127.0.0.1:5173/app"
DEFAULT_OUT_DIR = ROOT / "docs" / "assets" / "screenshots"


CAPTURES = [
    {
        "name": "admin-console-users",
        "route": "/admin/users/docs-screenshots?query=docs",
        "wait_for": ["Admin Console", "用户目录"],
    },
    {
        "name": "memory-console",
        "route": "/agent/memory",
        "wait_for": ["Memory", "记忆"],
        "after_load": "document.querySelector('.fa-trajectory-overview-list-item.is-button')?.click();",
    },
    {
        "name": "productivity-notes",
        "route": "/productivity/notes",
        "wait_for": ["Productivity", "生产力"],
    },
]


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    token: str | None = None,
) -> dict[str, object]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib_request.Request(url, data=data, headers=headers, method=method)
    with urllib_request.urlopen(req, timeout=20) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw) if raw else {}
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Unexpected response from {url}: {parsed!r}")
    return parsed


def create_demo_access_token(api_base_url: str, *, user_id: str) -> str:
    response = _json_request(
        f"{api_base_url.rstrip('/')}/v1/auth/demo-token",
        method="POST",
        payload={
            "user_id": user_id,
            "scopes": ["chat", "branches", "admin"],
        },
    )
    token = response.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"Demo token response did not include access_token: {response!r}")
    return token


def _load_runtime_database_uri() -> str | None:
    state_file = ROOT / ".focus_agent" / "postgres" / "runtime.env"
    if not state_file.exists():
        return os.environ.get("DATABASE_URI")
    for raw_line in state_file.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("DATABASE_URI="):
            return raw_line.split("=", 1)[1].strip() or None
    return os.environ.get("DATABASE_URI")


def seed_memory_records(database_uri: str | None, *, user_id: str) -> None:
    if not database_uri:
        print("Skipping memory screenshot seed: DATABASE_URI is unavailable.", file=sys.stderr)
        return
    rows = [
        (
            "docs-memory-stream-boundary",
            "streaming-contract",
            "Stream visibility policy",
            "Only chunks explicitly promoted into the visible phase may become message.delta. Tool planning, repair prompts, and protocol text stay quarantined.",
            "project_fact",
            0.9,
        ),
        (
            "docs-memory-agent-team",
            "agent-team-evidence",
            "Agent Team adoption evidence",
            "Mission tasks should preserve acceptance criteria, changed files, test evidence, and final-answer synthesis before merge review.",
            "project_fact",
            0.82,
        ),
    ]
    with psycopg.connect(database_uri) as connection:
        with connection.cursor() as cursor:
            for memory_id, key, summary, content, kind, importance in rows:
                data = {
                    "memory_id": memory_id,
                    "kind": kind,
                    "tags": ["docs", "screenshot"],
                    "scope": "root_thread",
                    "namespace": ["conversation", "docs-screenshot-root", "episodic"],
                    "status": "active",
                    "content": content,
                    "summary": summary,
                    "user_id": user_id,
                    "visibility": "private",
                    "root_thread_id": "docs-screenshot-root",
                    "source_thread_id": "docs-screenshot-root",
                    "semantic_key": key,
                    "importance": importance,
                    "promoted_to_main": True,
                }
                cursor.execute(
                    """
                    insert into focus_memories (
                        memory_id, namespace, kind, scope, visibility, status, user_id,
                        root_thread_id, source_thread_id, semantic_key, fingerprint,
                        confidence, importance, summary, content, promoted_to_main,
                        data_json, embedding_status
                    )
                    values (
                        %(memory_id)s,
                        array['conversation', 'docs-screenshot-root', 'episodic'],
                        %(kind)s,
                        'root_thread',
                        'private',
                        'active',
                        %(user_id)s,
                        'docs-screenshot-root',
                        'docs-screenshot-root',
                        %(semantic_key)s,
                        %(fingerprint)s,
                        0.9,
                        %(importance)s,
                        %(summary)s,
                        %(content)s,
                        true,
                        %(data_json)s::jsonb,
                        'pending'
                    )
                    on conflict (memory_id) do update set
                        updated_at = now(),
                        kind = excluded.kind,
                        semantic_key = excluded.semantic_key,
                        fingerprint = excluded.fingerprint,
                        summary = excluded.summary,
                        content = excluded.content,
                        data_json = excluded.data_json,
                        importance = excluded.importance
                    """,
                    {
                        "memory_id": memory_id,
                        "kind": kind,
                        "user_id": user_id,
                        "semantic_key": key,
                        "fingerprint": f"docs:{key}",
                        "importance": importance,
                        "summary": summary,
                        "content": content,
                        "data_json": json.dumps(data),
                    },
                )
        connection.commit()


def seed_productivity(api_base_url: str, *, token: str) -> None:
    notes = _json_request(f"{api_base_url.rstrip('/')}/v1/notes?q=docs-screenshot", token=token)
    if not notes.get("items"):
        _json_request(
            f"{api_base_url.rstrip('/')}/v1/notes",
            method="POST",
            token=token,
            payload={
                "title": "Docs screenshot: streaming boundary",
                "body": "The final assistant answer is separated from tool and reasoning events before it reaches the transcript.",
                "tags": ["docs", "streaming"],
                "source_thread_id": "docs-screenshot-root",
                "source_url": "/app/c/docs-screenshot-root/t/docs-screenshot-root",
                "captured_from": "docs",
            },
        )
        _json_request(
            f"{api_base_url.rstrip('/')}/v1/notes",
            method="POST",
            token=token,
            payload={
                "title": "Docs screenshot: Agent Team adoption",
                "body": "Accepted task outputs can be captured back into notes and tasks with review evidence attached.",
                "tags": ["docs", "agent-team"],
                "source_thread_id": "docs-screenshot-root",
                "source_url": "/app/agent-team/docs-screenshot-session",
                "captured_from": "docs",
            },
        )

    tasks = _json_request(f"{api_base_url.rstrip('/')}/v1/tasks", token=token)
    existing_titles = {
        item.get("title") for item in tasks.get("items", []) if isinstance(item, dict)
    }
    if "Review documentation visual evidence" not in existing_titles:
        _json_request(
            f"{api_base_url.rstrip('/')}/v1/tasks",
            method="POST",
            token=token,
            payload={
                "title": "Review documentation visual evidence",
                "description": "Confirm screenshots are real project UI and diagrams match current architecture.",
                "source_thread_id": "docs-screenshot-root",
                "assignee_user_id": "researcher-1",
            },
        )


def seed_productivity_records(database_uri: str | None, *, user_id: str) -> bool:
    if not database_uri:
        return False
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    notes = [
        FocusNote(
            note_id="docs-note-stream-boundary",
            user_id=user_id,
            title="Docs screenshot: streaming boundary",
            body="The final assistant answer is separated from tool and reasoning events before it reaches the transcript.",
            tags=["docs", "streaming"],
            source_thread_id="docs-screenshot-root",
            source_kind="chat_answer",
            source_id="docs-streaming-boundary",
            source_url="/app/c/docs-screenshot-root/t/docs-screenshot-root",
            pinned_context={"thread_id": "docs-screenshot-root"},
            captured_from="docs",
            metadata={"docs_screenshot": True},
            created_at=now,
            updated_at=now,
        ),
        FocusNote(
            note_id="docs-note-agent-team-adoption",
            user_id=user_id,
            title="Docs screenshot: Agent Team adoption",
            body="Accepted task outputs can be captured back into notes and tasks with review evidence attached.",
            tags=["docs", "agent-team"],
            source_thread_id="docs-screenshot-root",
            source_kind="agent_team_review",
            source_id="docs-agent-team-adoption",
            source_url="/app/agent-team/docs-screenshot-session",
            pinned_context={"thread_id": "docs-screenshot-root", "review": "adoption"},
            captured_from="docs",
            metadata={"docs_screenshot": True},
            created_at=now,
            updated_at=now,
        ),
    ]
    tasks = [
        FocusTask(
            task_id="docs-task-visual-evidence",
            user_id=user_id,
            title="Review documentation visual evidence",
            description="Confirm screenshots are real project UI and diagrams match current architecture.",
            status="in_progress",
            source_thread_id="docs-screenshot-root",
            source_kind="docs_update",
            source_id="docs-visual-refresh",
            source_url="/app/productivity/notes",
            pinned_context={"thread_id": "docs-screenshot-root"},
            captured_from="docs",
            assignee_user_id=user_id,
            tags=["docs", "validation"],
            metadata={"docs_screenshot": True},
            created_at=now,
            updated_at=now,
        )
    ]
    with psycopg.connect(database_uri) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "delete from focus_notes where user_id = %s and title like 'Docs screenshot:%%'",
                (user_id,),
            )
            cursor.execute(
                "delete from focus_tasks where user_id = %s and title = 'Review documentation visual evidence'",
                (user_id,),
            )
            for note in notes:
                payload = note.model_dump(mode="json")
                cursor.execute(
                    """
                    insert into focus_notes (
                        note_id, user_id, title, body, tags, status, source_thread_id,
                        source_artifact_id, source_kind, source_id, source_url,
                        pinned_context, captured_from, is_archived, created_at, updated_at,
                        archived_at, data_json
                    )
                    values (
                        %(note_id)s, %(user_id)s, %(title)s, %(body)s, %(tags)s,
                        %(status)s, %(source_thread_id)s, %(source_artifact_id)s,
                        %(source_kind)s, %(source_id)s, %(source_url)s,
                        %(pinned_context)s::jsonb, %(captured_from)s, %(is_archived)s,
                        %(created_at)s, %(updated_at)s, %(archived_at)s,
                        %(data_json)s::jsonb
                    )
                    """,
                    {
                        **payload,
                        "status": str(note.status.value),
                        "pinned_context": json.dumps(note.pinned_context),
                        "data_json": json.dumps(payload),
                    },
                )
            for task in tasks:
                payload = task.model_dump(mode="json")
                cursor.execute(
                    """
                    insert into focus_tasks (
                        task_id, user_id, title, description, status, due_at, priority,
                        source_thread_id, source_note_id, source_kind, source_id, source_url,
                        pinned_context, captured_from, assignee_user_id, tags,
                        created_at, updated_at, completed_at, archived_at, data_json
                    )
                    values (
                        %(task_id)s, %(user_id)s, %(title)s, %(description)s,
                        %(status)s, %(due_at)s, %(priority)s, %(source_thread_id)s,
                        %(source_note_id)s, %(source_kind)s, %(source_id)s,
                        %(source_url)s, %(pinned_context)s::jsonb, %(captured_from)s,
                        %(assignee_user_id)s, %(tags)s, %(created_at)s, %(updated_at)s,
                        %(completed_at)s, %(archived_at)s, %(data_json)s::jsonb
                    )
                    """,
                    {
                        **payload,
                        "status": str(task.status.value),
                        "pinned_context": json.dumps(task.pinned_context),
                        "data_json": json.dumps(payload),
                    },
                )
        connection.commit()
    return True


def build_url(base_url: str, route: str) -> str:
    return f"{base_url.rstrip('/')}/{route.lstrip('/')}"


def browser_instrumentation(token: str) -> str:
    return (
        "try {"
        f"window.localStorage.setItem('focus-agent-token', {json.dumps(token)});"
        "window.localStorage.setItem('focus-agent-language', 'zh');"
        "} catch {}"
    )


def wait_expression(required_text: str | list[str]) -> str:
    required = json.dumps(required_text if isinstance(required_text, list) else [required_text])
    return f"""
(async () => {{
  const required = {required};
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const started = Date.now();
  while (Date.now() - started < 20000) {{
    const text = document.body?.innerText || "";
    const matched = required.some((item) => text.includes(item));
    if (matched && !location.pathname.includes("/auth/login")) {{
      return JSON.stringify({{ ok: true, location: location.href, text: text.slice(0, 240) }});
    }}
    await sleep(200);
  }}
  return JSON.stringify({{ ok: false, location: location.href, text: (document.body?.innerText || "").slice(0, 500) }});
}})()
"""


def capture_pages(
    *,
    app_base_url: str,
    out_dir: Path,
    token: str,
    chrome_path: str,
    wait_ms: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    port = pick_free_port()
    temp_dir = tempfile.TemporaryDirectory(prefix="focus-agent-doc-screenshots-")
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
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1440,
                    "height": 980,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            client.send(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": browser_instrumentation(token)},
            )
            for capture in CAPTURES:
                url = build_url(app_base_url, str(capture["route"]))
                client.send("Page.navigate", {"url": url})
                response = client.send(
                    "Runtime.evaluate",
                    {
                        "expression": wait_expression(capture["wait_for"]),
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                )
                payload = (
                    response.get("result", {}) if isinstance(response.get("result"), dict) else {}
                )
                value = payload.get("value")
                result = json.loads(value) if isinstance(value, str) and value else {}
                if not result.get("ok"):
                    raise RuntimeError(
                        f"Page did not become screenshot-ready for {url}: {result!r}"
                    )
                if capture.get("after_load"):
                    client.send("Runtime.evaluate", {"expression": str(capture["after_load"])})
                    time.sleep(0.6)
                time.sleep(wait_ms / 1000)
                client.send("Runtime.evaluate", {"expression": "window.scrollTo(0, 0)"})
                screenshot = client.send(
                    "Page.captureScreenshot",
                    {
                        "format": "png",
                        "fromSurface": True,
                        "captureBeyondViewport": False,
                    },
                )
                data = screenshot.get("data")
                if not isinstance(data, str):
                    raise RuntimeError(f"Chrome did not return screenshot data for {url}.")
                output_path = out_dir / f"{capture['name']}.png"
                output_path.write_bytes(base64.b64decode(data))
                print(f"captured {url} -> {output_path.relative_to(ROOT)}")
        finally:
            client.close()
    finally:
        chrome_process.terminate()
        try:
            chrome_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome_process.kill()
            chrome_process.wait(timeout=5)
        temp_dir.cleanup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--app-base-url", default=DEFAULT_APP_BASE_URL)
    parser.add_argument("--health-url", default=f"{DEFAULT_API_BASE_URL}/healthz")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--user-id", default="researcher-1")
    parser.add_argument("--database-uri", default=None)
    parser.add_argument("--chrome-path", default=None)
    parser.add_argument("--wait-ms", type=int, default=1600)
    parser.add_argument("--skip-seed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_health(str(args.health_url))
    token = create_demo_access_token(str(args.api_base_url), user_id=str(args.user_id))
    database_uri = str(args.database_uri) if args.database_uri else _load_runtime_database_uri()
    if not args.skip_seed:
        if not seed_productivity_records(database_uri, user_id=str(args.user_id)):
            seed_productivity(str(args.api_base_url), token=token)
        seed_memory_records(database_uri, user_id=str(args.user_id))
    capture_pages(
        app_base_url=str(args.app_base_url),
        out_dir=Path(args.out_dir),
        token=token,
        chrome_path=resolve_chrome_path(args.chrome_path),
        wait_ms=int(args.wait_ms),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
