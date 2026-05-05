import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type { FocusAgentModelsResponse } from "../types.js";

async function listModels(this: FocusAgentEndpointContext): Promise<FocusAgentModelsResponse> {
  return this.requestJson<FocusAgentModelsResponse>("/v1/models", {
    method: "GET",
    headers: {},
  }, true);
}

export interface AgentGovernanceModelEndpoints {
  listModels: OmitThisParameter<typeof listModels>;
}

export const agentGovernanceModelEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceModelEndpoints> = {
  listModels,
};
