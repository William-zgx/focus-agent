import type { FocusAgentEvent } from "../types";

function canonicalizeAliasEvent(event: FocusAgentEvent): FocusAgentEvent {
  switch (event.event) {
    case "message.delta":
      return { ...event, event: "visible_text.delta" } as FocusAgentEvent<"visible_text.delta">;
    case "message.completed":
      return { ...event, event: "visible_text.completed" } as FocusAgentEvent<"visible_text.completed">;
    case "tool.call.delta":
      return { ...event, event: "tool_call.delta" } as FocusAgentEvent<"tool_call.delta">;
    default:
      return event;
  }
}

function aliasDeduplicationKey(event: FocusAgentEvent): string | null {
  switch (event.event) {
    case "visible_text.delta":
    case "visible_text.completed":
    case "tool_call.delta":
      return `${event.event}:${JSON.stringify(event.data)}`;
    default:
      return null;
  }
}

export async function* dedupeAndCanonicalizeAliasEvents(
  stream: AsyncIterable<FocusAgentEvent>,
): AsyncGenerator<FocusAgentEvent, void, unknown> {
  let buffered: FocusAgentEvent | null = null;

  for await (const rawEvent of stream) {
    const event = canonicalizeAliasEvent(rawEvent);
    if (!buffered) {
      buffered = event;
      continue;
    }

    const bufferedKey = aliasDeduplicationKey(buffered);
    const eventKey = aliasDeduplicationKey(event);
    if (bufferedKey && bufferedKey === eventKey) {
      continue;
    }

    yield buffered;
    buffered = event;
  }

  if (buffered) {
    yield buffered;
  }
}
