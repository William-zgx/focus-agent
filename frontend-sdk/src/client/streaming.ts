import { reduceStreamEvent, createInitialStreamState } from "../reducers.js";
import { applyEndpointMethods } from "./endpoint.js";
import type {
  EndpointClientConstructor,
  FocusAgentEndpointContext,
  FocusAgentEndpointMethodMap,
  FocusAgentStreamOptions,
} from "./endpoint.js";
import type {
  FocusAgentEvent,
  FocusAgentHarnessResumeRequest,
  FocusAgentHarnessRunCancelRequest,
  FocusAgentHarnessRunRequest,
  FocusAgentHarnessRunResponse,
  FocusAgentThreadHarnessRunsCancelResponse,
  FocusAgentStreamHandlers,
  FocusAgentStreamState,
  FocusAgentTurnRequest,
  FocusAgentResumeRequest,
  FocusAgentToolEvent,
} from "../types.js";

async function streamTurn(
  this: FocusAgentEndpointContext,
  request: FocusAgentTurnRequest,
  options: FocusAgentStreamOptions = {},
): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
  return streamHarnessRun.call(
    this,
    request.thread_id,
    {
      message: request.message,
      model: request.model,
      thinking_mode: request.thinking_mode,
      skill_hints: request.skill_hints,
    },
    options,
  );
}

async function streamResume(
  this: FocusAgentEndpointContext,
  request: FocusAgentResumeRequest,
  options: FocusAgentStreamOptions = {},
): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
  const harnessRequest: FocusAgentHarnessResumeRequest = {
    resume: request.resume,
    metadata: request.metadata,
    on_disconnect: request.on_disconnect,
    multitask_strategy: request.multitask_strategy,
  };
  return this.stream(
    `/v2/threads/${encodeURIComponent(request.thread_id)}/runs/resume/stream`,
    harnessRequest,
    options,
    {
      resumePathForRunId: (runId) => `/v2/runs/${encodeURIComponent(runId)}/stream`,
    },
  );
}

async function streamHarnessRun(
  this: FocusAgentEndpointContext,
  threadId: string,
  request: FocusAgentHarnessRunRequest,
  options: FocusAgentStreamOptions = {},
): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
  return this.stream(
    `/v2/threads/${encodeURIComponent(threadId)}/runs/stream`,
    request,
    options,
    {
      resumePathForRunId: (runId) => `/v2/runs/${encodeURIComponent(runId)}/stream`,
    },
  );
}

async function streamHarnessRunEvents(
  this: FocusAgentEndpointContext,
  runId: string,
  options: FocusAgentStreamOptions = {},
): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
  const initialResumePath = `/v2/runs/${encodeURIComponent(runId)}/stream`;
  return this.stream(
    initialResumePath,
    {},
    options,
    {
      initialRunId: runId,
      initialResumePath,
    },
  );
}

async function cancelHarnessRun(
  this: FocusAgentEndpointContext,
  runId: string,
  request: FocusAgentHarnessRunCancelRequest = {},
): Promise<FocusAgentHarnessRunResponse> {
  return this.requestJson<FocusAgentHarnessRunResponse>(
    `/v2/runs/${encodeURIComponent(runId)}/cancel`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function cancelThreadHarnessRuns(
  this: FocusAgentEndpointContext,
  threadId: string,
  request: FocusAgentHarnessRunCancelRequest = {},
): Promise<FocusAgentThreadHarnessRunsCancelResponse> {
  return this.requestJson<FocusAgentThreadHarnessRunsCancelResponse>(
    `/v2/threads/${encodeURIComponent(threadId)}/runs/cancel`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function collectStream(
  this: FocusAgentEndpointContext,
  stream: AsyncIterable<FocusAgentEvent>,
  handlers: FocusAgentStreamHandlers = {},
): Promise<FocusAgentStreamState> {
  let state = createInitialStreamState();
  for await (const event of stream) {
    state = reduceStreamEvent(state, event);
    handlers.onEvent?.(event);
    switch (event.event) {
      case "message.delta":
        handlers.onMessageDelta?.(event as FocusAgentEvent<"message.delta">);
        break;
      case "reasoning.delta":
        handlers.onReasoningDelta?.(event);
        break;
      case "tool.call.delta":
        handlers.onToolCallDelta?.(event as FocusAgentEvent<"tool.call.delta">);
        break;
      case "tool.requested":
      case "tool.error":
      case "tool.result":
        handlers.onToolEvent?.(event as FocusAgentToolEvent);
        break;
      case "run.completed":
        handlers.onCompleted?.(event);
        break;
      case "run.failed":
        handlers.onFailed?.(event);
        break;
      default:
        break;
    }
  }
  return state;
}

export interface StreamingEndpoints {
  streamTurn: OmitThisParameter<typeof streamTurn>;
  streamResume: OmitThisParameter<typeof streamResume>;
  streamHarnessRun: OmitThisParameter<typeof streamHarnessRun>;
  streamHarnessRunEvents: OmitThisParameter<typeof streamHarnessRunEvents>;
  cancelHarnessRun: OmitThisParameter<typeof cancelHarnessRun>;
  cancelThreadHarnessRuns: OmitThisParameter<typeof cancelThreadHarnessRuns>;
  collectStream: OmitThisParameter<typeof collectStream>;
}

const streamingEndpoints: FocusAgentEndpointMethodMap<StreamingEndpoints> = {
  streamTurn,
  streamResume,
  streamHarnessRun,
  streamHarnessRunEvents,
  cancelHarnessRun,
  cancelThreadHarnessRuns,
  collectStream,
};

export function applyStreamingEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, streamingEndpoints);
}
