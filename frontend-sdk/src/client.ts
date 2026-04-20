import { iterSSEEvents } from "./parser";
import { reduceStreamEvent, createInitialStreamState } from "./reducers";
import type {
  FocusAgentApplyMergeDecisionRequest,
  FocusAgentApplyMergeDecisionResponse,
  FocusAgentBranchRecord,
  FocusAgentConversationListResponse,
  FocusAgentConversationSummary,
  FocusAgentCreateConversationRequest,
  FocusAgentDemoTokenRequest,
  FocusAgentEvent,
  FocusAgentForkBranchRequest,
  FocusAgentModelsResponse,
  FocusAgentPrincipalResponse,
  FocusAgentRenameBranchRequest,
  FocusAgentUpdateConversationRequest,
  FocusAgentStreamHandlers,
  FocusAgentStreamState,
  FocusAgentTokenResponse,
  FocusAgentTurnRequest,
  FocusAgentResumeRequest,
  BranchTreeResponse,
  ThreadStateResponse,
  FocusAgentToolEvent,
} from "./types";

export interface FocusAgentClientOptions {
  baseUrl: string;
  token?: string;
  getToken?: () => string | null | Promise<string | null>;
  fetchImpl?: typeof fetch;
}

export class FocusAgentRequestError extends Error {
  readonly status: number;
  readonly statusText: string;

  constructor(status: number, statusText: string) {
    super(`FocusAgent request failed: ${status} ${statusText}`);
    this.name = "FocusAgentRequestError";
    this.status = status;
    this.statusText = statusText;
  }
}

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

async function* dedupeAndCanonicalizeAliasEvents(
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

export class FocusAgentClient {
  readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private token?: string;
  private readonly getTokenFn?: () => string | null | Promise<string | null>;

  constructor(options: FocusAgentClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.token = options.token;
    this.getTokenFn = options.getToken;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  setToken(token: string | undefined): void {
    this.token = token;
  }

  async createDemoToken(request: FocusAgentDemoTokenRequest = {}): Promise<FocusAgentTokenResponse> {
    return this.requestJson<FocusAgentTokenResponse>("/v1/auth/demo-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, false);
  }

  async getPrincipal(): Promise<FocusAgentPrincipalResponse> {
    return this.requestJson<FocusAgentPrincipalResponse>("/v1/auth/me", {
      method: "GET",
      headers: {},
    }, true);
  }

  async listModels(): Promise<FocusAgentModelsResponse> {
    return this.requestJson<FocusAgentModelsResponse>("/v1/models", {
      method: "GET",
      headers: {},
    }, true);
  }

  async listConversations(): Promise<FocusAgentConversationListResponse> {
    return this.requestJson<FocusAgentConversationListResponse>("/v1/conversations", {
      method: "GET",
      headers: {},
    }, true);
  }

  async createConversation(
    request: FocusAgentCreateConversationRequest = {},
  ): Promise<FocusAgentConversationSummary> {
    return this.requestJson<FocusAgentConversationSummary>("/v1/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async renameConversation(
    rootThreadId: string,
    request: FocusAgentUpdateConversationRequest,
  ): Promise<FocusAgentConversationSummary> {
    return this.requestJson<FocusAgentConversationSummary>(
      `/v1/conversations/${encodeURIComponent(rootThreadId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async archiveConversation(rootThreadId: string): Promise<FocusAgentConversationSummary> {
    return this.requestJson<FocusAgentConversationSummary>(
      `/v1/conversations/${encodeURIComponent(rootThreadId)}/archive`,
      {
        method: "POST",
        headers: {},
      },
      true,
    );
  }

  async activateConversation(rootThreadId: string): Promise<FocusAgentConversationSummary> {
    return this.requestJson<FocusAgentConversationSummary>(
      `/v1/conversations/${encodeURIComponent(rootThreadId)}/activate`,
      {
        method: "POST",
        headers: {},
      },
      true,
    );
  }

  async getThreadState(threadId: string): Promise<ThreadStateResponse> {
    return this.requestJson<ThreadStateResponse>(`/v1/threads/${encodeURIComponent(threadId)}`, {
      method: "GET",
      headers: {},
    }, true);
  }

  async getBranchTree(rootThreadId: string): Promise<BranchTreeResponse> {
    return this.requestJson<BranchTreeResponse>(`/v1/branches/tree/${encodeURIComponent(rootThreadId)}`, {
      method: "GET",
      headers: {},
    }, true);
  }

  async forkBranch(request: FocusAgentForkBranchRequest): Promise<FocusAgentBranchRecord> {
    return this.requestJson<FocusAgentBranchRecord>("/v1/branches/fork", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async archiveBranch(threadId: string): Promise<FocusAgentBranchRecord> {
    return this.requestJson<FocusAgentBranchRecord>(`/v1/branches/${encodeURIComponent(threadId)}/archive`, {
      method: "POST",
      headers: {},
    }, true);
  }

  async activateBranch(threadId: string): Promise<FocusAgentBranchRecord> {
    return this.requestJson<FocusAgentBranchRecord>(`/v1/branches/${encodeURIComponent(threadId)}/activate`, {
      method: "POST",
      headers: {},
    }, true);
  }

  async renameBranch(threadId: string, request: FocusAgentRenameBranchRequest): Promise<FocusAgentBranchRecord> {
    return this.requestJson<FocusAgentBranchRecord>(`/v1/branches/${encodeURIComponent(threadId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async prepareMergeProposal(threadId: string): Promise<ThreadStateResponse["merge_proposal"]> {
    return this.requestJson<ThreadStateResponse["merge_proposal"]>(
      `/v1/branches/${encodeURIComponent(threadId)}/proposal`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
      true,
    );
  }

  async applyMergeDecision(
    threadId: string,
    request: FocusAgentApplyMergeDecisionRequest,
  ): Promise<FocusAgentApplyMergeDecisionResponse> {
    return this.requestJson<FocusAgentApplyMergeDecisionResponse>(
      `/v1/branches/${encodeURIComponent(threadId)}/merge`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async sendTurn(request: FocusAgentTurnRequest): Promise<ThreadStateResponse> {
    return this.requestJson<ThreadStateResponse>(
      "/v1/chat/turns",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async streamTurn(
    request: FocusAgentTurnRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    return this.stream("/v1/chat/turns/stream", request, options);
  }

  async streamResume(
    request: FocusAgentResumeRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    return this.stream("/v1/chat/resume/stream", request, options);
  }

  async collectStream(
    stream: AsyncIterable<FocusAgentEvent>,
    handlers: FocusAgentStreamHandlers = {},
  ): Promise<FocusAgentStreamState> {
    let state = createInitialStreamState();
    for await (const event of stream) {
      state = reduceStreamEvent(state, event);
      handlers.onEvent?.(event);
      switch (event.event) {
        case "visible_text.delta":
        case "message.delta":
          handlers.onVisibleTextDelta?.(event as FocusAgentEvent<"visible_text.delta">);
          break;
        case "reasoning.delta":
          handlers.onReasoningDelta?.(event);
          break;
        case "tool_call.delta":
        case "tool.call.delta":
          handlers.onToolCallDelta?.(event as FocusAgentEvent<"tool_call.delta">);
          break;
        case "tool.requested":
        case "tool.start":
        case "tool.delta":
        case "tool.end":
        case "tool.error":
        case "tool.result":
          handlers.onToolEvent?.(event as FocusAgentToolEvent);
          break;
        case "turn.completed":
          handlers.onCompleted?.(event);
          break;
        case "turn.failed":
          handlers.onFailed?.(event);
          break;
        default:
          break;
      }
    }
    return state;
  }

  private async stream(
    path: string,
    body: unknown,
    options: { signal?: AbortSignal } = {},
  ): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: await this.buildHeaders({ "Content-Type": "application/json", Accept: "text/event-stream" }, true),
      body: JSON.stringify(body),
      signal: options.signal,
    });
    this.ensureOk(response);
    if (!response.body) {
      throw new Error("FocusAgent stream response did not include a body.");
    }
    return dedupeAndCanonicalizeAliasEvents(iterSSEEvents(response.body));
  }

  private async requestJson<T>(path: string, init: RequestInit, auth: boolean): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers: await this.buildHeaders(init.headers ?? {}, auth),
    });
    this.ensureOk(response);
    return (await response.json()) as T;
  }

  private async buildHeaders(headers: HeadersInit, auth: boolean): Promise<HeadersInit> {
    const next = new Headers(headers);
    if (auth) {
      const token = await this.resolveToken();
      if (token) next.set("Authorization", `Bearer ${token}`);
    }
    return next;
  }

  private async resolveToken(): Promise<string | null> {
    if (this.token) return this.token;
    if (this.getTokenFn) return (await this.getTokenFn()) ?? null;
    return null;
  }

  private ensureOk(response: Response): void {
    if (response.ok) return;
    throw new FocusAgentRequestError(response.status, response.statusText);
  }
}
