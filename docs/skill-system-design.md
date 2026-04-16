# Focus Agent Skill System Design

## Goals

- Add a lightweight Skill system inspired by `hermes-agent`, but sized for the current Focus Agent runtime.
- Keep the implementation prompt-first and local-first: discovery, activation, prompt injection, and basic inspection tools.
- Make the existing `AGENTS.md` mode prefixes usable by the agent without introducing a full skills hub or installer.

## Non-goals

- No remote skill marketplace, install/uninstall workflow, or skill patching API in this iteration.
- No dynamic model routing or hidden multi-agent orchestration.
- No support for arbitrary linked files under a skill yet; this first cut only loads `SKILL.md`.

## Directory layout

- Python runtime: `src/focus_agent/skills/`
- Bundled skills: `src/focus_agent/skills/builtin/<skill>/SKILL.md`
- Optional local overlays: `FOCUS_AGENT_SKILLS_DIRS` or the default `.focus_agent/skills`

Bundled skills are versioned with the repo so the agent has a stable baseline even when no local skills exist.

## Skill document format

Each skill is a directory containing `SKILL.md` with simple YAML-like frontmatter:

```md
---
name: plan
description: Planning-only mode for decomposition and sequencing
triggers: plan:
when_to_use: The user wants a plan first, The work has multiple phases
prompt_mode: explore
---
```

Supported metadata in this iteration:

- `name`
- `description`
- `triggers`
- `when_to_use`
- `prompt_mode`

The parser is intentionally minimal and optimized for our bundled skills plus straightforward local overrides.

## Compatibility conventions

Skills in this repository should be rewritten into Focus-Agent-native instructions instead of being copied verbatim from other runtimes.

- Every shipped skill should define `triggers`, `when_to_use`, and `prompt_mode`.
- Skill bodies should reference real capabilities available in this repo: Focus-Agent-native repository tools, git inspection helpers, artifact tools, and configured web/search tools.
- Imported skills should remove legacy runtime assumptions such as Hermes-only helper tools, upload-directory paths, or hidden subagent APIs.
- Keep active skill bodies concise because they are injected directly into the system prompt for the current turn.

## Runtime flow

### 1. Discovery

`SkillRegistry` scans configured skill roots plus the bundled skill directory and builds an in-memory index keyed by normalized skill name.

### 2. Activation

Skills can activate in two ways:

- Explicit request hints from the API payload via `skill_hints`
- Prefix triggers in the user message, such as `plan:` or `review:`

Prefix activation is stackable, so a message can activate more than one skill if it begins with multiple known prefixes.

### 3. State + context propagation

When a turn is sent:

- `ChatService` resolves active skills
- resolved `skill_hints` are written into `RequestContext`
- `active_skill_ids` are persisted in graph state for resume flows
- the cleaned task text becomes `task_brief`

This is important because resume requests do not carry the original message prefix again.

### 4. Prompt injection

`graph_builder` asks the registry for:

- an available-skills index block
- an active-skills instructions block

`context_policy` then renders those blocks into the final system prompt alongside scene, branch scope, memory, and findings.

### 5. Tool surface

The new `ToolRegistry` composes default tools with two skill tools:

- repository inspection tools such as `list_files`, `read_file`, `search_code`, `codebase_stats`, `git_status`, `git_diff`, and `git_log`
- the shared `web_search` tool for live web lookup
- `skills_list`
- `skill_view`

This keeps the system aligned with the Hermes progressive-disclosure model, even though the first version only supports viewing `SKILL.md`.

## Built-in skills

This iteration bundles a pragmatic baseline:

- `autopilot`
- `codebase-inspection`
- `code-documentation`
- `consulting-analysis`
- `eco`
- `github-code-review`
- `plan`
- `ralph`
- `review`
- `systematic-debugging`
- `tdd`
- `ultrawork`
- `writing-plans`

These skills intentionally steer behavior that the current runtime can already support. For example, `ultrawork` encourages workstream decomposition, but it does not claim hidden sub-agent execution.

We also copy a small number of practical skills from local reference repositories such as `hermes-agent` and `deer-flow`, then rewrite them into shorter Focus-Agent-specific variants so they can be activated safely in this runtime.

## Configuration

`Settings.skill_directories` is populated from `FOCUS_AGENT_SKILLS_DIRS` as a comma-separated list. Missing directories are ignored, which keeps local development simple.

## Current limitations

- The frontmatter parser is deliberately simple and not a full YAML implementation.
- Skill prompts are injected as plain text blocks; there is no scoring/ranking stage yet.
- The system does not yet persist skill metadata snapshots or support linked reference files.
- Skill selection is prefix/hint based; semantic auto-matching is future work.
- Search-capable skills should prefer stable runtime tools such as `web_search`; provider-specific backends like Tavily should stay behind that tool boundary when possible.

## Next steps

1. Add linked-file loading inside a skill directory, mirroring Hermes `skill_view(name, file_path=...)`.
2. Add skill authoring/patching APIs once we have a stable review and persistence story.
3. Feed skill metadata into memory and MCP routing so skills can bias retrieval and tool availability.
4. Introduce stronger conflict handling when multiple active skills want incompatible prompt modes.
