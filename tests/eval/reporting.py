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
    summary_dict = summary.to_dict()
    structured_summary_keys = {
        "per_tag_success",
        "per_capability_success",
        "per_risk_level_success",
        "flaky_case_ids",
        "failure_clusters",
        "model_matrix",
    }
    summary_rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td>{escape(str(value))}</td></tr>"
        for key, value in summary_dict.items()
        if key not in structured_summary_keys
    )
    per_tag_rows = _render_mapping_rows(
        summary_dict.get("per_tag_success"),
        "No tag breakdown available.",
    )
    per_capability_rows = _render_mapping_rows(
        summary_dict.get("per_capability_success"),
        "No capability breakdown available.",
    )
    per_risk_level_rows = _render_mapping_rows(
        summary_dict.get("per_risk_level_success"),
        "No risk-level breakdown available.",
    )
    model_matrix_rows = _render_model_matrix_rows(summary_dict.get("model_matrix"))
    failure_cluster_rows = _render_failure_cluster_rows(summary_dict.get("failure_clusters"))
    flaky_case_rows = _render_flaky_case_rows(summary_dict.get("flaky_case_ids"))
    collaboration_rows = _render_collaboration_rows(summary_dict)
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
    .nowrap {{
      white-space: nowrap;
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
    <section>
      <h2>Capability Success</h2>
      <table>
        {per_capability_rows}
      </table>
    </section>
    <section>
      <h2>Risk Level Success</h2>
      <table>
        {per_risk_level_rows}
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
    <section>
      <h2>Collaboration Summary</h2>
      <table>
        {collaboration_rows}
      </table>
    </section>
  </div>
  <section style="margin-top: 20px;">
    <h2>Model Matrix</h2>
    <table>
      <thead>
        <tr>
          <th>Model Label</th>
          <th>Model</th>
          <th>Cases</th>
          <th>Passed</th>
          <th>Success</th>
          <th>Latency (ms)</th>
          <th>Cost</th>
        </tr>
      </thead>
      <tbody>
        {model_matrix_rows}
      </tbody>
    </table>
  </section>
  <div class="grid" style="margin-top: 20px;">
    <section>
      <h2>Failure Clusters</h2>
      <table>
        <thead>
          <tr>
            <th>Cluster</th>
            <th>Count</th>
            <th>Cases</th>
          </tr>
        </thead>
        <tbody>
          {failure_cluster_rows}
        </tbody>
      </table>
    </section>
    <section>
      <h2>Flaky Cases</h2>
      <table>
        <tbody>
          {flaky_case_rows}
        </tbody>
      </table>
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


def _render_mapping_rows(mapping: Any, empty_message: str) -> str:
    if not isinstance(mapping, dict) or not mapping:
        return f'<tr><td colspan="2">{escape(empty_message)}</td></tr>'
    return "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in sorted(mapping.items())
    )


def _render_model_matrix_rows(model_matrix: Any) -> str:
    if not isinstance(model_matrix, dict) or not model_matrix:
        return '<tr><td colspan="7">No model matrix available.</td></tr>'

    rows: list[str] = []
    for model_label, row in sorted(model_matrix.items()):
        if not isinstance(row, dict):
            continue
        cases = row.get("cases")
        case_count = len(cases) if isinstance(cases, dict) else 0
        rows.append(
            "<tr>"
            f"<td><code>{escape(str(model_label))}</code></td>"
            f"<td>{escape(str(row.get('model') or '-'))}</td>"
            f"<td class=\"nowrap\">{case_count}</td>"
            f"<td class=\"nowrap\">{escape(str(row.get('passed', 0)))}"
            f" / {escape(str(row.get('total', 0)))}</td>"
            f"<td class=\"nowrap\">{escape(str(row.get('task_success', 0.0)))}</td>"
            f"<td class=\"nowrap\">{escape(str(row.get('avg_latency_ms', 0.0)))}</td>"
            f"<td class=\"nowrap\">{escape(str(row.get('avg_cost_usd', 0.0)))}</td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="7">No model matrix available.</td></tr>'


def _render_failure_cluster_rows(failure_clusters: Any) -> str:
    if not isinstance(failure_clusters, list) or not failure_clusters:
        return '<tr><td colspan="3">No failure clusters available.</td></tr>'

    rows: list[str] = []
    for cluster in failure_clusters:
        if not isinstance(cluster, dict):
            continue
        case_ids = cluster.get("case_ids") or []
        if isinstance(case_ids, list):
            case_text = ", ".join(str(case_id) for case_id in case_ids[:12])
            if len(case_ids) > 12:
                case_text = f"{case_text}, ..."
        else:
            case_text = str(case_ids)
        rows.append(
            "<tr>"
            f"<td>{escape(str(cluster.get('cluster') or cluster.get('reason') or '-'))}</td>"
            f"<td class=\"nowrap\">{escape(str(cluster.get('count', 0)))}</td>"
            f"<td><code>{escape(case_text or '-')}</code></td>"
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="3">No failure clusters available.</td></tr>'


def _render_flaky_case_rows(flaky_case_ids: Any) -> str:
    if not isinstance(flaky_case_ids, list) or not flaky_case_ids:
        return '<tr><td>No flaky cases detected.</td></tr>'
    return "\n".join(
        f"<tr><td><code>{escape(str(case_id))}</code></td></tr>"
        for case_id in flaky_case_ids
    )


def _render_collaboration_rows(summary: dict[str, Any]) -> str:
    fields = [
        ("avg_delegation_role_hits", "Avg delegation role hits"),
        ("delegation_role_hit_rate", "Delegation role hit rate"),
        ("avg_handoff_hits", "Avg handoff hits"),
        ("handoff_hit_rate", "Handoff hit rate"),
        ("avg_critic_gate_hits", "Avg critic gate hits"),
        ("critic_gate_hit_rate", "Critic gate hit rate"),
        ("avg_fallback_uses", "Avg fallback uses"),
        ("fallback_use_rate", "Fallback use rate"),
        ("avg_parallel_tool_calls", "Avg parallel tool calls"),
        ("parallel_tool_call_rate", "Parallel tool call rate"),
        ("avg_environment_assertions_failed", "Avg environment assertion failures"),
        ("environment_assertion_failure_rate", "Environment assertion failure rate"),
    ]
    return "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(summary.get(key, 0)))}</td></tr>"
        for key, label in fields
    )


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
