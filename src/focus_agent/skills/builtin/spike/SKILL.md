---
name: spike
description: Run a throwaway experiment to validate feasibility, compare approaches, or expose unknowns before committing to a build.
triggers: spike:, prototype:, proof-of-concept:, explore-idea:
when_to_use: The user wants to test an idea before building, Feasibility is uncertain, Competing approaches need evidence, A quick prototype can answer what research cannot
recommended_tools: list_files, search_code, read_file, web_search, web_fetch, apply_patch, run_workspace_command, write_text_artifact, git_status, git_diff
capability_requirements: feasibility analysis, rapid prototyping, experimental validation, risk assessment
prompt_mode: execute
---
# Spike

A spike is disposable evidence. Use it to answer a feasibility question, not to start production implementation.

## Do Not Use When

- The answer is available from code inspection or documentation alone.
- The work is already validated and should move directly to implementation.
- The user needs production-quality architecture, tests, and rollout.

## Method

1. Decompose into 2-5 observable feasibility questions unless the user already named one exact spike.
2. Research just enough to choose the approach: primary docs, repo examples, dependency availability, maintenance, licensing, and operational constraints.
3. Build the smallest standalone experiment: CLI, minimal page, local endpoint, or focused test.
4. Verify more than the happy path, especially the edge case most likely to kill the idea.
5. Write the verdict before any production implementation begins.

Run the riskiest question first. If it invalidates the idea, stop and report that result.

## Verdict

```markdown
## Verdict: VALIDATED | PARTIAL | INVALIDATED

### What worked
- ...

### What did not
- ...

### Surprises
- ...

### Recommendation for the real build
- ...
```

`VALIDATED` means the core question is answered yes with evidence. `PARTIAL` means it works only under documented constraints. `INVALIDATED` means the idea should change or stop; that is still a successful spike.

## Comparison Spikes

When two approaches answer the same question, test them against the same sample inputs and compare correctness, setup cost, performance, and failure modes. Pick a winner only after both variants have comparable evidence.

## Output

- State the feasibility question.
- Show the smallest artifact or command that proves the result.
- Report the verdict and constraints.
- Keep throwaway code clearly separated from production code.
