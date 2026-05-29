#!/usr/bin/env python3
"""Shared SVG primitives for documentation visuals."""

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
