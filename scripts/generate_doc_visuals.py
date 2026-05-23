#!/usr/bin/env python3
"""Generate checked-in documentation SVG assets."""

from __future__ import annotations

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
DIAGRAMS = ASSETS / "diagrams"
FONT = "Inter, Avenir Next, Segoe UI, Arial, sans-serif"
MONO = "SFMono-Regular, Menlo, Consolas, monospace"


def attrs(**values: object) -> str:
    return " ".join(
        f'{key.replace("_", "-")}="{escape(str(value), quote=True)}"'
        for key, value in values.items()
        if value is not None
    )


def text(
    x: int,
    y: int,
    value: str,
    *,
    size: int = 18,
    fill: str = "#13233A",
    weight: int = 600,
    family: str = FONT,
    anchor: str | None = None,
) -> str:
    tag_attrs = attrs(
        x=x,
        y=y,
        fill=fill,
        font_family=family,
        font_size=size,
        font_weight=weight,
        text_anchor=anchor,
    )
    return f"<text {tag_attrs}>{escape(value)}</text>"


def rect(
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    fill: str = "#FFFFFF",
    stroke: str = "#D5E0EC",
    radius: int = 18,
    stroke_width: int = 1,
    opacity: float | None = None,
) -> str:
    tag_attrs = attrs(
        x=x,
        y=y,
        width=width,
        height=height,
        rx=radius,
        fill=fill,
        stroke=stroke,
        stroke_width=stroke_width,
        opacity=opacity,
    )
    return f"<rect {tag_attrs}/>"


def line(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    stroke: str = "#7D91AA",
    width: int = 3,
    dash: str | None = None,
    marker: bool = True,
) -> str:
    tag_attrs = attrs(
        d=f"M{x1} {y1} L{x2} {y2}",
        stroke=stroke,
        stroke_width=width,
        stroke_linecap="round",
        stroke_dasharray=dash,
        marker_end="url(#arrow)" if marker else None,
    )
    return f'<path {tag_attrs} fill="none"/>'


def polyline(points: list[tuple[int, int]], *, stroke: str = "#7D91AA") -> str:
    if not points:
        return ""
    commands = [f"M{points[0][0]} {points[0][1]}"] + [f"L{x} {y}" for x, y in points[1:]]
    tag_attrs = attrs(
        d=" ".join(commands),
        stroke=stroke,
        stroke_width=3,
        stroke_linecap="round",
        stroke_linejoin="round",
        marker_end="url(#arrow)",
    )
    return f'<path {tag_attrs} fill="none"/>'


def card(
    x: int,
    y: int,
    width: int,
    height: int,
    title: str,
    body: str,
    *,
    accent: str = "#2C7BE5",
    fill: str = "#FFFFFF",
    title_fill: str = "#102033",
    body_fill: str = "#52677F",
) -> str:
    parts = [
        rect(x, y, width, height, fill=fill, stroke="#D5E0EC", radius=16),
        f'<circle cx="{x + 24}" cy="{y + 28}" r="7" fill="{accent}"/>',
        text(x + 42, y + 34, title, size=18, fill=title_fill, weight=800),
    ]
    for index, row in enumerate(wrap(body, 38)):
        parts.append(text(x + 22, y + 64 + index * 20, row, size=14, fill=body_fill, weight=500))
    return "\n".join(parts)


def pill(x: int, y: int, label: str, *, fill: str, dot: str = "#FFFFFF") -> str:
    width = max(78, 22 + len(label) * 8)
    return "\n".join(
        [
            rect(x, y, width, 34, fill=fill, stroke="none", radius=17),
            f'<circle cx="{x + 18}" cy="{y + 17}" r="5" fill="{dot}"/>',
            text(x + 30, y + 23, label, size=13, fill="#F8FBFF", weight=800),
        ]
    )


def wrap(value: str, limit: int) -> list[str]:
    words = value.split()
    rows: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > limit and current:
            rows.append(current)
            current = word
        else:
            current = candidate
    if current:
        rows.append(current)
    return rows[:3]


def frame(width: int, height: int, body: str, *, title: str | None = None) -> str:
    header = ""
    if title:
        header = text(48, 72, title, size=34, fill="#102033", weight=850)
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
      <path d="M1 1L9 5L1 9" fill="none" stroke="#6D829E" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
    <linearGradient id="softBg" x1="0" y1="0" x2="{width}" y2="{height}" gradientUnits="userSpaceOnUse">
      <stop stop-color="#F7FAFD"/>
      <stop offset="1" stop-color="#EDF4F8"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="28" fill="url(#softBg)"/>
  <rect x="24" y="24" width="{width - 48}" height="{height - 48}" rx="24" fill="#FFFFFF" stroke="#D8E4EF"/>
  {header}
  {body}
</svg>
"""


def hero(*, chinese: bool = False) -> str:
    title = "Focus Agent"
    subtitle = (
        "让分支、记忆、协作和复盘保持同一个焦点。"
        if chinese
        else "Keep branches, memory, teamwork, and review in one focused workspace."
    )
    pills = (
        ["分支会话", "Agent Team", "记忆", "Admin", "复盘", "生产力", "流式隔离"]
        if chinese
        else ["Branching", "Agent Team", "Memory", "Admin", "Review", "Productivity", "Stream Gate"]
    )
    cta = "Web-first Agent 平台骨架" if chinese else "Web-first agent platform scaffold"
    parts = [
        '<defs><linearGradient id="heroBg" x1="0" y1="0" x2="1280" y2="640" gradientUnits="userSpaceOnUse"><stop stop-color="#071320"/><stop offset="0.54" stop-color="#102A3D"/><stop offset="1" stop-color="#19312B"/></linearGradient><linearGradient id="panel" x1="700" y1="110" x2="1180" y2="548" gradientUnits="userSpaceOnUse"><stop stop-color="#FAFDFF"/><stop offset="1" stop-color="#EAF3FA"/></linearGradient><filter id="shadow" x="660" y="76" width="570" height="520" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feDropShadow dx="0" dy="24" stdDeviation="24" flood-color="#02111D" flood-opacity="0.34"/></filter></defs>',
        '<rect width="1280" height="640" rx="36" fill="url(#heroBg)"/>',
        '<path d="M92 120C230 52 356 72 470 180C582 286 646 298 760 236C904 156 1058 118 1190 182" stroke="#4DD4F7" stroke-width="2" opacity="0.22" fill="none"/>',
        '<path d="M112 524C252 456 368 464 488 536C604 606 728 594 842 520C962 440 1068 436 1194 496" stroke="#62E0AE" stroke-width="2" opacity="0.18" fill="none"/>',
        rect(108, 118, 114, 114, fill="#F4FAFF", stroke="none", radius=28),
        '<circle cx="145" cy="175" r="22" stroke="#2FB7F5" stroke-width="8"/><circle cx="145" cy="175" r="8" fill="#2FB7F5"/><path d="M168 175H190V151H210M190 175V199H210" stroke="#17334D" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="210" cy="151" r="7" fill="#17334D"/><circle cx="190" cy="175" r="7" fill="#17334D"/><circle cx="210" cy="199" r="7" fill="#17334D"/>',
        text(108, 310, title, size=70, fill="#F8FBFF", weight=850),
    ]
    for index, row in enumerate(wrap(subtitle, 46)):
        parts.append(text(108, 356 + index * 30, row, size=23, fill="#B8CEE3", weight=600))
    parts.append(text(108, 424, cta, size=18, fill="#E8F2FB", weight=800))
    x = 108
    y = 462
    colors = ["#164B73", "#176052", "#6A4A17", "#553F7C", "#275A86", "#365F42", "#6F3446"]
    for index, label in enumerate(pills):
        parts.append(
            pill(
                x,
                y,
                label,
                fill=colors[index % len(colors)],
                dot=["#45C8FF", "#65E0B1", "#FFCA68", "#B9A6FF"][index % 4],
            )
        )
        x += max(94, 32 + len(label) * 9)
        if x > 585:
            x = 108
            y += 46
    parts.extend(
        [
            '<g filter="url(#shadow)">',
            rect(700, 104, 456, 428, fill="url(#panel)", stroke="#D5E3EF", radius=28),
            rect(700, 104, 456, 48, fill="#EAF2F9", stroke="none", radius=28),
            '<circle cx="732" cy="128" r="6" fill="#FF8A8A"/><circle cx="752" cy="128" r="6" fill="#FFC857"/><circle cx="772" cy="128" r="6" fill="#49D98C"/>',
            text(808, 134, "Focus Agent Console", size=14, fill="#5E7898", weight=800),
            rect(724, 176, 112, 328, fill="#132A43", stroke="none", radius=20),
            text(746, 204, "workspace", size=11, fill="#8FC7FF", weight=800, family=MONO),
            pill(744, 226, "main", fill="#1B4C74", dot="#45C8FF"),
            pill(744, 270, "branch", fill="#1E5C4E", dot="#65E0B1"),
            pill(744, 314, "memory", fill="#5D461B", dot="#FFCA68"),
            pill(744, 358, "admin", fill="#4B3B75", dot="#B9A6FF"),
            rect(860, 176, 264, 126, fill="#F7FAFE", stroke="#D5E3EF", radius=18),
            text(882, 206, "Agent Team mission", size=16, fill="#203854", weight=850),
            line(918, 244, 982, 244, stroke="#2FB7F5"),
            line(982, 244, 1044, 220, stroke="#62C99D"),
            line(982, 244, 1044, 268, stroke="#F1A936"),
            rect(884, 228, 70, 34, fill="#E7F4FC", stroke="#BFD9EC", radius=12),
            rect(1008, 204, 78, 34, fill="#EAF8F1", stroke="#C4E7D4", radius=12),
            rect(1008, 252, 78, 34, fill="#FFF5DE", stroke="#F2D699", radius=12),
            text(900, 250, "Plan", size=12, fill="#21445F", weight=800),
            text(1022, 226, "Build", size=12, fill="#255C45", weight=800),
            text(1018, 274, "Verify", size=12, fill="#77521B", weight=800),
            rect(860, 324, 264, 80, fill="#122A43", stroke="none", radius=18),
            text(882, 350, "stream boundary", size=12, fill="#84CFFF", weight=800, family=MONO),
            text(882, 374, "tool events -> processing cards", size=13, fill="#E8F2FB", weight=700),
            text(882, 394, "visible answer -> message.delta", size=13, fill="#E8F2FB", weight=700),
            rect(860, 424, 124, 58, fill="#F3F7FB", stroke="#D5E3EF", radius=16),
            text(880, 449, "Memory", size=15, fill="#203854", weight=850),
            text(880, 469, "pgvector shadow", size=12, fill="#5A7088", weight=600),
            rect(1000, 424, 124, 58, fill="#F3F7FB", stroke="#D5E3EF", radius=16),
            text(1020, 449, "Review", size=15, fill="#203854", weight=850),
            text(1020, 469, "trajectory + eval", size=12, fill="#5A7088", weight=600),
            "</g>",
        ]
    )
    return f"""<svg width="1280" height="640" viewBox="0 0 1280 640" fill="none" xmlns="http://www.w3.org/2000/svg">
  {"".join(parts)}
</svg>
"""


def platform_map() -> str:
    body = "\n".join(
        [
            card(
                70,
                128,
                220,
                112,
                "Web App + SDK",
                "React routes, typed client, SSE reducer",
                accent="#2FB7F5",
            ),
            card(
                370,
                128,
                220,
                112,
                "FastAPI",
                "Auth, contracts, middleware, error envelope",
                accent="#7A68D8",
            ),
            card(
                670,
                128,
                220,
                112,
                "Services",
                "Chat, Branch, Agent Team, Admin, Productivity",
                accent="#2CA874",
            ),
            card(
                970,
                128,
                220,
                112,
                "LangGraph",
                "Turn graph, tool loop, context, memory",
                accent="#E49B23",
            ),
            line(290, 184, 370, 184),
            line(590, 184, 670, 184),
            line(890, 184, 970, 184),
            card(
                170,
                330,
                210,
                112,
                "Postgres",
                "threads, users, memory, trajectory, notes/tasks",
                accent="#245D9C",
            ),
            card(
                440,
                330,
                210,
                112,
                "Artifact Store",
                "metadata in DB, bodies on filesystem",
                accent="#B65B76",
            ),
            card(
                710,
                330,
                210,
                112,
                "Observability",
                "request ids, trajectory, replay, release evidence",
                accent="#2F9FAD",
            ),
            card(
                980,
                330,
                210,
                112,
                "Governance",
                "roles, tool policy, branch action, audits",
                accent="#8E6AC8",
            ),
            polyline([(780, 240), (780, 286), (276, 286), (276, 330)]),
            polyline([(780, 240), (780, 286), (545, 286), (545, 330)], stroke="#B65B76"),
            polyline([(780, 240), (780, 286), (815, 330)], stroke="#2F9FAD"),
            polyline([(780, 240), (780, 286), (1085, 330)], stroke="#8E6AC8"),
            text(
                70,
                506,
                "Boundary rule: product modules stay API-facing; shared state lives behind services and repositories.",
                size=18,
                fill="#3E536B",
                weight=650,
            ),
        ]
    )
    return frame(1280, 580, body, title="Focus Agent platform topology")


def agent_team_dag() -> str:
    body = "\n".join(
        [
            card(
                70,
                134,
                210,
                116,
                "Mission",
                "Goal, constraints, context evidence",
                accent="#2FB7F5",
            ),
            card(
                350, 84, 210, 102, "Planner", "Task DAG and acceptance criteria", accent="#7A68D8"
            ),
            card(
                350,
                230,
                210,
                102,
                "Executor",
                "Implementation or deliverable branch",
                accent="#2CA874",
            ),
            card(650, 84, 210, 102, "Reviewer", "Risk report and findings", accent="#B65B76"),
            card(650, 230, 210, 102, "Verifier", "Regression and eval evidence", accent="#E49B23"),
            card(
                970,
                134,
                220,
                116,
                "Adoption Review",
                "Merge bundle, selected outputs, notes/tasks capture",
                accent="#245D9C",
            ),
            line(280, 192, 350, 136),
            line(280, 192, 350, 282),
            line(560, 136, 650, 136),
            line(560, 282, 650, 282),
            line(860, 136, 970, 192),
            line(860, 282, 970, 192),
            rect(458, 384, 360, 74, fill="#EEF7F4", stroke="#CDE7DD", radius=18),
            text(486, 416, "Agent Task Ledger + Trajectory", size=19, fill="#225B45", weight=850),
            text(
                486,
                440,
                "Every branch leaves evidence before final synthesis.",
                size=15,
                fill="#4F6B5F",
                weight=600,
            ),
            line(545, 332, 550, 384, stroke="#2CA874"),
            line(755, 332, 725, 384, stroke="#E49B23"),
        ]
    )
    return frame(1280, 540, body, title="Agent Team mission DAG")


def streaming_boundary() -> str:
    body = "\n".join(
        [
            card(
                62,
                128,
                210,
                116,
                "Model chunks",
                "Tool-bound, repair, reasoning, final answer",
                accent="#7A68D8",
            ),
            card(
                340,
                128,
                220,
                116,
                "Visibility gate",
                "quarantine by default; visible phase only",
                accent="#E49B23",
            ),
            card(
                640,
                88,
                220,
                100,
                "message.delta",
                "confirmed visible answer text",
                accent="#2CA874",
            ),
            card(
                640,
                230,
                220,
                100,
                "tool/task events",
                "structured processing cards",
                accent="#2FB7F5",
            ),
            card(
                940,
                128,
                230,
                116,
                "SDK reducer + UI",
                "safeVisibleTextTransition plus transcript filtering",
                accent="#B65B76",
            ),
            line(272, 186, 340, 186),
            line(560, 186, 640, 138, stroke="#2CA874"),
            line(560, 186, 640, 280, stroke="#2FB7F5"),
            line(860, 138, 940, 186, stroke="#2CA874"),
            line(860, 280, 940, 186, stroke="#2FB7F5"),
            rect(348, 286, 204, 56, fill="#FFF5DE", stroke="#F2D699", radius=16),
            text(
                374,
                319,
                "DSML / XML / tool prose stays internal",
                size=15,
                fill="#77521B",
                weight=800,
            ),
            line(442, 244, 442, 286, stroke="#E49B23", dash="6 8"),
        ]
    )
    return frame(1230, 460, body, title="Streaming quarantine boundary")


def memory_lifecycle() -> str:
    body = "\n".join(
        [
            card(
                60,
                120,
                190,
                104,
                "Retrieve",
                "namespace filters, FTS, optional vector",
                accent="#2FB7F5",
            ),
            card(
                310,
                120,
                190,
                104,
                "Assemble",
                "memory block enters context budget",
                accent="#7A68D8",
            ),
            card(
                560,
                120,
                190,
                104,
                "Agent turn",
                "tool loop, summary, branch findings",
                accent="#2CA874",
            ),
            card(810, 120, 190, 104, "Extract", "conservative write requests", accent="#E49B23"),
            card(
                1040, 120, 190, 104, "Policy", "dedupe, scope, visibility, audit", accent="#B65B76"
            ),
            line(250, 172, 310, 172),
            line(500, 172, 560, 172),
            line(750, 172, 810, 172),
            line(1000, 172, 1040, 172),
            card(
                210,
                334,
                240,
                102,
                "Canonical store",
                "focus_memories remains source of truth",
                accent="#245D9C",
            ),
            card(
                520,
                334,
                240,
                102,
                "Shadow index",
                "focus_memory_embeddings is rebuildable",
                accent="#2F9FAD",
            ),
            card(
                830,
                334,
                240,
                102,
                "Governance",
                "audit events, tombstones, candidates",
                accent="#8E6AC8",
            ),
            polyline([(1135, 224), (1135, 286), (330, 286), (330, 334)], stroke="#245D9C"),
            polyline([(1135, 224), (1135, 286), (640, 334)], stroke="#2F9FAD"),
            polyline([(1135, 224), (1135, 286), (950, 334)], stroke="#8E6AC8"),
        ]
    )
    return frame(1280, 520, body, title="Memory v2 lifecycle")


def tool_skill_runtime() -> str:
    body = "\n".join(
        [
            card(
                60,
                124,
                210,
                112,
                "User request",
                "task intent, prefixes, skill hints",
                accent="#2FB7F5",
            ),
            card(
                330,
                88,
                220,
                112,
                "Skill roots",
                "bundled SKILL.md plus local overlays",
                accent="#7A68D8",
            ),
            card(
                330,
                250,
                220,
                112,
                "Tool catalog",
                "workspace, web, artifact, memory, productivity",
                accent="#2CA874",
            ),
            card(
                640,
                124,
                230,
                112,
                "ChatService",
                "RequestContext, active skills, cleaned task",
                accent="#E49B23",
            ),
            card(
                950,
                124,
                230,
                112,
                "Graph runtime",
                "prompt blocks, tool router, guarded execution",
                accent="#B65B76",
            ),
            line(270, 180, 330, 144),
            line(270, 180, 330, 306),
            line(550, 144, 640, 180),
            line(550, 306, 640, 180, stroke="#2CA874"),
            line(870, 180, 950, 180),
            rect(664, 300, 486, 64, fill="#F4F8FC", stroke="#D5E3EF", radius=16),
            text(690, 326, "Runtime invariant", size=16, fill="#203854", weight=850),
            text(
                690,
                348,
                "Skills guide workflow; tools perform scoped side effects.",
                size=15,
                fill="#52677F",
                weight=600,
            ),
        ]
    )
    return frame(1240, 480, body, title="Skill prompt injection and tool narrowing")


def productivity_workflow() -> str:
    body = "\n".join(
        [
            card(
                64,
                118,
                190,
                110,
                "Sources",
                "chat answers, Agent Team reviews, tools",
                accent="#7A68D8",
            ),
            card(
                324,
                118,
                210,
                110,
                "Capture APIs",
                "normalize payload, source_kind, pinned context",
                accent="#2FB7F5",
            ),
            card(
                604,
                118,
                210,
                110,
                "ProductivityService",
                "title fallback, metadata, owner scope",
                accent="#E49B23",
            ),
            card(
                884, 80, 210, 96, "focus_notes", "durable notes with source links", accent="#2CA874"
            ),
            card(884, 222, 210, 96, "focus_tasks", "status, assignee, events", accent="#B65B76"),
            line(254, 174, 324, 174),
            line(534, 174, 604, 174),
            line(814, 174, 884, 128, stroke="#2CA874"),
            line(814, 174, 884, 270, stroke="#B65B76"),
            rect(432, 356, 430, 70, fill="#EFF7F4", stroke="#CDE7DD", radius=18),
            text(466, 386, "Web workbench", size=20, fill="#225B45", weight=850),
            text(
                466,
                411,
                "Notes and tasks preserve source trace back to the thread or review.",
                size=15,
                fill="#4F6B5F",
                weight=600,
            ),
            line(990, 318, 648, 356, stroke="#2CA874"),
        ]
    )
    return frame(1160, 500, body, title="Productivity capture and source trace")


def branch_action_lifecycle() -> str:
    body = "\n".join(
        [
            card(
                70,
                122,
                210,
                108,
                "Decision event",
                "pre-turn recommendation or post-turn evidence",
                accent="#7A68D8",
            ),
            card(
                350,
                122,
                220,
                108,
                "Pending action",
                "BranchActionProposal enters thread state",
                accent="#E49B23",
            ),
            card(
                650,
                72,
                210,
                98,
                "Confirm",
                "fork, open, or return with navigation",
                accent="#2CA874",
            ),
            card(
                650,
                244,
                210,
                98,
                "Dismiss",
                "mark action dismissed; no side effect",
                accent="#B65B76",
            ),
            card(
                950,
                122,
                210,
                108,
                "Refresh surfaces",
                "thread state, branch tree, route caches",
                accent="#2FB7F5",
            ),
            line(280, 176, 350, 176),
            line(570, 176, 650, 121, stroke="#2CA874"),
            line(570, 176, 650, 293, stroke="#B65B76"),
            line(860, 121, 950, 176, stroke="#2CA874"),
            line(860, 293, 950, 176, stroke="#B65B76"),
            rect(392, 370, 486, 60, fill="#FFF7E8", stroke="#F2D699", radius=16),
            text(
                420,
                405,
                "Safety boundary: recommendation never forks silently.",
                size=19,
                fill="#77521B",
                weight=850,
            ),
        ]
    )
    return frame(1230, 500, body, title="Branch Action lifecycle")


def quick_start_path() -> str:
    body = "\n".join(
        [
            card(70, 116, 180, 96, "Install", "uv, pnpm, setup-local", accent="#2FB7F5"),
            card(310, 116, 180, 96, "Config", ".focus_agent models/tools/env", accent="#7A68D8"),
            card(550, 116, 180, 96, "Start", "make api or make serve-dev", accent="#E49B23"),
            card(790, 68, 190, 92, "Managed DB", "repo-local PostgreSQL", accent="#2CA874"),
            card(790, 214, 190, 92, "External DB", "use DATABASE_URI", accent="#245D9C"),
            card(1040, 116, 180, 96, "Open /app", "auth, workbench, readyz", accent="#B65B76"),
            line(250, 164, 310, 164),
            line(490, 164, 550, 164),
            line(730, 164, 790, 114, stroke="#2CA874"),
            line(730, 164, 790, 260, stroke="#245D9C"),
            line(980, 114, 1040, 164, stroke="#2CA874"),
            line(980, 260, 1040, 164, stroke="#245D9C"),
            text(
                550,
                372,
                "The shortest path is local-first, with database choice made at startup.",
                size=18,
                fill="#3E536B",
                weight=650,
                anchor="middle",
            ),
        ]
    )
    return frame(1280, 450, body, title="Local startup decision path")


def validation_ladder() -> str:
    body = "\n".join(
        [
            card(62, 112, 170, 102, "Docs/assets", "link check, SVG render", accent="#2FB7F5"),
            card(274, 112, 170, 102, "Backend", "ruff, pytest, contracts", accent="#7A68D8"),
            card(486, 112, 170, 102, "Web", "lint, format, check, build", accent="#2CA874"),
            card(698, 112, 170, 102, "SDK", "types, build, transport", accent="#E49B23"),
            card(
                910, 112, 170, 102, "High risk", "streaming, auth, memory, branch", accent="#B65B76"
            ),
            card(
                536,
                300,
                220,
                96,
                "Release gate",
                "CI parity plus evidence reports",
                accent="#245D9C",
            ),
            line(232, 164, 274, 164),
            line(444, 164, 486, 164),
            line(656, 164, 698, 164),
            line(868, 164, 910, 164),
            polyline([(995, 214), (995, 258), (646, 258), (646, 300)], stroke="#245D9C"),
        ]
    )
    return frame(1140, 470, body, title="Validation ladder")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> int:
    write(ASSETS / "focus-agent-readme-hero.svg", hero(chinese=False))
    write(ASSETS / "focus-agent-readme-hero.zh-CN.svg", hero(chinese=True))
    write(DIAGRAMS / "architecture-platform-map.svg", platform_map())
    write(DIAGRAMS / "agent-team-mission-dag.svg", agent_team_dag())
    write(DIAGRAMS / "streaming-boundary.svg", streaming_boundary())
    write(DIAGRAMS / "memory-lifecycle.svg", memory_lifecycle())
    write(DIAGRAMS / "tool-skill-runtime.svg", tool_skill_runtime())
    write(DIAGRAMS / "productivity-workflow.svg", productivity_workflow())
    write(DIAGRAMS / "branch-action-lifecycle.svg", branch_action_lifecycle())
    write(DIAGRAMS / "quick-start-path.svg", quick_start_path())
    write(DIAGRAMS / "development-validation-ladder.svg", validation_ladder())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
