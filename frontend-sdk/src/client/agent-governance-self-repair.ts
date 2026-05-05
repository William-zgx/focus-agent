import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentSelfRepairFailureListResponse,
  FocusAgentSelfRepairPromotePreviewRequest,
  FocusAgentSelfRepairPromotePreviewResponse,
} from "../types.js";

async function listAgentSelfRepairFailures(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentSelfRepairFailureListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentSelfRepairFailureListResponse>(
    `/v1/agent/self-repair/failures${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function previewAgentSelfRepairPromotion(
  this: FocusAgentEndpointContext,
  request: FocusAgentSelfRepairPromotePreviewRequest,
): Promise<FocusAgentSelfRepairPromotePreviewResponse> {
  return this.requestJson<FocusAgentSelfRepairPromotePreviewResponse>("/v1/agent/self-repair/promote-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

export interface AgentGovernanceSelfRepairEndpoints {
  listAgentSelfRepairFailures: OmitThisParameter<typeof listAgentSelfRepairFailures>;
  previewAgentSelfRepairPromotion: OmitThisParameter<typeof previewAgentSelfRepairPromotion>;
}

export const agentGovernanceSelfRepairEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceSelfRepairEndpoints> = {
  listAgentSelfRepairFailures,
  previewAgentSelfRepairPromotion,
};
