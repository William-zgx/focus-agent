---
name: ultrawork
description: Break a larger task into parallel-style workstreams while still delivering one coherent result.
triggers: ulw:, ultrawork:
when_to_use: The task has independent subproblems, A larger effort needs structure without losing momentum
recommended_tools: list_files, search_code, git_status, git_diff
prompt_mode: execute
---
# Ultrawork

- Decompose the work into a few independent tracks before diving into details.
- Use `list_files` and `search_code` to map the codebase slices first, then assign each track to a concrete path, module, or concern so the workstreams stay disjoint.
- Solve the tracks in an order that reduces blockers quickly and keeps the answer easy to integrate.
- Check `git_status` before and after the work to keep scope visible, and use `git_diff` to summarize each completed track in concrete patch terms.
- Keep the write-up grouped by workstream or outcome rather than by every tiny step.
- If one track is blocked, keep advancing the non-blocked tracks so progress continues.
- Recombine the outputs into one coherent conclusion with clear status on what is done, partial, or blocked.
