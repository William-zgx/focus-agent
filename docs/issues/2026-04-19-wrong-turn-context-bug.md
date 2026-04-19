# 2026-04-19 Wrong-Turn Context Bug

## Summary

The assistant answered the wrong request for the current turn.

User asked:

- "帮我写一篇300字左右描述小猫可爱的作文。直接发给我。"

Observed behavior:

- The system called unrelated tools such as `current_utc_time`, `web_search`, and `write_text_artifact`.
- The final answer was a weather comparison for Beijing and Shanghai instead of a short essay about a cat.

## Why This Is Wrong

- The request is a direct writing task and should usually not require search or artifact writing.
- The response content appears to come from an earlier weather-related turn.
- This suggests turn context, planning state, tool state, or assistant fallback content may be leaking across turns or threads.

## Suspected Areas

1. Frontend message send path:
   - confirm the current turn always sends the correct latest user message
   - confirm the current thread id is correct at send time

2. Streaming and optimistic UI state:
   - check whether stream state or fallback assistant text can survive into the next turn
   - check whether tool activity cards or pending assistant content are reused incorrectly

3. Backend planning and execution:
   - confirm planner input is built from the current turn only
   - confirm previous tool plan/results are not reused for a new turn

## Repro Snapshot

- Current request in screenshot: write a ~300-character/word cute cat essay and send directly in chat
- Actual tools shown: `current_utc_time`, then `web_search` + `write_text_artifact`
- Actual answer shown: weather comparison content

## Expected Behavior

- No weather-related tools should run
- No artifact should be written because the user explicitly asked for direct chat output
- The assistant should directly return a short cat essay in the chat
