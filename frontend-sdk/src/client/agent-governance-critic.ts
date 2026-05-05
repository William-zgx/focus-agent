import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentCriticEvaluateRequest,
  FocusAgentCriticEvaluateResponse,
  FocusAgentCriticVerdictListResponse,
} from "../types.js";

async function listAgentCriticVerdicts(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentCriticVerdictListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentCriticVerdictListResponse>(
    `/v1/agent/critic/verdicts${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function evaluateAgentCriticGate(
  this: FocusAgentEndpointContext,
  request: FocusAgentCriticEvaluateRequest,
): Promise<FocusAgentCriticEvaluateResponse> {
  return this.requestJson<FocusAgentCriticEvaluateResponse>("/v1/agent/critic/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

export interface AgentGovernanceCriticEndpoints {
  listAgentCriticVerdicts: OmitThisParameter<typeof listAgentCriticVerdicts>;
  evaluateAgentCriticGate: OmitThisParameter<typeof evaluateAgentCriticGate>;
}

export const agentGovernanceCriticEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceCriticEndpoints> = {
  listAgentCriticVerdicts,
  evaluateAgentCriticGate,
};
