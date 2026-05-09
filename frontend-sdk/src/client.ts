import { FocusAgentTransport, iterValidatedSSEEvents } from "./transport.js";
import { applyAdminEndpoints, type AdminEndpoints } from "./client/admin.js";
import { applyAgentGovernanceEndpoints, type AgentGovernanceEndpoints } from "./client/agent-governance.js";
import { applyAgentTeamEndpoints, type AgentTeamEndpoints } from "./client/agent-team.js";
import { applyAuthEndpoints, type AuthEndpoints } from "./client/auth.js";
import { applyMemoryEndpoints, type MemoryEndpoints } from "./client/memory.js";
import { applyObservabilityEndpoints, type ObservabilityEndpoints } from "./client/observability.js";
import { canonicalizeStreamEvents } from "./client/stream.js";
import { applyStreamingEndpoints, type StreamingEndpoints } from "./client/streaming.js";
import { applyThreadBranchEndpoints, type ThreadBranchEndpoints } from "./client/thread-branch.js";
import type { FocusAgentStreamOptions } from "./client/endpoint.js";
import type { FocusAgentEvent } from "./types.js";

export interface FocusAgentClientOptions {
  baseUrl: string;
  token?: string;
  getToken?: () => string | null | Promise<string | null>;
  fetchImpl?: typeof fetch;
}

export { FocusAgentRequestError } from "./errors.js";
export type { FocusAgentStreamOptions } from "./client/endpoint.js";

export interface FocusAgentClient
  extends AuthEndpoints,
    AdminEndpoints,
    AgentGovernanceEndpoints,
    AgentTeamEndpoints,
    ThreadBranchEndpoints,
    MemoryEndpoints,
    ObservabilityEndpoints,
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
  ): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    const headers = new Headers({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    });
    if (options.lastEventId) {
      headers.set("Last-Event-ID", options.lastEventId);
    }
    const response = await this.transport.fetch({
      path,
      auth: true,
      init: {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: options.signal,
      },
    });
    if (!response.body) {
      throw new Error("FocusAgent stream response did not include a body.");
    }
    return canonicalizeStreamEvents(iterValidatedSSEEvents(response.body));
  }

  private async requestJson<T>(path: string, init: RequestInit, auth: boolean): Promise<T> {
    return this.transport.requestJson<T>({ path, init, auth });
  }

  private async buildHeaders(headers: HeadersInit, auth: boolean): Promise<HeadersInit> {
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

applyAuthEndpoints(FocusAgentClient);
applyAdminEndpoints(FocusAgentClient);
applyAgentGovernanceEndpoints(FocusAgentClient);
applyAgentTeamEndpoints(FocusAgentClient);
applyThreadBranchEndpoints(FocusAgentClient);
applyMemoryEndpoints(FocusAgentClient);
applyObservabilityEndpoints(FocusAgentClient);
applyStreamingEndpoints(FocusAgentClient);
