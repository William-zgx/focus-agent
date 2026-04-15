---
name: consulting-analysis
description: Produce consulting-style analysis frameworks and final reports from real research inputs, with clear structure, evidence discipline, and executive-ready synthesis.
triggers: consulting:, consulting-analysis:
when_to_use: The user wants a professional analytical report, A market or industry topic needs a structured framework, Research findings should be synthesized into consulting-style output
prompt_mode: synthesize
---

# Consulting Analysis

Use this skill for research work that needs to read like a professional report rather than a loose answer.

## Two-Phase Model

### Phase 1: Framework

When the user has a topic but not the data package yet, produce:

- research objective
- scope and assumptions
- chapter outline
- key hypotheses
- data requirements by chapter
- suggested search angles and source types
- recommended tables or charts

### Phase 2: Final Report

When the user already has evidence, synthesize it into a polished report with:

- executive summary
- clear chapter structure
- evidence-backed narrative
- tables or charts when available
- references or links for major claims

## Evidence Rules

- Do not invent numbers, quotes, or market facts.
- If evidence is incomplete, flag the gap instead of smoothing it over.
- Use tables when charts are unavailable.
- Keep claims traceable to the supplied data, notes, or search findings.

## Style

- Write with an objective, executive-friendly tone.
- Move from finding to implication, not just raw observation.
- Separate facts, interpretation, and recommendation when the distinction matters.
- Prefer a small number of sharp insights over repetitive filler.

## Output Shape

For framework requests, return an actionable research blueprint.

For final-report requests, return a complete report that someone could hand to a stakeholder with minimal cleanup.
