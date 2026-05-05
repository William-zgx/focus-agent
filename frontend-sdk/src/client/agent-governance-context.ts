import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentContextArtifactListResponse,
  FocusAgentContextDecisionListResponse,
  FocusAgentContextPolicyResponse,
  FocusAgentContextPreviewRequest,
  FocusAgentContextPreviewResponse,
} from "../types.js";

async function getAgentContextPolicy(this: FocusAgentEndpointContext): Promise<FocusAgentContextPolicyResponse> {
  return this.requestJson<FocusAgentContextPolicyResponse>("/v1/agent/context/policy", {
    method: "GET",
    headers: {},
  }, true);
}

async function previewAgentContext(
  this: FocusAgentEndpointContext,
  request: FocusAgentContextPreviewRequest,
): Promise<FocusAgentContextPreviewResponse> {
  return this.requestJson<FocusAgentContextPreviewResponse>("/v1/agent/context/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function listAgentContextDecisions(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentContextDecisionListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentContextDecisionListResponse>(
    `/v1/agent/context/decisions${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function listAgentContextArtifacts(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentContextArtifactListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentContextArtifactListResponse>(
    `/v1/agent/context/artifacts${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

export interface AgentGovernanceContextEndpoints {
  getAgentContextPolicy: OmitThisParameter<typeof getAgentContextPolicy>;
  previewAgentContext: OmitThisParameter<typeof previewAgentContext>;
  listAgentContextDecisions: OmitThisParameter<typeof listAgentContextDecisions>;
  listAgentContextArtifacts: OmitThisParameter<typeof listAgentContextArtifacts>;
}

export const agentGovernanceContextEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceContextEndpoints> = {
  getAgentContextPolicy,
  previewAgentContext,
  listAgentContextDecisions,
  listAgentContextArtifacts,
};
