import { FocusAgentRequestError } from "./errors.js";
import { iterSSEEvents } from "./parser.js";
import type { FocusAgentEvent } from "./types.js";
import { validateFocusAgentEvent } from "./transport.validation.js";

export interface FocusAgentTransportOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  getHeaders?: (headers: HeadersInit, auth: boolean) => HeadersInit | Promise<HeadersInit>;
}

export interface FocusAgentTransportRequest {
  path: string;
  init: RequestInit;
  auth: boolean;
}

interface ErrorEnvelope {
  code?: string | number;
  stable_code?: string | number;
  message?: string;
  data?: unknown;
  details?: unknown;
  trace_id?: string | null;
  retryable?: boolean;
  request_id?: string | null;
}

interface ErrorDetailEnvelope {
  code?: string | number;
  stable_code?: string | number;
  message?: string;
  details?: unknown;
  trace_id?: string | null;
  retryable?: boolean;
}

const JSON_CONTENT_TYPE_PATTERN = /(^|[+\-/])json($|[;\s])/i;

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function normalizeNetworkError(error: unknown): never {
  if (isAbortError(error)) {
    throw error;
  }
  throw error;
}

function isJsonResponse(response: Response): boolean {
  const contentType = response.headers.get("content-type") ?? "";
  return JSON_CONTENT_TYPE_PATTERN.test(contentType);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringOrNumber(value: unknown): string | number | undefined {
  if (typeof value === "string" || typeof value === "number") return value;
  return undefined;
}

function stringOrNull(value: unknown): string | null | undefined {
  if (typeof value === "string" || value === null) return value;
  return undefined;
}

function booleanOrUndefined(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function parseErrorEnvelope(raw: unknown): ErrorEnvelope {
  if (!isRecord(raw)) return {};
  const detail = isRecord(raw.detail) ? (raw.detail as ErrorDetailEnvelope) : undefined;
  return {
    code: stringOrNumber(detail?.code) ?? stringOrNumber(raw.code),
    stable_code: stringOrNumber(detail?.stable_code) ?? stringOrNumber(raw.stable_code),
    message:
      typeof raw.message === "string"
        ? raw.message
        : typeof detail?.message === "string"
          ? detail.message
          : undefined,
    data: "detail" in raw ? raw.detail : "data" in raw ? raw.data : undefined,
    details: "details" in raw ? raw.details : detail?.details,
    trace_id: stringOrNull(detail?.trace_id) ?? stringOrNull(raw.trace_id),
    retryable: booleanOrUndefined(detail?.retryable) ?? booleanOrUndefined(raw.retryable),
    request_id: stringOrNull(raw.request_id),
  };
}

async function readTextSafely(response: Response): Promise<string> {
  try {
    return await response.text();
  } catch {
    return "";
  }
}

async function readJsonSafely(response: Response): Promise<{ parsed: true; value: unknown } | { parsed: false; rawText: string }> {
  const rawText = await readTextSafely(response);
  if (!rawText.trim()) {
    return { parsed: false, rawText };
  }
  try {
    return { parsed: true, value: JSON.parse(rawText) as unknown };
  } catch {
    return { parsed: false, rawText };
  }
}

export async function createFocusAgentRequestError(response: Response): Promise<FocusAgentRequestError> {
  if (isJsonResponse(response)) {
    const json = await readJsonSafely(response);
    if (json.parsed) {
      const envelope = parseErrorEnvelope(json.value);
      return new FocusAgentRequestError({
        status: response.status,
        statusText: response.statusText,
        code: envelope.code ?? response.status,
        stable_code: envelope.stable_code,
        message: envelope.message,
        data: envelope.data,
        details: envelope.details,
        trace_id: envelope.trace_id,
        retryable: envelope.retryable,
        request_id: envelope.request_id,
        raw: json.value,
      });
    }
    return new FocusAgentRequestError({
      status: response.status,
      statusText: response.statusText,
      code: response.status,
      data: json.rawText ? { body: json.rawText } : undefined,
      raw: json.rawText,
    });
  }

  const rawText = await readTextSafely(response);
  return new FocusAgentRequestError({
    status: response.status,
    statusText: response.statusText,
    code: response.status,
    data: rawText ? { body: rawText } : undefined,
    raw: rawText,
  });
}

export async function ensureOkResponse(response: Response): Promise<void> {
  if (response.ok) return;
  throw await createFocusAgentRequestError(response);
}

export class FocusAgentTransport {
  readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly getHeaders?: (headers: HeadersInit, auth: boolean) => HeadersInit | Promise<HeadersInit>;

  constructor(options: FocusAgentTransportOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.getHeaders = options.getHeaders;
  }

  async fetch(request: FocusAgentTransportRequest): Promise<Response> {
    const headers = this.getHeaders
      ? await this.getHeaders(request.init.headers ?? {}, request.auth)
      : request.init.headers;
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${request.path}`, {
        ...request.init,
        credentials: request.init.credentials ?? "include",
        headers,
      });
    } catch (error) {
      normalizeNetworkError(error);
    }
    await ensureOkResponse(response);
    return response;
  }

  async requestJson<T>(request: FocusAgentTransportRequest): Promise<T> {
    const response = await this.fetch(request);
    if (response.status === 204) {
      return undefined as T;
    }
    const rawText = await readTextSafely(response);
    if (!rawText.trim()) {
      return undefined as T;
    }
    return JSON.parse(rawText) as T;
  }
}

export class FocusAgentTransportValidationError extends Error {
  readonly rawEvent: unknown;

  constructor(message: string, rawEvent: unknown) {
    super(message);
    this.name = "FocusAgentTransportValidationError";
    this.rawEvent = rawEvent;
  }
}

export async function* validateTransportEvents(
  stream: AsyncIterable<FocusAgentEvent>,
): AsyncGenerator<FocusAgentEvent, void, unknown> {
  for await (const event of stream) {
    if (!validateFocusAgentEvent(event)) {
      throw new FocusAgentTransportValidationError(
        `Invalid FocusAgent transport event: ${String((event as { event?: unknown }).event ?? "unknown")}`,
        event,
      );
    }
    yield event;
  }
}

export function iterValidatedSSEEvents(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<FocusAgentEvent, void, unknown> {
  return validateTransportEvents(iterSSEEvents(stream));
}
