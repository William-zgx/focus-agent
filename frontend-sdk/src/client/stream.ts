import type { FocusAgentEvent } from "../types.js";

export async function* canonicalizeStreamEvents(
	stream: AsyncIterable<FocusAgentEvent>,
	seenEventIds: Set<string> = new Set<string>(),
): AsyncGenerator<FocusAgentEvent, void, unknown> {
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
