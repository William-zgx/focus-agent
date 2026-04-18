"""Report helpers for the agent eval framework."""

from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any, Iterable

from .metrics import MetricSummary
from .schema import EvalResult


def write_json_report(
    path: str | Path,
    *,
    summary: MetricSummary,
    results: Iterable[EvalResult],
    comparison: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": dict(meta or {}),
        "summary": summary.to_dict(),
        "comparison": comparison or {},
        "results": [result.to_dict() for result in results],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def write_jsonl_results(path: str | Path, results: Iterable[EvalResult]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(result.to_dict(), ensure_ascii=False) for result in results]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def write_html_report(
    path: str | Path,
    *,
    summary: MetricSummary,
    results: Iterable[EvalResult],
    comparison: dict[str, Any] | None = None,
    title: str = "Focus Agent Eval Report",
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    result_list = list(results)
    regressions = list((comparison or {}).get("regressions") or [])
    summary_rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td>{escape(str(value))}</td></tr>"
        for key, value in summary.to_dict().items()
        if key != "per_tag_success"
    )
    per_tag = summary.to_dict().get("per_tag_success") or {}
    per_tag_rows = "\n".join(
        f"<tr><th>{escape(tag)}</th><td>{escape(str(value))}</td></tr>"
        for tag, value in per_tag.items()
    ) or '<tr><td colspan="2">No tag breakdown available.</td></tr>'
    result_rows = "\n".join(_render_result_row(result) for result in result_list) or (
        '<tr><td colspan="6">No results.</td></tr>'
    )
    regression_items = "\n".join(f"<li>{escape(item)}</li>" for item in regressions) or (
        "<li>No regressions detected.</li>"
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    body {{
      font-family: "Segoe UI", Arial, sans-serif;
      margin: 24px;
      color: #1f2937;
      background: #f8fafc;
    }}
    h1, h2 {{
      margin-bottom: 12px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px;
    }}
    section {{
      background: white;
      border: 1px solid #dbe2ea;
      border-radius: 12px;
      padding: 16px 18px;
      box-shadow: 0 2px 12px rgba(15, 23, 42, 0.05);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid #e5e7eb;
      vertical-align: top;
    }}
    .pass {{
      color: #166534;
      font-weight: 600;
    }}
    .fail {{
      color: #991b1b;
      font-weight: 600;
    }}
    code {{
      font-family: "Cascadia Code", Consolas, monospace;
      font-size: 0.95em;
    }}
    ul {{
      margin: 0;
      padding-left: 20px;
    }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <div class="grid">
    <section>
      <h2>Summary</h2>
      <table>
        {summary_rows}
      </table>
    </section>
    <section>
      <h2>Per Tag Success</h2>
      <table>
        {per_tag_rows}
      </table>
    </section>
  </div>
  <div class="grid" style="margin-top: 20px;">
    <section>
      <h2>Regression Gate</h2>
      <ul>
        {regression_items}
      </ul>
    </section>
  </div>
  <section style="margin-top: 20px;">
    <h2>Per Case</h2>
    <table>
      <thead>
        <tr>
          <th>Case</th>
          <th>Status</th>
          <th>Tags</th>
          <th>Tools</th>
          <th>Latency (ms)</th>
          <th>Notes</th>
        </tr>
      </thead>
      <tbody>
        {result_rows}
      </tbody>
    </table>
  </section>
</body>
</html>
"""
    target.write_text(html, encoding="utf-8")
    return target


def load_metric_summary(path: str | Path) -> MetricSummary:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "summary" in payload and isinstance(payload["summary"], dict):
        payload = payload["summary"]
    summary = MetricSummary()
    for key, value in payload.items():
        if hasattr(summary, key):
            setattr(summary, key, value)
    return summary


def load_result_records(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        return []

    if source.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    payload = json.loads(text)
    if isinstance(payload, dict):
        records = payload.get("results")
        if isinstance(records, list):
            return [record for record in records if isinstance(record, dict)]
        if {"case_id", "passed"} <= set(payload):
            return [payload]
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    raise ValueError(f"unsupported replay payload: {source}")


def _render_result_row(result: EvalResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    status_class = "pass" if result.passed else "fail"
    verdict_notes = "; ".join(
        f"{verdict.kind}: {verdict.reasoning}" for verdict in result.verdicts if verdict.reasoning
    ) or (result.error or "")
    tools = ", ".join(step.tool for step in result.trajectory) or "-"
    tags = ", ".join(result.tags) or "-"
    latency = result.metrics.get("latency_ms", 0.0)
    return (
        "<tr>"
        f"<td><code>{escape(result.case_id)}</code></td>"
        f"<td class=\"{status_class}\">{status}</td>"
        f"<td>{escape(tags)}</td>"
        f"<td>{escape(tools)}</td>"
        f"<td>{escape(str(round(float(latency), 1)))}</td>"
        f"<td>{escape(verdict_notes[:240])}</td>"
        "</tr>"
    )
