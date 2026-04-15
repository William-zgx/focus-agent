---
name: tavily-search
description: Search the live web through Tavily when the task needs current information, source URLs, or a fast research backend for this project.
triggers: tavily:, web-search:, search-web:
when_to_use: The task needs current web information, You want direct search results with links, Another research workflow needs a fast search backend
prompt_mode: explore
---

# Tavily Search

Use this skill when this project should perform live web search with Tavily preferred and DuckDuckGo as fallback.

## Preconditions

- Network access must be available.
- `TAVILY_API_KEY` is optional but preferred; without it the runtime should fall back to DuckDuckGo.

## Default Command

```bash
./scripts/search "your query"
```

## Preferred Runtime Path

Inside Focus Agent, prefer calling the `web_search` tool instead of only describing a search plan. Use the shell script only as a local debugging fallback.

Useful variants:

```bash
./scripts/search --format json "your query"
./scripts/search --max-results 8 "your query"
```

## Search Guidance

- Use focused queries instead of broad keywords.
- When the user asks for "latest", "today", or "recent", include the real current date in the query.
- Prefer official docs, primary sources, and reputable publications when possible.
- Use this skill for retrieval first, then synthesize the answer from the returned evidence.
- Expect provider fallback: Tavily first when configured and healthy, DuckDuckGo otherwise.

## Output

Return the useful part of the search, not raw noise:

- the direct answer if one is supported by the evidence
- the most relevant URLs
- any uncertainty, staleness, or missing coverage
