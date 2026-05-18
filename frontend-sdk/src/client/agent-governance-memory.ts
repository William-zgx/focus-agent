import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentMemoryCuratorDecisionListResponse,
  FocusAgentMemoryCuratorEvaluateRequest,
  FocusAgentMemoryCuratorEvaluateResponse,
  FocusAgentMemoryCuratorPolicyResponse,
  FocusAgentMemoryUsageResponse,
} from "../types.js";

async function getAgentMemoryCuratorPolicy(this: FocusAgentEndpointContext): Promise<FocusAgentMemoryCuratorPolicyResponse> {
  return this.requestJson<FocusAgentMemoryCuratorPolicyResponse>("/v1/agent/memory/curator/policy", {
    method: "GET",
    headers: {},
  }, true);
}

async function evaluateAgentMemoryCurator(
  this: FocusAgentEndpointContext,
  request: FocusAgentMemoryCuratorEvaluateRequest,
): Promise<FocusAgentMemoryCuratorEvaluateResponse> {
  return this.requestJson<FocusAgentMemoryCuratorEvaluateResponse>("/v1/agent/memory/curator/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function listAgentMemoryCuratorDecisions(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentMemoryCuratorDecisionListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentMemoryCuratorDecisionListResponse>(
    `/v1/agent/memory/curator/decisions${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function getMemoryUsage(
  this: FocusAgentEndpointContext,
  memoryId: string,
): Promise<FocusAgentMemoryUsageResponse> {
  return this.requestJson<FocusAgentMemoryUsageResponse>(
    `/v1/memory/${encodeURIComponent(memoryId)}/usage`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

export interface AgentGovernanceMemoryEndpoints {
  getAgentMemoryCuratorPolicy: OmitThisParameter<typeof getAgentMemoryCuratorPolicy>;
  evaluateAgentMemoryCurator: OmitThisParameter<typeof evaluateAgentMemoryCurator>;
  listAgentMemoryCuratorDecisions: OmitThisParameter<typeof listAgentMemoryCuratorDecisions>;
  getMemoryUsage: OmitThisParameter<typeof getMemoryUsage>;
}

export const agentGovernanceMemoryEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceMemoryEndpoints> = {
  getAgentMemoryCuratorPolicy,
  evaluateAgentMemoryCurator,
  listAgentMemoryCuratorDecisions,
  getMemoryUsage,
};
