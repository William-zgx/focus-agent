import { appendQueryValue } from "./query";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint";
import type {
  FocusAgentTaskLedgerPlanRequest,
  FocusAgentTaskLedgerPlanResponse,
  FocusAgentTaskLedgerPolicyResponse,
  FocusAgentTaskLedgerRunListResponse,
} from "../types";

async function getAgentTaskLedgerPolicy(this: FocusAgentEndpointContext): Promise<FocusAgentTaskLedgerPolicyResponse> {
  return this.requestJson<FocusAgentTaskLedgerPolicyResponse>("/v1/agent/task-ledger/policy", {
    method: "GET",
    headers: {},
  }, true);
}

async function planAgentTaskLedger(
  this: FocusAgentEndpointContext,
  request: FocusAgentTaskLedgerPlanRequest,
): Promise<FocusAgentTaskLedgerPlanResponse> {
  return this.requestJson<FocusAgentTaskLedgerPlanResponse>("/v1/agent/task-ledger/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function listAgentTaskLedgerRuns(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentTaskLedgerRunListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentTaskLedgerRunListResponse>(
    `/v1/agent/task-ledger/runs${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

export interface AgentGovernanceTaskLedgerEndpoints {
  getAgentTaskLedgerPolicy: OmitThisParameter<typeof getAgentTaskLedgerPolicy>;
  planAgentTaskLedger: OmitThisParameter<typeof planAgentTaskLedger>;
  listAgentTaskLedgerRuns: OmitThisParameter<typeof listAgentTaskLedgerRuns>;
}

export const agentGovernanceTaskLedgerEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceTaskLedgerEndpoints> = {
  getAgentTaskLedgerPolicy,
  planAgentTaskLedger,
  listAgentTaskLedgerRuns,
};
