---
name: research
description: Investigate a question with multi-angle web research, full-source reading, and evidence-backed synthesis. Prefer this over a single shallow web_search.
triggers: research:, web-research:, deep-research:
when_to_use: The task needs current or external information, Options should be compared before choosing, A recommendation should be grounded in cited evidence, Content generation depends on non-trivial facts
recommended_tools: ask_user_question, web_search, web_fetch, current_utc_time, read_file, search_code, list_files, workspace_tree, write_text_artifact, artifact_read, artifact_update
prompt_mode: explore
---

# Research

Use this skill when the answer depends on collecting evidence instead of only reasoning from repository context or general knowledge.

**Core rule:** never generate non-trivial content from a single search or from model memory alone when the claim is time-sensitive, comparative, or high-stakes. Research quality bounds answer quality.

## Workflow

### Phase 0: Clarify (when needed)

If the question is ambiguous, ask **one focused clarifying question** (or a short ordered set) before deep research. Prefer `ask_user_question` when options are enumerable; otherwise ask in prose. Prefer clarifying over guessing scope, audience, or decision criteria.

### Phase 1: Orient

1. Call `current_utc_time` when recency matters so temporal search phrasing uses the real date.
2. Restate the decision or uncertainty to resolve, what a good answer must include, and what is out of scope.
3. Run an initial `web_search` for landscape orientation (do not skip this when the topic is external or current).

### Phase 2: Broad exploration

1. Identify 3–5 dimensions, subtopics, stakeholders, or angles from the first results.
2. Optionally track multi-step research with `tasks_create` / `tasks_update` (or a short plan in the reply) when the investigation has several independent strands.
3. Prefer official docs, vendor docs, specs, papers, and primary announcements over secondary blogs.

### Phase 3: Deep dive

For each important dimension:

1. Run targeted `web_search` queries with multiple phrasings.
2. Use `web_fetch` on the most important URLs — snippets alone are not enough for key claims.
3. Follow references when sources point at better primary material.
4. Use `list_files`, `workspace_tree`, `search_code`, and `read_file` when repository context changes the recommendation.

### Phase 4: Diversity and validation

Seek coverage across information types:

| Type | Purpose | Query hints |
|------|---------|-------------|
| Facts and data | Concrete evidence | statistics, numbers, market size, benchmarks |
| Examples and cases | Real applications | case study, implementation, postmortem |
| Expert views | Authority | analysis, interview, commentary |
| Trends | Direction | latest, forecast, adoption |
| Comparisons | Alternatives | vs, comparison, alternatives |
| Challenges | Balance | limitations, criticism, failure modes |

### Phase 5: Synthesis check (before answering)

- [ ] Searched from at least 3 different angles when the topic is multi-faceted
- [ ] Fetched and read the most important sources in full via `web_fetch`
- [ ] Have concrete data or examples, not only slogans
- [ ] Considered challenges or opposing views when they matter
- [ ] Information is current enough for the user's time intent

If any required box fails, continue researching before the final answer.

## Temporal awareness

Match search precision to user intent (use the real date from `current_utc_time`):

| User intent | Precision | Example pattern |
|-------------|-----------|-----------------|
| today / just released | month + day + year | `"tech news March 15 2026"` |
| this week | week range | `"releases week of Mar 10 2026"` |
| recently / latest | month + year | `"AI adoption March 2026"` |
| this year / trends | year | `"software trends 2026"` |

Do not drop to year-only when day-level freshness is required.

## Rules

- Do not present speculation as a confirmed fact.
- Call out staleness, incomplete evidence, and confidence limits.
- Prefer concise comparison tables when several options are involved.
- Save durable research deliverables with `write_text_artifact`, then iterate via `artifact_read` / `artifact_update`.
- After saving an artifact, surface the artifact id/path clearly so the user can open it (do not bury the deliverable only inside tool JSON).

## Output

Return:

- direct answer or recommendation
- most important supporting sources (with enough detail to re-find them)
- key tradeoffs, caveats, or follow-up checks
- path or id of any saved artifact
