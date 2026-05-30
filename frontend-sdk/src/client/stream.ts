import type { FocusAgentEvent } from "../types.js";

export async function* canonicalizeStreamEvents(
  stream: AsyncIterable<FocusAgentEvent>,
): AsyncGenerator<FocusAgentEvent, void, unknown> {
  const seenEventIds = new Set<string>();
  for await (const event of stream) {
    if (event.id) {
      if (seenEventIds.has(event.id)) {
        continue;
      }
      seenEventIds.add(event.id);
    }
    yield event;
  }
}
