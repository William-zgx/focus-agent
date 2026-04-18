---
name: research
description: Investigate a question with disciplined source gathering, comparison, and evidence-backed synthesis.
triggers: research:, web-research:
when_to_use: The task needs current or external information, Options should be compared before choosing, A recommendation should be grounded in cited evidence
recommended_tools: web_search, web_fetch, read_file, search_code, write_text_artifact, artifact_read, artifact_update
prompt_mode: explore
---

# Research

Use this skill when the answer depends on collecting evidence instead of only reasoning from repository context.

## Workflow

1. Define the question precisely:
   - what decision or uncertainty needs to be resolved
   - what a good answer must include
   - what scope is intentionally out of bounds
2. Gather the best available evidence:
   - prefer `web_search` for current external information
   - use `web_fetch` when the user provides a specific URL or a search result needs direct reading
   - prefer official docs, vendor docs, specs, papers, and primary announcements
   - use `read_file` and `search_code` when repository context changes the recommendation
3. Compare options explicitly:
   - strengths
   - limitations
   - compatibility with this project
   - operational or maintenance risk
4. Synthesize:
   - direct answer
   - recommendation
   - supporting evidence
   - caveats or missing data

## Rules

- Do not present speculation as a confirmed fact.
- Call out staleness or incomplete evidence when it matters.
- When the user asks for the latest status, verify with live search instead of relying on memory.
- Save durable research deliverables with `write_text_artifact`, then use `artifact_read` or `artifact_update` for follow-up revisions.
- Prefer concise comparison tables over long prose when several options are involved.

## Output

Return:

- the answer or recommendation
- the most important supporting sources
- any important tradeoffs or follow-up checks
