import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentReviewQueueDecisionResponse,
  FocusAgentReviewQueueListResponse,
} from "../types.js";

async function listAgentReviewQueue(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentReviewQueueListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentReviewQueueListResponse>(
    `/v1/agent/review-queue${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function approveAgentReviewQueueItem(this: FocusAgentEndpointContext, itemId: string): Promise<FocusAgentReviewQueueDecisionResponse> {
  return this.requestJson<FocusAgentReviewQueueDecisionResponse>(
    `/v1/agent/review-queue/${encodeURIComponent(itemId)}/approve`,
    {
      method: "POST",
      headers: {},
    },
    true,
  );
}

async function rejectAgentReviewQueueItem(this: FocusAgentEndpointContext, itemId: string): Promise<FocusAgentReviewQueueDecisionResponse> {
  return this.requestJson<FocusAgentReviewQueueDecisionResponse>(
    `/v1/agent/review-queue/${encodeURIComponent(itemId)}/reject`,
    {
      method: "POST",
      headers: {},
    },
    true,
  );
}

export interface AgentGovernanceReviewEndpoints {
  listAgentReviewQueue: OmitThisParameter<typeof listAgentReviewQueue>;
  approveAgentReviewQueueItem: OmitThisParameter<typeof approveAgentReviewQueueItem>;
  rejectAgentReviewQueueItem: OmitThisParameter<typeof rejectAgentReviewQueueItem>;
}

export const agentGovernanceReviewEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceReviewEndpoints> = {
  listAgentReviewQueue,
  approveAgentReviewQueueItem,
  rejectAgentReviewQueueItem,
};
