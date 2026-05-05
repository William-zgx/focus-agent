import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentDelegationPlanRequest,
  FocusAgentDelegationPlanResponse,
  FocusAgentDelegationPolicyResponse,
  FocusAgentDelegationRunListResponse,
} from "../types.js";

async function getAgentDelegationPolicy(this: FocusAgentEndpointContext): Promise<FocusAgentDelegationPolicyResponse> {
  return this.requestJson<FocusAgentDelegationPolicyResponse>("/v1/agent/delegation/policy", {
    method: "GET",
    headers: {},
  }, true);
}

async function planAgentDelegation(
  this: FocusAgentEndpointContext,
  request: FocusAgentDelegationPlanRequest,
): Promise<FocusAgentDelegationPlanResponse> {
  return this.requestJson<FocusAgentDelegationPlanResponse>("/v1/agent/delegation/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function listAgentDelegationRuns(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentDelegationRunListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentDelegationRunListResponse>(
    `/v1/agent/delegation/runs${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

export interface AgentGovernanceDelegationEndpoints {
  getAgentDelegationPolicy: OmitThisParameter<typeof getAgentDelegationPolicy>;
  planAgentDelegation: OmitThisParameter<typeof planAgentDelegation>;
  listAgentDelegationRuns: OmitThisParameter<typeof listAgentDelegationRuns>;
}

export const agentGovernanceDelegationEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceDelegationEndpoints> = {
  getAgentDelegationPolicy,
  planAgentDelegation,
  listAgentDelegationRuns,
};
