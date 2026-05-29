#!/usr/bin/env python3
"""Generate checked-in documentation SVG assets."""

from __future__ import annotations

from pathlib import Path

from doc_visual_diagrams import (
    agent_team_dag,
    branch_action_lifecycle,
    memory_lifecycle,
    platform_map,
    productivity_workflow,
    quick_start_path,
    streaming_boundary,
    tool_skill_runtime,
    validation_ladder,
)
from doc_visual_primitives import ASSETS, DIAGRAMS, MONO, ROOT, rect, text


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
