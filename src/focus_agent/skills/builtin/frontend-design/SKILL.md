---
name: frontend-design
description: Produce distinctive, intentional UI instead of generic AI template aesthetics. Use when building or reshaping web or product surfaces.
triggers: frontend-design:, ui-design:, design-ui:
when_to_use: Building new UI or pages, Reshaping an existing interface, Avoiding templated AI aesthetics, Need design direction for a product surface
recommended_tools: list_files, workspace_tree, search_code, read_file, apply_patch, write_text_artifact, artifact_read, artifact_update
prompt_mode: execute
---

# Frontend Design

Approach the work like a design lead at a small studio hired to give this product a visual identity that could not be mistaken for anyone else's. Make deliberate, opinionated choices about palette, typography, layout, and motion that fit *this* brief — not a generic template.

## Ground it in the subject

Before designing, pin down:

- concrete subject / product
- audience
- the page or surface's single job

If the repository already has design tokens, components, or brand notes, inspect them with `list_files`, `workspace_tree`, `search_code`, and `read_file` first and extend that system rather than inventing a parallel one.

## Design principles

- **Hero is a thesis.** Open with the most characteristic thing in the subject's world (headline, image, demo, interactive moment). Avoid default "big number + gradient accent" unless it truly fits.
- **Typography carries personality.** Pair display and body faces deliberately; set a clear type scale. Avoid the same generic font pairing you would use on any unrelated brief.
- **Structure is information.** Numbering, eyebrows, dividers, and labels should encode something true about the content, not decorate it.
- **Motion with intent.** Prefer one orchestrated moment over scattered micro-animations. Respect reduced motion when relevant.
- **Match complexity to the vision.** Maximalist directions need craft; minimal directions need precision.

## Anti-defaults (avoid unless the brief demands them)

AI-generated UI currently clusters around:

1. warm cream background + high-contrast serif + terracotta accent
2. near-black background + single acid-green or vermilion accent
3. broadsheet layout with hairline rules, zero radius, dense columns

These are legitimate for some briefs, but they are defaults. When the brief leaves an axis free, spend that freedom on a choice specific to the subject.

## Process

1. **Plan tokens first:** 4–6 named colors, 2+ type roles, layout concept (short prose + optional ASCII wireframe), and one signature element.
2. **Critique the plan:** if any part reads as the generic default you would produce for any similar page, revise it and say what changed.
3. **Build:** implement against the plan. Prefer existing project components and styles.
4. **Self-critique:** remove one decorative element that does not serve the brief; check responsive basics and focus visibility.
5. **Deliver:** if the design is a durable draft, save it with `write_text_artifact` and surface the artifact path/id clearly to the user.

## Copy is design material

- Write from the end user's side of the screen.
- Active voice; controls say what happens ("Save changes", not "Submit" for generic forms when a precise verb exists).
- Errors explain what went wrong and how to fix it.
- Empty states invite a next action.

## Rules

- Do not ship lookalike template aesthetics when the brief allows originality.
- Prefer surgical edits via `apply_patch` over rewriting unrelated files.
- Do not invent brand assets that contradict repository docs or existing design system tokens.
