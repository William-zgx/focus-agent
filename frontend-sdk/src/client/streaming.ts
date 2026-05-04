import { reduceStreamEvent, createInitialStreamState } from "../reducers";
import { applyEndpointMethods } from "./endpoint";
import type { EndpointClientConstructor, FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint";
import type {
  FocusAgentEvent,
  FocusAgentStreamHandlers,
  FocusAgentStreamState,
  FocusAgentTurnRequest,
  FocusAgentResumeRequest,
  FocusAgentToolEvent,
} from "../types";

async function streamTurn(
  this: FocusAgentEndpointContext,
  request: FocusAgentTurnRequest,
  options: { signal?: AbortSignal } = {},
): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
  return this.stream("/v1/chat/turns/stream", request, options);
}

async function streamResume(
  this: FocusAgentEndpointContext,
  request: FocusAgentResumeRequest,
  options: { signal?: AbortSignal } = {},
): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
  return this.stream("/v1/chat/resume/stream", request, options);
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

export interface StreamingEndpoints {
  streamTurn: OmitThisParameter<typeof streamTurn>;
  streamResume: OmitThisParameter<typeof streamResume>;
  collectStream: OmitThisParameter<typeof collectStream>;
}

const streamingEndpoints: FocusAgentEndpointMethodMap<StreamingEndpoints> = {
  streamTurn,
  streamResume,
  collectStream,
};

export function applyStreamingEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, streamingEndpoints);
}
