import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentRoleDecisionListResponse,
  FocusAgentRoleDryRunRequest,
  FocusAgentRoleDryRunResponse,
  FocusAgentRolePolicyResponse,
} from "../types.js";

async function getAgentRolePolicy(this: FocusAgentEndpointContext): Promise<FocusAgentRolePolicyResponse> {
  return this.requestJson<FocusAgentRolePolicyResponse>("/v1/agent/roles/policy", {
    method: "GET",
    headers: {},
  }, true);
}

async function dryRunAgentRoleRoute(
  this: FocusAgentEndpointContext,
  request: FocusAgentRoleDryRunRequest,
): Promise<FocusAgentRoleDryRunResponse> {
  return this.requestJson<FocusAgentRoleDryRunResponse>("/v1/agent/roles/dry-run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function listAgentRoleDecisions(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentRoleDecisionListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentRoleDecisionListResponse>(
    `/v1/agent/roles/decisions${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

export interface AgentGovernanceRoleEndpoints {
  getAgentRolePolicy: OmitThisParameter<typeof getAgentRolePolicy>;
  dryRunAgentRoleRoute: OmitThisParameter<typeof dryRunAgentRoleRoute>;
  listAgentRoleDecisions: OmitThisParameter<typeof listAgentRoleDecisions>;
}

export const agentGovernanceRoleEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceRoleEndpoints> = {
  getAgentRolePolicy,
  dryRunAgentRoleRoute,
  listAgentRoleDecisions,
};
