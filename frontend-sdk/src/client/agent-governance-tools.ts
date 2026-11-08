import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentCapabilityListResponse,
  FocusAgentToolsetListResponse,
} from "../types.js";

async function listAgentCapabilities(this: FocusAgentEndpointContext): Promise<FocusAgentCapabilityListResponse> {
  return this.requestJson<FocusAgentCapabilityListResponse>("/v1/agent/capabilities", {
    method: "GET",
    headers: {},
  }, true);
}

async function listAgentToolsets(this: FocusAgentEndpointContext): Promise<FocusAgentToolsetListResponse> {
  return this.requestJson<FocusAgentToolsetListResponse>("/v1/agent/toolsets", {
    method: "GET",
    headers: {},
  }, true);
}

export interface AgentGovernanceToolEndpoints {
  listAgentCapabilities: OmitThisParameter<typeof listAgentCapabilities>;
  listAgentToolsets: OmitThisParameter<typeof listAgentToolsets>;
}

export const agentGovernanceToolEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceToolEndpoints> = {
  listAgentCapabilities,
  listAgentToolsets,
};
