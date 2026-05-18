import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentContextArtifactListResponse,
  FocusAgentContextDecisionListResponse,
  FocusAgentContextExplainRequest,
  FocusAgentContextExplainResponse,
  FocusAgentContextMemoryEvidenceListResponse,
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

async function listAgentContextEvidence(
  this: FocusAgentEndpointContext,
  request: { thread_id?: string | null; turn_id?: string | null; limit?: number } = {},
): Promise<FocusAgentContextMemoryEvidenceListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "thread_id", request.thread_id);
  appendQueryValue(params, "turn_id", request.turn_id);
  appendQueryValue(params, "limit", request.limit);
  const query = params.toString();
  return this.requestJson<FocusAgentContextMemoryEvidenceListResponse>(
    `/v1/agent/context/evidence${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function explainAgentContext(
  this: FocusAgentEndpointContext,
  request: FocusAgentContextExplainRequest,
): Promise<FocusAgentContextExplainResponse> {
  return this.requestJson<FocusAgentContextExplainResponse>("/v1/agent/context/explain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

export interface AgentGovernanceContextEndpoints {
  getAgentContextPolicy: OmitThisParameter<typeof getAgentContextPolicy>;
  previewAgentContext: OmitThisParameter<typeof previewAgentContext>;
  listAgentContextDecisions: OmitThisParameter<typeof listAgentContextDecisions>;
  listAgentContextArtifacts: OmitThisParameter<typeof listAgentContextArtifacts>;
  listAgentContextEvidence: OmitThisParameter<typeof listAgentContextEvidence>;
  explainAgentContext: OmitThisParameter<typeof explainAgentContext>;
}

export const agentGovernanceContextEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceContextEndpoints> = {
  getAgentContextPolicy,
  previewAgentContext,
  listAgentContextDecisions,
  listAgentContextArtifacts,
  listAgentContextEvidence,
  explainAgentContext,
};
