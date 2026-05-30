#!/usr/bin/env python3
"""Secondary documentation diagram builders."""

from __future__ import annotations

from doc_visual_primitives import card, frame, line, polyline, rect, text


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
                "Local gates plus evidence reports",
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
