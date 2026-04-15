---
name: codebase-inspection
description: Inspect repository size, language mix, and line counts using project-local tooling such as pygount, rg, and wc.
triggers: loc:, inspect-codebase:
when_to_use: The user wants codebase metrics, You need language or LOC breakdowns, Repository size or composition matters to the answer
prompt_mode: explore
---

# Codebase Inspection

Measure the repository with the best available project tool and report the method you used.

## Preferred Method

Use `codebase_stats` for file counts, line counts, and language breakdown.

## Fallback Method

If you need a narrower slice, combine `list_files`, `search_code`, and `read_file` to inspect specific directories or file families and label the result as a targeted sample.

## Rules

- Always exclude dependency, cache, and build output directories.
- Distinguish between exact counts and estimates.
- Explain notable caveats such as generated code, vendored code, Markdown-heavy repos, or large JSON datasets.
- Prefer answering the user's actual question over dumping every metric you can compute.

## Good Output

Return a compact summary with:

- scope scanned
- method used
- language or directory breakdown
- any caveats that materially affect interpretation
