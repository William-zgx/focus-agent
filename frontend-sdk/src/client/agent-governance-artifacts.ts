import { appendQueryValue } from "./query";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint";
import type {
  FocusAgentArtifactListResponse,
  FocusAgentArtifactSynthesisRequest,
  FocusAgentArtifactSynthesisResponse,
} from "../types";

async function listAgentArtifacts(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentArtifactListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentArtifactListResponse>(
    `/v1/agent/artifacts${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function synthesizeAgentArtifacts(
  this: FocusAgentEndpointContext,
  request: FocusAgentArtifactSynthesisRequest,
): Promise<FocusAgentArtifactSynthesisResponse> {
  return this.requestJson<FocusAgentArtifactSynthesisResponse>("/v1/agent/artifacts/synthesize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

export interface AgentGovernanceArtifactEndpoints {
  listAgentArtifacts: OmitThisParameter<typeof listAgentArtifacts>;
  synthesizeAgentArtifacts: OmitThisParameter<typeof synthesizeAgentArtifacts>;
}

export const agentGovernanceArtifactEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceArtifactEndpoints> = {
  listAgentArtifacts,
  synthesizeAgentArtifacts,
};
