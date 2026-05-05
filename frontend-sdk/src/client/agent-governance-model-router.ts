import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentModelRouteRequest,
  FocusAgentModelRouteResponse,
  FocusAgentModelRouterDecisionListResponse,
  FocusAgentModelRouterPolicyResponse,
} from "../types.js";

async function getAgentModelRouterPolicy(this: FocusAgentEndpointContext): Promise<FocusAgentModelRouterPolicyResponse> {
  return this.requestJson<FocusAgentModelRouterPolicyResponse>("/v1/agent/model-router/policy", {
    method: "GET",
    headers: {},
  }, true);
}

async function routeAgentModel(this: FocusAgentEndpointContext, request: FocusAgentModelRouteRequest): Promise<FocusAgentModelRouteResponse> {
  return this.requestJson<FocusAgentModelRouteResponse>("/v1/agent/model-router/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function listAgentModelRouterDecisions(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentModelRouterDecisionListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentModelRouterDecisionListResponse>(
    `/v1/agent/model-router/decisions${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

export interface AgentGovernanceModelRouterEndpoints {
  getAgentModelRouterPolicy: OmitThisParameter<typeof getAgentModelRouterPolicy>;
  routeAgentModel: OmitThisParameter<typeof routeAgentModel>;
  listAgentModelRouterDecisions: OmitThisParameter<typeof listAgentModelRouterDecisions>;
}

export const agentGovernanceModelRouterEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceModelRouterEndpoints> = {
  getAgentModelRouterPolicy,
  routeAgentModel,
  listAgentModelRouterDecisions,
};
