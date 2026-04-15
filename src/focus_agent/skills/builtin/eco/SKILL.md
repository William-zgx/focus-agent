---
name: eco
description: Use the shortest grounded path with minimal prompt overhead and concise outputs.
triggers: eco:
when_to_use: The task is simple, The user wants a fast answer, Latency and prompt size matter more than exhaustive coverage
prompt_mode: execute
---
# Eco

- Prefer the cheapest valid path that still preserves correctness.
- Avoid long narration, redundant exploration, and unnecessary tool loops.
- Reuse available context before requesting or generating more.
- Return compact outputs that preserve the essential answer, decision, or artifact.
- If the task turns out to be deeper than expected, say so briefly and then expand only where needed.
