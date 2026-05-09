import type { FocusAgentEvent } from "../types.js";

export async function* canonicalizeStreamEvents(
  stream: AsyncIterable<FocusAgentEvent>,
): AsyncGenerator<FocusAgentEvent, void, unknown> {
  for await (const event of stream) {
    yield event;
  }
}
