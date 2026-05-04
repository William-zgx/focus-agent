import { appendQueryValue } from "./query";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint";
import type {
  FocusAgentCapabilityListResponse,
  FocusAgentToolRouteDecisionListResponse,
  FocusAgentToolRouteRequest,
  FocusAgentToolRouteResponse,
} from "../types";

async function listAgentCapabilities(this: FocusAgentEndpointContext): Promise<FocusAgentCapabilityListResponse> {
  return this.requestJson<FocusAgentCapabilityListResponse>("/v1/agent/capabilities", {
    method: "GET",
    headers: {},
  }, true);
}

async function routeAgentTools(this: FocusAgentEndpointContext, request: FocusAgentToolRouteRequest): Promise<FocusAgentToolRouteResponse> {
  return this.requestJson<FocusAgentToolRouteResponse>("/v1/agent/tool-router/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function listAgentToolRouteDecisions(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentToolRouteDecisionListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentToolRouteDecisionListResponse>(
    `/v1/agent/tool-router/decisions${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

export interface AgentGovernanceToolEndpoints {
  listAgentCapabilities: OmitThisParameter<typeof listAgentCapabilities>;
  routeAgentTools: OmitThisParameter<typeof routeAgentTools>;
  listAgentToolRouteDecisions: OmitThisParameter<typeof listAgentToolRouteDecisions>;
}

export const agentGovernanceToolEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceToolEndpoints> = {
  listAgentCapabilities,
  routeAgentTools,
  listAgentToolRouteDecisions,
};
