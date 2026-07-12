import type { FocusAgentEvent } from "@focus-agent/web-sdk";

import { SSE_HEADERS } from "./constants";

export function sseFrame(event: FocusAgentEvent): string {
	const idLine = event.id ? `id: ${event.id}\n` : "";
	return `${idLine}event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`;
}

export function sseResponse(
	events: FocusAgentEvent[],
	signal?: AbortSignal,
): Response {
	const encoder = new TextEncoder();
	let cleanup = () => {};
	let finished = false;
	const body = new ReadableStream<Uint8Array>({
		start(controller) {
			let index = 0;
			let timeout: ReturnType<typeof setTimeout> | null = null;

			const onAbort = () => {
				error(signal?.reason ?? new DOMException("Aborted", "AbortError"));
			};
			cleanup = () => {
				if (timeout !== null) {
					clearTimeout(timeout);
					timeout = null;
				}
				signal?.removeEventListener("abort", onAbort);
			};
			const finish = () => {
				if (finished) return false;
				finished = true;
				cleanup();
				return true;
			};
			const close = () => {
				if (!finish()) return;
				controller.close();
			};
			const error = (reason: unknown) => {
				if (!finish()) return;
				controller.error(reason);
			};
			const push = () => {
				timeout = null;
				if (finished) return;
				if (signal?.aborted) {
					error(signal.reason ?? new DOMException("Aborted", "AbortError"));
					return;
				}
				const event = events[index];
				if (!event) {
					close();
					return;
				}
				controller.enqueue(encoder.encode(sseFrame(event)));
				index += 1;
				timeout = setTimeout(push, 20);
			};

			signal?.addEventListener("abort", onAbort, { once: true });
			push();
		},
		cancel() {
			finished = true;
			cleanup();
		},
	});
	return new Response(body, { headers: SSE_HEADERS });
}
