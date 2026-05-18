export interface FocusAgentRequestErrorOptions {
  status: number;
  statusText: string;
  code?: string | number;
  stable_code?: string | number;
  message?: string;
  data?: unknown;
  details?: unknown;
  trace_id?: string | null;
  retryable?: boolean;
  request_id?: string | null;
  raw?: unknown;
}

function buildDefaultMessage(status: number, statusText: string): string {
  const suffix = statusText ? ` ${statusText}` : "";
  return `FocusAgent request failed: ${status}${suffix}`;
}

export class FocusAgentRequestError extends Error {
  readonly status: number;
  readonly statusText: string;
  readonly code?: string | number;
  readonly stable_code?: string | number;
  readonly data?: unknown;
  readonly details?: unknown;
  readonly trace_id?: string | null;
  readonly retryable: boolean;
  readonly request_id?: string | null;
  readonly raw?: unknown;

  constructor(status: number, statusText: string);
  constructor(options: FocusAgentRequestErrorOptions);
  constructor(statusOrOptions: number | FocusAgentRequestErrorOptions, statusText = "") {
    const options = typeof statusOrOptions === "number"
      ? { status: statusOrOptions, statusText }
      : statusOrOptions;
    super(options.message ?? buildDefaultMessage(options.status, options.statusText));
    this.name = "FocusAgentRequestError";
    this.status = options.status;
    this.statusText = options.statusText;
    this.code = options.code;
    this.stable_code = options.stable_code;
    this.data = options.data;
    this.details = options.details;
    this.trace_id = options.trace_id;
    this.retryable = options.retryable ?? false;
    this.request_id = options.request_id;
    this.raw = options.raw;
  }
}
