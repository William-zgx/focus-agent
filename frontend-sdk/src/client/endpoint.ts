import type { FocusAgentEvent } from "../types.js";

export interface FocusAgentStreamOptions {
  signal?: AbortSignal;
  lastEventId?: string;
}

export interface FocusAgentStreamReconnectOptions {
  resumePathForRunId?: (runId: string) => string;
}

export interface FocusAgentEndpointContext {
  requestJson<T>(path: string, init: RequestInit, auth: boolean): Promise<T>;
  setToken(token: string | undefined): void;
  stream(
    path: string,
    body: unknown,
    options?: FocusAgentStreamOptions,
    reconnect?: FocusAgentStreamReconnectOptions,
  ): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>>;
}

export type EndpointClientConstructor = { prototype: object };

export type FocusAgentEndpointMethodMap<T> = {
  [K in keyof T]: T[K] extends (...args: infer Args) => infer Result
    ? (this: FocusAgentEndpointContext, ...args: Args) => Result
    : never;
};

export function applyEndpointMethods<T>(
  Client: EndpointClientConstructor,
  methods: FocusAgentEndpointMethodMap<T>,
): void {
  for (const [name, method] of Object.entries(methods)) {
    Object.defineProperty(Client.prototype, name, {
      value: method,
      writable: true,
      configurable: true,
    });
  }
}
