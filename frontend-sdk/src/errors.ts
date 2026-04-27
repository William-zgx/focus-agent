export interface FocusAgentRequestErrorOptions {
  status: number;
  statusText: string;
  code?: string | number;
  message?: string;
  data?: unknown;
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
  readonly data?: unknown;
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
    this.data = options.data;
    this.request_id = options.request_id;
    this.raw = options.raw;
  }
}
