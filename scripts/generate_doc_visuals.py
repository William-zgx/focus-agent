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
    font = (
        "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Arial, sans-serif"
        if chinese
        else "Avenir Next, Nunito Sans, Segoe UI, Arial, sans-serif"
    )
    subtitle = "模型和你，都应该更专注" if chinese else "Keep the work focused."
    summary_lines = (
        ["适合研究型工作流：线程可分支、过程可实时看到，", "结论可有控制地回到主线。"]
        if chinese
        else [
            "Built for research flows where threads branch,",
            "tools stream, and conclusions merge back with control.",
        ]
    )
    pills = (
        [
            ("分支探索", 148, "#32C6FF"),
            ("实时输出", 132, "#2DE2A6"),
            ("回到主线", 116, "#FFB84D"),
            ("接口安全", 144, "#7DAEFF"),
        ]
        if chinese
        else [
            ("Branch-aware", 148, "#32C6FF"),
            ("Streaming", 132, "#2DE2A6"),
            ("Merge", 116, "#FFB84D"),
            ("Secure API", 144, "#7DAEFF"),
        ]
    )
    copy = {
        "console": "Focus Agent 控制台" if chinese else "Focus Agent Console",
        "threads": "线程" if chinese else "threads",
        "main": "主线" if chinese else "main",
        "verify": "验证" if chinese else "verify",
        "deep": "深挖" if chinese else "deep",
        "chat": "对话" if chinese else "chat",
        "prompt": "分析不同方案的取舍。" if chinese else "Research the trade-offs.",
        "stream": "回答片段持续输出中..." if chinese else "Streaming answer chunks...",
        "proposal": "分支建议" if chinese else "branch proposal",
        "proposal_line_1": (
            "创建一个验证分支，并让主线继续专注于"
            if chinese
            else "Create a verification branch and keep the"
        ),
        "proposal_line_2": "总结与综合。" if chinese else "main thread focused on synthesis.",
        "tools": "工具事件" if chinese else "tool events",
        "tool_summary_1": "更适合调试和可视化的" if chinese else "Structured tool lifecycle events",
        "tool_summary_2": "结构化工具事件。" if chinese else "for richer UI and debugging.",
    }
    parts = [
        '<defs><linearGradient id="bg" x1="74" y1="58" x2="1190" y2="592" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#07111D"/><stop offset="1" stop-color="#0C1E31"/></linearGradient><radialGradient id="glow1" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(1084 134) rotate(133.211) scale(430.27 506.809)"><stop stop-color="#39C5FF" stop-opacity="0.32"/><stop offset="1" stop-color="#39C5FF" stop-opacity="0"/></radialGradient><radialGradient id="glow2" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(318 600) rotate(-59.6054) scale(379.48 465.487)"><stop stop-color="#2DE2A6" stop-opacity="0.14"/><stop offset="1" stop-color="#2DE2A6" stop-opacity="0"/></radialGradient><linearGradient id="brand" x1="184" y1="154" x2="254" y2="240" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#32C6FF"/><stop offset="1" stop-color="#7DAEFF"/></linearGradient><linearGradient id="panelStroke" x1="724" y1="104" x2="1172" y2="548" gradientUnits="userSpaceOnUse"><stop stop-color="#DCEBFB" stop-opacity="0.92"/><stop offset="1" stop-color="#C9DCF1" stop-opacity="0.46"/></linearGradient><linearGradient id="pillBlue" x1="0" y1="0" x2="104" y2="40" gradientUnits="userSpaceOnUse"><stop stop-color="#10304E"/><stop offset="1" stop-color="#143A5E"/></linearGradient><filter id="shadow" x="684" y="86" width="520" height="490" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB"><feDropShadow dx="0" dy="26" stdDeviation="22" flood-color="#041C38" flood-opacity="0.34"/></filter></defs>',
        '<rect width="1280" height="640" rx="36" fill="url(#bg)"/>',
        '<rect width="1280" height="640" rx="36" fill="url(#glow1)"/>',
        '<rect width="1280" height="640" rx="36" fill="url(#glow2)"/>',
        '<g opacity="0.18"><path d="M88 82H1192" stroke="#82A7D1"/><path d="M88 558H1192" stroke="#82A7D1"/><path d="M88 82V558" stroke="#82A7D1"/><path d="M1192 82V558" stroke="#82A7D1"/></g>',
        rect(118, 126, 132, 132, fill="#F1F7FF", stroke="none", radius=34),
        '<circle cx="160" cy="191" r="24" stroke="url(#brand)" stroke-width="8"/><circle cx="160" cy="191" r="8.5" fill="url(#brand)"/><path d="M184 191H202V165H221" stroke="#16304F" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/><path d="M202 191V217H221" stroke="#16304F" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="221" cy="165" r="7.5" fill="#16304F"/><circle cx="202" cy="191" r="7.5" fill="#16304F"/><circle cx="221" cy="217" r="7.5" fill="#16304F"/>',
        text(118, 320, "Focus Agent", size=68, fill="#F5FAFF", weight=700, family=font),
        text(118, 370, subtitle, size=24, fill="#9DB8D6", weight=500, family=font),
    ]
    x = 118
    for label, width, dot in pills:
        parts.extend(
            [
                rect(x, 416, width, 42, fill="#122843", stroke="none", radius=21),
                f'<circle cx="{x + 22}" cy="437" r="6" fill="{dot}"/>',
                text(x + 38, 444, label, size=18, fill="#DDECFF", weight=600, family=font),
            ]
        )
        x += width + 12
    for index, line_text in enumerate(summary_lines):
        parts.append(
            text(
                118,
                500 + index * 26,
                line_text,
                size=18,
                fill="#DCEAFF",
                weight=500,
                family=font,
            )
        )
    parts.extend(
        [
            '<g filter="url(#shadow)">',
            rect(730, 130, 428, 402, fill="#F8FBFF", stroke="url(#panelStroke)", radius=30),
            rect(730, 130, 428, 46, fill="#EFF5FC", stroke="none", radius=30),
            '<circle cx="760" cy="153" r="6" fill="#FF8A8A"/><circle cx="780" cy="153" r="6" fill="#FFC857"/><circle cx="800" cy="153" r="6" fill="#49D98C"/>',
            text(834, 159, copy["console"], size=14, fill="#5E7898", weight=700, family=font),
            rect(752, 194, 108, 316, fill="#122A45", stroke="none", radius=20),
            text(770, 222, copy["threads"], size=11, fill="#8FC7FF", weight=700, family=font),
            rect(766, 238, 80, 40, fill="#1B4268", stroke="none", radius=14),
            '<circle cx="780" cy="258" r="5" fill="#32C6FF"/>',
            text(792, 262, copy["main"], size=13, fill="#EFF7FF", weight=700, family=font),
            rect(766, 288, 80, 40, fill="#173751", stroke="none", radius=14),
            '<circle cx="780" cy="308" r="5" fill="#2DE2A6"/>',
            text(792, 312, copy["verify"], size=13, fill="#DDECFF", weight=700, family=font),
            rect(766, 338, 80, 40, fill="#173751", stroke="none", radius=14),
            '<circle cx="780" cy="358" r="5" fill="#FFB84D"/>',
            text(792, 362, copy["deep"], size=13, fill="#DDECFF", weight=700, family=font),
            '<path d="M780 263V303" stroke="#4F7094" stroke-width="2" stroke-linecap="round"/>',
            '<path d="M780 313V353" stroke="#4F7094" stroke-width="2" stroke-linecap="round"/>',
            rect(878, 194, 258, 152, fill="#F2F7FD", stroke="none", radius=20),
            text(898, 220, copy["chat"], size=11, fill="#5D7798", weight=700, family=font),
            rect(894, 236, 158, 34, fill="#DBEAF8", stroke="none", radius=14),
            text(908, 257, copy["prompt"], size=13, fill="#24476B", weight=700, family=font),
            rect(966, 280, 154, 46, fill="#12304D", stroke="none", radius=16),
            text(980, 300, "message.delta", size=10, fill="#84CFFF", weight=700, family=MONO),
            text(980, 315, copy["stream"], size=12, fill="#F4FAFF", weight=600, family=font),
            rect(894, 356, 242, 58, fill="#F2F7FD", stroke="none", radius=18),
            text(912, 379, copy["proposal"], size=10, fill="#59B7EF", weight=700, family=font),
            text(
                912, 397, copy["proposal_line_1"], size=12, fill="#24476B", weight=600, family=font
            ),
            text(
                912, 412, copy["proposal_line_2"], size=12, fill="#24476B", weight=600, family=font
            ),
            rect(878, 430, 258, 88, fill="#112943", stroke="none", radius=20),
            text(898, 454, copy["tools"], size=11, fill="#8EF0CB", weight=700, family=font),
            rect(896, 466, 104, 24, fill="url(#pillBlue)", stroke="none", radius=12),
            text(911, 482, "search_code", size=12, fill="#DDECFF", weight=700, family=font),
            rect(1008, 466, 110, 24, fill="#183654", stroke="none", radius=12),
            text(1024, 482, "web_search", size=12, fill="#DDECFF", weight=700, family=font),
            text(
                898, 498, copy["tool_summary_1"], size=12, fill="#DDECFF", weight=600, family=font
            ),
            text(
                898, 512, copy["tool_summary_2"], size=12, fill="#DDECFF", weight=600, family=font
            ),
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
