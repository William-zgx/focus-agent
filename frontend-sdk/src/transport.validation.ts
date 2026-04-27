import { FocusAgentRequestError } from "./errors.js";
import { FocusAgentTransport, createFocusAgentRequestError } from "./transport.js";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

async function testJsonEnvelopeError(): Promise<void> {
  const response = new Response(JSON.stringify({
    code: "invalid_request",
    message: "Invalid request.",
    data: { field: "thread_id" },
    request_id: "req-123",
  }), {
    status: 422,
    statusText: "Unprocessable Entity",
    headers: { "content-type": "application/json" },
  });

  const error = await createFocusAgentRequestError(response);
  assert(error instanceof FocusAgentRequestError, "expected FocusAgentRequestError");
  assert(error.status === 422, "expected status from response");
  assert(error.statusText === "Unprocessable Entity", "expected statusText from response");
  assert(error.code === "invalid_request", "expected code from envelope");
  assert(error.message === "Invalid request.", "expected message from envelope");
  assert(error.request_id === "req-123", "expected request_id from envelope");
  assert((error.data as { field: string }).field === "thread_id", "expected data from envelope");
  assert((error.raw as { request_id: string }).request_id === "req-123", "expected raw envelope fallback");
}

async function testNonJsonErrorFallback(): Promise<void> {
  const response = new Response("upstream unavailable", {
    status: 503,
    statusText: "Service Unavailable",
    headers: { "content-type": "text/plain" },
  });

  const error = await createFocusAgentRequestError(response);
  assert(error.status === 503, "expected non-JSON status");
  assert(error.code === 503, "expected status code fallback");
  assert(error.message === "FocusAgent request failed: 503 Service Unavailable", "expected default message fallback");
  assert((error.data as { body: string }).body === "upstream unavailable", "expected body data fallback");
  assert(error.raw === "upstream unavailable", "expected raw text fallback");
}

async function testEmptySuccessResponse(): Promise<void> {
  const transport = new FocusAgentTransport({
    baseUrl: "https://focus-agent.test/",
    fetchImpl: async () => new Response(null, { status: 204 }),
  });

  const value = await transport.requestJson<undefined>({
    path: "/empty",
    init: { method: "GET" },
    auth: false,
  });
  assert(value === undefined, "expected undefined for empty success response");
}

async function testAbortErrorPassesThrough(): Promise<void> {
  const abortError = new DOMException("The operation was aborted.", "AbortError");
  const transport = new FocusAgentTransport({
    baseUrl: "https://focus-agent.test",
    fetchImpl: async () => {
      throw abortError;
    },
  });

  try {
    await transport.requestJson<unknown>({
      path: "/abort",
      init: { method: "GET" },
      auth: false,
    });
  } catch (error) {
    assert(error === abortError, "expected original AbortError to pass through");
    assert(!(error instanceof FocusAgentRequestError), "expected abort not to be wrapped");
    return;
  }
  throw new Error("expected abort to throw");
}

async function main(): Promise<void> {
  await testJsonEnvelopeError();
  await testNonJsonErrorFallback();
  await testEmptySuccessResponse();
  await testAbortErrorPassesThrough();
}

void main();
