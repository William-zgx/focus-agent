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
	const body = new ReadableStream<Uint8Array>({
		start(controller) {
			let index = 0;
			let timeout: ReturnType<typeof setTimeout> | null = null;

			const close = () => {
				if (timeout) {
					clearTimeout(timeout);
					timeout = null;
				}
			};
			const push = () => {
				if (signal?.aborted) {
					close();
					controller.error(
						signal.reason ?? new DOMException("Aborted", "AbortError"),
					);
					return;
				}
				const event = events[index];
				if (!event) {
					close();
					controller.close();
					return;
				}
				controller.enqueue(encoder.encode(sseFrame(event)));
				index += 1;
				timeout = setTimeout(push, 20);
			};

			signal?.addEventListener(
				"abort",
				() => {
					close();
					controller.error(
						signal.reason ?? new DOMException("Aborted", "AbortError"),
					);
				},
				{ once: true },
			);
			push();
		},
	});
	return new Response(body, { headers: SSE_HEADERS });
}
