import type { FocusAgentEvent, FocusAgentEventName, FocusAgentEventPayload } from "./types.js";

export interface ParsedSSEFrame {
  event: string;
  data: string;
  id?: string;
  raw: string;
}

export class FocusAgentSSEDecodeError extends Error {
  readonly frame: ParsedSSEFrame;

  constructor(frame: ParsedSSEFrame, cause: unknown) {
    super(`Failed to decode SSE frame for event "${frame.event}".`, { cause });
    this.name = "FocusAgentSSEDecodeError";
    this.frame = frame;
  }
}

export function parseSSEFrames(buffer: string): { frames: ParsedSSEFrame[]; remainder: string } {
  const chunks = buffer.split(/\r?\n\r?\n/);
  const remainder = chunks.pop() ?? "";
  const frames: ParsedSSEFrame[] = [];

  for (const rawChunk of chunks) {
    if (!rawChunk.trim()) {
      continue;
    }
    const lines = rawChunk.split(/\r?\n/);
    let event = "message";
    let id: string | undefined;
    const dataLines: string[] = [];
    let hasEventLine = false;
    let hasDataLine = false;
    for (const line of lines) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
        hasEventLine = true;
      } else if (line.startsWith("id:")) {
        id = line.slice(3).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
        hasDataLine = true;
      }
    }
    if (!hasEventLine && !hasDataLine) {
      continue;
    }
    frames.push({ event, data: dataLines.join("\n"), id, raw: rawChunk });
  }

  return { frames, remainder };
}

export function decodeEvent(frame: ParsedSSEFrame): FocusAgentEvent {
  let payload: FocusAgentEventPayload;
  try {
    payload = frame.data ? (JSON.parse(frame.data) as FocusAgentEventPayload) : ({} as FocusAgentEventPayload);
  } catch (error) {
    throw new FocusAgentSSEDecodeError(frame, error);
  }
  return {
    event: frame.event as FocusAgentEventName,
    data: payload,
    id: frame.id,
    raw: frame.raw,
  } as FocusAgentEvent;
}

export async function* iterSSEEvents(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<FocusAgentEvent, void, unknown> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        completed = true;
        break;
      }
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
    if (!completed) {
      await reader.cancel().catch(() => undefined);
    }
    reader.releaseLock();
  }
}
