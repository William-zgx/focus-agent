import { iterSSEEvents } from "./parser";
import { reduceStreamEvent, createInitialStreamState } from "./reducers";
import type {
  FocusAgentDemoTokenRequest,
  FocusAgentEvent,
  FocusAgentModelsResponse,
  FocusAgentPrincipalResponse,
  FocusAgentStreamHandlers,
  FocusAgentStreamState,
  FocusAgentTokenResponse,
  FocusAgentTurnRequest,
  FocusAgentResumeRequest,
  FocusAgentToolEvent,
} from "./types";

export interface FocusAgentClientOptions {
  baseUrl: string;
  token?: string;
  getToken?: () => string | null | Promise<string | null>;
  fetchImpl?: typeof fetch;
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
    this.fetchImpl = options.fetchImpl ?? fetch;
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

  async streamTurn(request: FocusAgentTurnRequest): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    return this.stream("/v1/chat/turns/stream", request);
  }

  async streamResume(request: FocusAgentResumeRequest): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    return this.stream("/v1/chat/resume/stream", request);
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

  private async stream(path: string, body: unknown): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: await this.buildHeaders({ "Content-Type": "application/json", Accept: "text/event-stream" }, true),
      body: JSON.stringify(body),
    });
    this.ensureOk(response);
    if (!response.body) {
      throw new Error("FocusAgent stream response did not include a body.");
    }
    return iterSSEEvents(response.body);
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
    throw new Error(`FocusAgent request failed: ${response.status} ${response.statusText}`);
  }
}
