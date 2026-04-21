# Tool and Skill System Design

This document defines the current boundary between low-level tools and higher-level skills in Focus Agent, the runtime shape of the skill system, and the remaining product-tool backlog.

## Goals

- Keep tools small, safe, auditable, and easy to test.
- Let skills describe reusable workflows instead of hardcoding workflows into tools.
- Add product capabilities that make the agent useful in normal conversations, not only codebase work.
- Preserve Focus Agent's branch-aware conversation model while expanding beyond developer-only tools.

## Non-goals

- Do not add an unrestricted shell tool as a general escape hatch.
- Do not make every common prompt pattern into a tool.
- Do not put personal account integrations such as calendar, mail, Notion, or Lark into the default builtin tool set.
- Do not make provider-specific details part of public tool or skill names when a stable abstraction is possible.

## Core Distinction

Tools are capabilities. Skills are workflows.

A tool should answer: "What concrete operation can the agent perform?"

A skill should answer: "How should the agent approach this kind of task?"

The intended flow is:

```text
User request
  -> Skill selects the working method
  -> Tool performs concrete operations
  -> Memory, notes, tasks, artifacts, or conversation state persist the result
```

## Tool Boundary

A tool is a narrow primitive that touches the outside world or persistent state.

Good tools:

- perform one clear operation
- have explicit inputs and structured outputs
- are scoped by workspace, user, thread, or configured provider
- can be enabled, disabled, renamed, and tested independently
- expose product capability without encoding a full business workflow

Examples:

- `web_search`: search the live web
- `web_fetch`: fetch and extract content from one URL
- `memory_save`: save an explicit memory
- `memory_search`: retrieve relevant memories
- `artifact_read`: read a saved artifact
- `tasks_create`: create a task

Poor tools:

- `competitor_analysis_tool`
- `meeting_summary_tool`
- `release_strategy_tool`
- `write_my_weekly_report_tool`

Those are workflows and should usually be skills that combine primitives.

## Reference Notes

The nearby Hermes agent and DeerFlow projects point in the same direction:

- Hermes organizes capabilities into toolsets such as web, file, skills, memory, todo, browser, and terminal. The useful lesson for Focus Agent is tool grouping and explicit toolset boundaries, not adopting every high-power tool by default.
- DeerFlow describes its core toolset as web search, web fetch, file operations, and bash execution, while skills remain structured Markdown workflows. The useful lesson is that web fetch is a first-class primitive and skills should stay progressively loaded.

Focus Agent should stay smaller by default: no unrestricted bash, no browser/computer control, and no account-backed connectors in the builtin baseline.

## Skill Boundary

A skill is prompt-level guidance for a repeatable task pattern. It can decide when and how to combine tools, but it should not claim hidden capabilities that the runtime cannot provide.

Good skills:

- define a workflow, decision standard, or output format
- reference real tools exposed by the runtime
- stay concise because active skill text is injected into the system prompt
- work across projects when placed in builtin skills
- capture personal or team-specific conventions when placed in local skills

Examples:

- `research`: use `web_search`, `web_fetch`, and artifacts to answer evidence-dependent questions
- `meeting-notes`: save meeting notes and create tasks from action items
- `personal-assistant`: decide whether information belongs in memory, notes, tasks, or an artifact
- `writing-plans`: create and update implementation plans as artifacts
- `release-readiness`: apply the repository's release checklist and produce a readiness report

## Skill Runtime

Focus Agent's skill runtime is prompt-first and local-first. It supports discovery, activation, prompt injection, and basic inspection tools without introducing a remote skills marketplace or hidden multi-agent orchestration.

### Directory layout

- Python runtime: `src/focus_agent/skills/`
- Bundled skills: `src/focus_agent/skills/builtin/<skill>/SKILL.md`
- Optional local overlays: `FOCUS_AGENT_SKILLS_DIRS` or the default `.focus_agent/skills`

Bundled skills are versioned with the repo so the agent has a stable baseline even when no local skills exist. Local overlays are intended for per-user or per-maintainer workflows and are typically kept out of git.

### Skill document format

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

The parser is intentionally minimal and optimized for bundled skills plus straightforward local overrides.

### Runtime flow

1. `SkillRegistry` scans configured roots plus bundled skills and builds an in-memory index.
2. Skills activate through API `skill_hints` or prefix triggers such as `plan:` and `review:`.
3. `ChatService` resolves active skills, writes skill hints into `RequestContext`, persists `active_skill_ids`, and uses the cleaned task as `task_brief`.
4. `graph_builder` asks the registry for available-skill and active-skill prompt blocks.
5. `context_policy` renders those blocks into the final system prompt alongside scene, branch scope, memory, and findings.

### Built-in skills

Current bundled skills:

- `autopilot`
- `codebase-inspection`
- `code-documentation`
- `eco`
- `plan`
- `research`
- `ralph`
- `review`
- `security-review`
- `systematic-debugging`
- `tdd`
- `ultrawork`
- `writing-plans`

These skills intentionally steer behavior that the current runtime can already support. For example, `ultrawork` encourages workstream decomposition, but it does not claim hidden sub-agent execution.

### Current limitations

- The frontmatter parser is deliberately simple and not a full YAML implementation.
- Skill prompts are injected as plain text blocks; there is no scoring/ranking stage yet.
- The system does not yet persist skill metadata snapshots or support linked reference files.
- Skill selection is prefix/hint based; semantic auto-matching is future work.

## Connector Boundary

Connectors are account-backed integrations. They should generally be optional and user-local.

Examples:

- calendar
- email
- cloud drive
- Notion
- Lark
- GitHub write operations

Connector-backed tools can follow the same tool rules, but they should not be enabled by default for every user because they depend on identity, permissions, and organization policy.

## Storage Boundary

Product tools should write to explicit product stores rather than hiding state in prompt text.

Recommended stores:

- Memory: small durable facts, user preferences, and reusable context.
- Notes: structured long-form records such as decisions, meeting notes, discoveries, and project context.
- Tasks: actionable items with status, due date, and optional source thread.
- Artifacts: generated documents or drafts that can be listed, read, and revised.
- Conversation state: thread, branch, merge, and summary data owned by Focus Agent.

## Builtin vs User-Local Placement

Builtin tools should be general, safe, and useful for most installations.

User-local tools or connector tools should cover personal accounts, company workflows, private systems, or high-risk permissions.

Builtin skills should describe cross-user workflows.

User-local skills should describe personal preferences, team templates, or organization-specific operating procedures.

## Current Baseline

Focus Agent already has these default tools:

- `current_utc_time`
- `write_text_artifact`
- `artifact_list`
- `artifact_read`
- `artifact_update`
- `list_files`
- `read_file`
- `search_code`
- `codebase_stats`
- `git_status`
- `git_diff`
- `git_log`
- `web_fetch`
- `memory_save`
- `memory_search`
- `memory_forget`
- `conversation_summary`
- `web_search`
- `skills_list`
- `skill_view`

The newer product primitives make the agent useful beyond repository work: explicit memory control, URL reading, artifact iteration, and conversation summarization.

## Tool Runtime Policy

Tool execution is mediated by runtime metadata rather than ad hoc logic in each graph node.

- `parallel_safe` read-only tools can run in the same tool round concurrently.
- `cacheable` tools may reuse deterministic observations within their declared scope.
- `side_effect` tools keep a serial boundary and invalidate the current turn/thread/branch namespaces after a successful write.
- `fallback_group` and `fallback_handler` keep provider fallback behind the stable public tool name.
- Runtime observations are trimmed by per-tool limits before being returned to the model.

Cache scopes are intentionally conservative:

- `turn` is for values that should only survive within one user turn. The namespace includes the root thread and turn id, so parallel conversations do not clear each other.
- `thread` is the default for workspace read tools such as `list_files`, `read_file`, `search_code`, and `codebase_stats`. Focus Agent conversation branches do not imply separate filesystem or git worktrees, so these reads should not become branch-local by default.
- `branch` is reserved for future tools that read or write branch-local product state.

Execution control fields that require cancellation or hard deadlines should not be exposed until the runtime can enforce them. In particular, timeout/cancel behavior should be treated as a separate runtime feature, not as passive metadata.

## Product Tool Taxonomy

### Retrieval Tools

Retrieval tools gather information from external or local sources.

- `web_search`
- `web_fetch`
- `knowledge_search`
- `memory_search`
- `notes_search`
- `artifact_search`

### Persistence Tools

Persistence tools save or update user-visible state.

- `memory_save`
- `memory_forget`
- `notes_create`
- `notes_update`
- `tasks_create`
- `tasks_update`
- `artifact_write`
- `artifact_update`

### Conversation Tools

Conversation tools operate on Focus Agent's own thread and branch model.

- `conversation_summary`
- `conversation_export`
- `branch_tree_inspect`
- `merge_proposal_inspect`

### Utility Tools

Utility tools provide deterministic helper capabilities.

- `current_utc_time`
- `structured_compute`
- `template_apply`

## Implemented Product Primitives

The first general-agent batch is now part of the baseline:

- Artifact iteration: `write_text_artifact`, `artifact_list`, `artifact_read`, `artifact_update`
- Web retrieval: `web_search`, `web_fetch`
- Explicit memory control: `memory_save`, `memory_search`, `memory_forget`
- Conversation recovery: `conversation_summary`
- Skill inspection: `skills_list`, `skill_view`

These capabilities are still primitives. For example, `research` decides how to gather and synthesize evidence, while `web_search`, `web_fetch`, and artifact tools perform the concrete operations.

Current bundled skills already consume these primitives:

- `research` uses `web_search`, `web_fetch`, and artifacts for evidence-backed answers.
- `writing-plans` uses artifact list/read/update for iterative plans.
- `autopilot` may save durable deliverables as artifacts and use memory for explicit durable facts.

## Backlog

The next product-tool expansion should focus on stores that are currently only conceptual:

- Notes: `notes_create`, `notes_search`, `notes_update`
- Tasks: `tasks_create`, `tasks_list`, `tasks_update`

Notes and tasks should be first-class product data with explicit storage, API, tests, and UI affordances. They should not be simulated with hidden prompt conventions or arbitrary markdown files.

Potential future skills after those stores exist:

- `personal-assistant`: route requests to memory, notes, tasks, or artifacts.
- `meeting-notes`: turn notes into action items using notes and tasks tools.
- `project-catchup`: summarize a conversation and save follow-up tasks or notes.

## Permission and Safety Rules

- Read tools should be explicit about scope and truncation.
- Write tools should return stable ids or paths for follow-up turns.
- Destructive tools should either be explicit privacy controls, such as `memory_forget`, or use reversible and soft-delete behavior first.
- Connector tools should default off and require user configuration.
- Tools should emit structured tool events so the frontend can show clear activity cards.
- Sensitive configuration should report presence or absence, never raw secrets.

## Design Checklist for New Tools

Before adding a tool, answer:

- Is this a primitive capability rather than a workflow?
- Can a skill combine existing tools to achieve the same result?
- What persistent store does it read or write?
- What permission boundary limits the operation?
- What structured output will the model and UI consume?
- How is truncation handled?
- How is the tool disabled or configured?
- What tests prove the boundary?
