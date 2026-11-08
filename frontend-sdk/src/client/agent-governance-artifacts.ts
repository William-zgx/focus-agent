import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type { FocusAgentArtifactListResponse } from "../types.js";

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

export interface AgentGovernanceArtifactEndpoints {
  listAgentArtifacts: OmitThisParameter<typeof listAgentArtifacts>;
}

export const agentGovernanceArtifactEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceArtifactEndpoints> = {
  listAgentArtifacts,
};
