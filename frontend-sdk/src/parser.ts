import type { FocusAgentEvent, FocusAgentEventName, FocusAgentEventPayload } from "./types";

export interface ParsedSSEFrame {
  event: string;
  data: string;
  raw: string;
}

export function parseSSEFrames(buffer: string): { frames: ParsedSSEFrame[]; remainder: string } {
  const chunks = buffer.split(/\n\n/);
  const remainder = chunks.pop() ?? "";
  const frames: ParsedSSEFrame[] = [];

  for (const rawChunk of chunks) {
    const lines = rawChunk.split(/\n/);
    let event = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    frames.push({ event, data: dataLines.join("\n"), raw: rawChunk });
  }

  return { frames, remainder };
}

export function decodeEvent(frame: ParsedSSEFrame): FocusAgentEvent {
  const payload = frame.data ? (JSON.parse(frame.data) as FocusAgentEventPayload) : ({} as FocusAgentEventPayload);
  return {
    event: frame.event as FocusAgentEventName,
    data: payload,
    raw: frame.raw,
  } as FocusAgentEvent;
}

export async function* iterSSEEvents(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<FocusAgentEvent, void, unknown> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSSEFrames(buffer);
      buffer = parsed.remainder;
      for (const frame of parsed.frames) {
        yield decodeEvent(frame);
      }
    }
    buffer += decoder.decode();
    const parsed = parseSSEFrames(buffer + "\n\n");
    for (const frame of parsed.frames) {
      yield decodeEvent(frame);
    }
  } finally {
    reader.releaseLock();
  }
}
