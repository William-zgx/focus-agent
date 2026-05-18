import { appendQueryValue } from "./query.js";
import type { FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentRoleDecisionListResponse,
  FocusAgentRoleDryRunRequest,
  FocusAgentRoleDryRunResponse,
  FocusAgentRolePolicyResponse,
  FocusAgentFeedbackTrendResponse,
  FocusAgentSkillCatalogResponse,
  FocusAgentSkillPreferenceRequest,
  FocusAgentSkillPreferenceResponse,
  FocusAgentSkillSelectionFeedbackRequest,
  FocusAgentSkillSelectionListResponse,
  FocusAgentSkillSelectRequest,
  FocusAgentSkillSelectionResponse,
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

async function selectAgentSkills(
  this: FocusAgentEndpointContext,
  request: FocusAgentSkillSelectRequest,
): Promise<FocusAgentSkillSelectionResponse> {
  return this.requestJson<FocusAgentSkillSelectionResponse>("/v1/agent/skills/select", {
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

async function listAgentSkillSelections(this: FocusAgentEndpointContext, limit = 50): Promise<FocusAgentSkillSelectionListResponse> {
  const params = new URLSearchParams();
  appendQueryValue(params, "limit", limit);
  const query = params.toString();
  return this.requestJson<FocusAgentSkillSelectionListResponse>(
    `/v1/agent/skills/selections${query ? `?${query}` : ""}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function sendAgentSkillSelectionFeedback(
  this: FocusAgentEndpointContext,
  selectionId: string,
  request: FocusAgentSkillSelectionFeedbackRequest,
): Promise<FocusAgentSkillSelectionListResponse> {
  return this.requestJson<FocusAgentSkillSelectionListResponse>(
    `/v1/agent/skills/selections/${encodeURIComponent(selectionId)}/feedback`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function getAgentSkillCatalog(this: FocusAgentEndpointContext): Promise<FocusAgentSkillCatalogResponse> {
  return this.requestJson<FocusAgentSkillCatalogResponse>("/v1/agent/skills/catalog", {
    method: "GET",
    headers: {},
  }, true);
}

async function updateAgentSkillPreference(
  this: FocusAgentEndpointContext,
  skillId: string,
  request: FocusAgentSkillPreferenceRequest,
): Promise<FocusAgentSkillPreferenceResponse> {
  return this.requestJson<FocusAgentSkillPreferenceResponse>(
    `/v1/agent/skills/${encodeURIComponent(skillId)}/preference`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function getAgentFeedbackTrend(this: FocusAgentEndpointContext): Promise<FocusAgentFeedbackTrendResponse> {
  return this.requestJson<FocusAgentFeedbackTrendResponse>("/v1/agent/feedback/trend", {
    method: "GET",
    headers: {},
  }, true);
}

export interface AgentGovernanceRoleEndpoints {
  getAgentRolePolicy: OmitThisParameter<typeof getAgentRolePolicy>;
  selectAgentSkills: OmitThisParameter<typeof selectAgentSkills>;
  dryRunAgentRoleRoute: OmitThisParameter<typeof dryRunAgentRoleRoute>;
  listAgentRoleDecisions: OmitThisParameter<typeof listAgentRoleDecisions>;
  listAgentSkillSelections: OmitThisParameter<typeof listAgentSkillSelections>;
  sendAgentSkillSelectionFeedback: OmitThisParameter<typeof sendAgentSkillSelectionFeedback>;
  getAgentSkillCatalog: OmitThisParameter<typeof getAgentSkillCatalog>;
  updateAgentSkillPreference: OmitThisParameter<typeof updateAgentSkillPreference>;
  getAgentFeedbackTrend: OmitThisParameter<typeof getAgentFeedbackTrend>;
}

export const agentGovernanceRoleEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceRoleEndpoints> = {
  getAgentRolePolicy,
  selectAgentSkills,
  dryRunAgentRoleRoute,
  listAgentRoleDecisions,
  listAgentSkillSelections,
  sendAgentSkillSelectionFeedback,
  getAgentSkillCatalog,
  updateAgentSkillPreference,
  getAgentFeedbackTrend,
};
