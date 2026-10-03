# DAG Templates

> **Historical refactor record.** These DAGs are design templates, not evidence
> that the corresponding multi-agent execution is enabled or that a template
> has passed current acceptance. See the [current capability baseline](../project-overview.md)
> and the 2026-09-28 [research](../plans/2026-09-28-agent-capabilities/research.md),
> [design](../plans/2026-09-28-agent-capabilities/design.md), and
> [plan](../plans/2026-09-28-agent-capabilities/plan.md).

## Research

`brief -> (research_a || research_b) -> synthesis -> report`

Resource claim examples: `data:source-set-a`, `data:source-set-b`, `file:docs/**`.

## Implementation

`design -> (backend || frontend) -> integration_test -> review`

Resource claim examples: `file:src/**`, `file:apps/**`, `file:tests/**`.

## Verification

`plan_verify -> (e2e_test || regression_test || perf_test) -> final_report`

Resource claim examples: `tool:test-runner`, `data:test-results`, `file:reports/**`.
