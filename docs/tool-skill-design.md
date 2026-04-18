# Tool and Skill Boundary Design

This document defines how Focus Agent should separate low-level tools from higher-level skills, then derives the first product-oriented tool batch for a more general-purpose conversational agent experience.

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

## First Implementation Batch

The first batch should prioritize product value while reusing as much existing infrastructure as possible.

### Batch 1A: Minimal general-agent primitives

These are implemented first because they are the smallest broadly useful capabilities for a general conversational agent.

1. `artifact_list`

List saved artifacts under the configured artifact directory with title, path, updated time, and size.

Why first:

- `write_text_artifact` already exists.
- Listing is a natural complement to writing.
- It makes generated plans and reports reusable across turns.

2. `artifact_read`

Read one saved artifact by artifact id or filename.

Why first:

- It turns artifacts into a real workspace for long conversations.
- Skills such as `writing-plans`, `research`, and `release-readiness` can build on it.

3. `artifact_update`

Replace or append to an existing artifact with an explicit update mode.

Why first:

- It enables iterative writing instead of creating many disconnected markdown files.
- It keeps the operation narrower and safer than arbitrary filesystem writes.

4. `web_fetch`

Fetch a user-provided URL and return title, final URL, text excerpt, and basic metadata.

Why first:

- `web_search` can find sources, but the agent also needs to read a specific source.
- This unlocks article summaries, doc review, and evidence gathering.
- Provider details stay behind the tool boundary.

5. `conversation_summary`

Return the latest saved rolling summary, task brief, branch metadata, active skills, and recent messages for the current or specified thread.

Why first:

- It directly reinforces Focus Agent's branch-aware product model.
- It helps users recover context in long-running conversations.
- It can feed artifacts, memory, or notes later.

6. `memory_save`

Save an explicit user-approved memory such as a preference, durable fact, or project context item.

7. `memory_search`

Search durable memories by query and optional namespace.

8. `memory_forget`

Remove or deactivate a memory item by id.

Why memory is in Batch 1A:

- The project already has memory models and namespace helpers.
- Explicit memory control is part of the minimum general-agent experience.
- These tools should still prefer explicit user intent such as "remember this" or skill-guided consent.

### Batch 1B: Notes and tasks

These should come after the artifact and memory primitives because they likely need new product storage models.

1. `notes_create`

Create a structured note with type, title, body, tags, and source thread.

2. `notes_search`

Search notes by query, tags, type, and date range.

3. `notes_update`

Update an existing note by id.

4. `tasks_create`

Create an actionable task with title, status, optional due date, and source thread.

5. `tasks_list`

List tasks by status, date range, or source thread.

6. `tasks_update`

Update task status, title, due date, or notes.

Why Batch 1B:

- Notes and tasks make the agent feel like a general assistant.
- They should be first-class product data, not hidden markdown conventions.
- They need explicit API, storage, and UI considerations.

## Skill Implications

After Batch 1A, builtin skills can become more product-oriented without adding workflow-specific tools.

Recommended builtin skill updates:

- `research`: use `web_search`, `web_fetch`, and artifacts for evidence-backed answers.
- `writing-plans`: use artifact list/read/update for iterative plans.
- `autopilot`: save durable deliverables as artifacts when appropriate.

Recommended new builtin skills after Batch 1C:

- `personal-assistant`: route user requests to memory, notes, tasks, or artifacts.
- `meeting-notes`: turn notes into action items using notes and tasks tools.
- `project-catchup`: summarize a conversation and save follow-up tasks or notes.

Recommended user-local skills:

- team-specific weekly report templates
- personal task triage conventions
- company-specific research source preferences
- connector-backed workflows such as calendar or email routines

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

## Recommended Next Step

Batch 1A is now the baseline. The next product-oriented step is Batch 1B: add first-class notes and tasks tools with explicit storage, API, tests, and UI affordances.

This keeps the expansion product-visible while preserving the rule that tools provide primitives and skills provide workflows.
