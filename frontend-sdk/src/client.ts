import { FocusAgentTransport, iterValidatedSSEEvents } from "./transport.js";
import { applyAdminEndpoints, type AdminEndpoints } from "./client/admin.js";
import {
	applyAgentGovernanceEndpoints,
	type AgentGovernanceEndpoints,
} from "./client/agent-governance.js";
import {
	applyAgentTeamEndpoints,
	type AgentTeamEndpoints,
} from "./client/agent-team.js";
import { applyAuthEndpoints, type AuthEndpoints } from "./client/auth.js";
import {
	applyBranchDecisionEndpoints,
	type BranchDecisionEndpoints,
} from "./client/branch-decisions.js";
import { applyMemoryEndpoints, type MemoryEndpoints } from "./client/memory.js";
import {
	applyObservabilityEndpoints,
	type ObservabilityEndpoints,
} from "./client/observability.js";
import {
	applyProductivityEndpoints,
	type ProductivityEndpoints,
} from "./client/productivity.js";
import { canonicalizeStreamEvents } from "./client/stream.js";
import {
	applyStreamingEndpoints,
	type StreamingEndpoints,
} from "./client/streaming.js";
import {
	applyThreadBranchEndpoints,
	type ThreadBranchEndpoints,
} from "./client/thread-branch.js";
import type {
	FocusAgentStreamOptions,
	FocusAgentStreamReconnectOptions,
} from "./client/endpoint.js";
import { isTerminalEvent } from "./guards.js";
import type { FocusAgentEvent } from "./types.js";

export interface FocusAgentClientOptions {
	baseUrl: string;
	token?: string;
	getToken?: () => string | null | Promise<string | null>;
	fetchImpl?: typeof fetch;
}

export { FocusAgentRequestError } from "./errors.js";
export type { FocusAgentStreamOptions } from "./client/endpoint.js";

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
	return new Promise((resolve, reject) => {
		if (signal?.aborted) {
			reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
			return;
		}
		const timeout = setTimeout(resolve, ms);
		signal?.addEventListener(
			"abort",
			() => {
				clearTimeout(timeout);
				reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
			},
			{ once: true },
		);
	});
}

export interface FocusAgentClient
	extends AuthEndpoints,
		AdminEndpoints,
		AgentGovernanceEndpoints,
		AgentTeamEndpoints,
		BranchDecisionEndpoints,
		ThreadBranchEndpoints,
		MemoryEndpoints,
		ObservabilityEndpoints,
		ProductivityEndpoints,
		StreamingEndpoints {}

export class FocusAgentClient {
	readonly baseUrl: string;
	private readonly transport: FocusAgentTransport;
	private token?: string;
	private readonly getTokenFn?: () => string | null | Promise<string | null>;

	constructor(options: FocusAgentClientOptions) {
		this.baseUrl = options.baseUrl.replace(/\/$/, "");
		this.token = options.token;
		this.getTokenFn = options.getToken;
		this.transport = new FocusAgentTransport({
			baseUrl: this.baseUrl,
			fetchImpl: options.fetchImpl,
			getHeaders: (headers, auth) => this.buildHeaders(headers, auth),
		});
	}

	setToken(token: string | undefined): void {
		this.token = token;
	}

	private async stream(
		path: string,
		body: unknown,
		options: FocusAgentStreamOptions = {},
		reconnect: FocusAgentStreamReconnectOptions = {},
	): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
		const headers = new Headers({
			"Content-Type": "application/json",
			Accept: "text/event-stream",
		});
		if (options.lastEventId) {
			headers.set("Last-Event-ID", options.lastEventId);
		}
		return this.reconnectingStream(path, body, headers, options, reconnect);
	}

	private async *reconnectingStream(
		path: string,
		body: unknown,
		baseHeaders: Headers,
		options: FocusAgentStreamOptions,
		reconnect: FocusAgentStreamReconnectOptions,
	): AsyncGenerator<FocusAgentEvent, void, unknown> {
		let lastEventId = options.lastEventId ?? null;
		let attempt = 0;
		let resumePath: string | null = null;
		while (!options.signal?.aborted) {
			const headers = new Headers(baseHeaders);
			if (lastEventId) {
				headers.set("Last-Event-ID", lastEventId);
			}
			const requestPath = resumePath ?? path;
			const requestBody = resumePath ? {} : body;
			try {
				let shouldReconnect = false;
				const response = await this.transport.fetch({
					path: requestPath,
					auth: true,
					init: {
						method: "POST",
						headers,
						body: JSON.stringify(requestBody),
						signal: options.signal,
					},
				});
				if (!response.body) {
					throw new Error("FocusAgent stream response did not include a body.");
				}
				for await (const event of canonicalizeStreamEvents(
					iterValidatedSSEEvents(response.body),
				)) {
					if (event.id) {
						lastEventId = event.id;
					}
					const runId = streamEventRunId(event);
					if (runId && reconnect.resumePathForRunId) {
						resumePath = reconnect.resumePathForRunId(runId);
					}
					attempt = 0;
					yield event;
					if (event.event === "server_shutdown") {
						shouldReconnect = true;
						break;
					}
					if (isTerminalEvent(event)) {
						return;
					}
				}
				if (options.signal?.aborted) return;
				if (shouldReconnect) {
					attempt += 1;
					const delay = Math.min(1000 * 2 ** Math.min(attempt - 1, 4), 15000);
					await sleep(delay, options.signal);
					continue;
				}
				return;
			} catch (error) {
				if (options.signal?.aborted) return;
				if (!resumePath) {
					throw error;
				}
				attempt += 1;
				const delay = Math.min(1000 * 2 ** Math.min(attempt - 1, 4), 15000);
				await sleep(delay, options.signal);
			}
		}
	}

	private async requestJson<T>(
		path: string,
		init: RequestInit,
		auth: boolean,
	): Promise<T> {
		return this.transport.requestJson<T>({ path, init, auth });
	}

	private async buildHeaders(
		headers: HeadersInit,
		auth: boolean,
	): Promise<HeadersInit> {
		const next = new Headers(headers);
		if (auth) {
			const token = await this.resolveToken();
			if (token) next.set("Authorization", "Bearer " + token);
		}
		return next;
	}

	private async resolveToken(): Promise<string | null> {
		if (this.token) return this.token;
		if (this.getTokenFn) return (await this.getTokenFn()) ?? null;
		return null;
	}
}

function streamEventRunId(event: FocusAgentEvent): string | null {
	const directRunId = event.data.run_id;
	if (typeof directRunId === "string" && directRunId.length > 0) {
		return directRunId;
	}
	const metadataRunId = event.data.metadata?.run_id;
	return typeof metadataRunId === "string" && metadataRunId.length > 0
		? metadataRunId
		: null;
}

applyAuthEndpoints(FocusAgentClient);
applyAdminEndpoints(FocusAgentClient);
applyAgentGovernanceEndpoints(FocusAgentClient);
applyAgentTeamEndpoints(FocusAgentClient);
applyBranchDecisionEndpoints(FocusAgentClient);
applyThreadBranchEndpoints(FocusAgentClient);
applyMemoryEndpoints(FocusAgentClient);
applyObservabilityEndpoints(FocusAgentClient);
applyProductivityEndpoints(FocusAgentClient);
applyStreamingEndpoints(FocusAgentClient);
