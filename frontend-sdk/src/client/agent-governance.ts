import { applyEndpointMethods } from "./endpoint.js";
import {
  agentGovernanceArtifactEndpoints,
  type AgentGovernanceArtifactEndpoints,
} from "./agent-governance-artifacts.js";
import {
  agentGovernanceContextEndpoints,
  type AgentGovernanceContextEndpoints,
} from "./agent-governance-context.js";
import {
  agentGovernanceCriticEndpoints,
  type AgentGovernanceCriticEndpoints,
} from "./agent-governance-critic.js";
import {
  agentGovernanceDelegationEndpoints,
  type AgentGovernanceDelegationEndpoints,
} from "./agent-governance-delegation.js";
import {
  agentGovernanceMemoryEndpoints,
  type AgentGovernanceMemoryEndpoints,
} from "./agent-governance-memory.js";
import {
  agentGovernanceModelRouterEndpoints,
  type AgentGovernanceModelRouterEndpoints,
} from "./agent-governance-model-router.js";
import {
  agentGovernanceModelEndpoints,
  type AgentGovernanceModelEndpoints,
} from "./agent-governance-models.js";
import {
  agentGovernanceReviewEndpoints,
  type AgentGovernanceReviewEndpoints,
} from "./agent-governance-review.js";
import {
  agentGovernanceRoleEndpoints,
  type AgentGovernanceRoleEndpoints,
} from "./agent-governance-roles.js";
import {
  agentGovernanceSelfRepairEndpoints,
  type AgentGovernanceSelfRepairEndpoints,
} from "./agent-governance-self-repair.js";
import {
  agentGovernanceTaskLedgerEndpoints,
  type AgentGovernanceTaskLedgerEndpoints,
} from "./agent-governance-task-ledger.js";
import {
  agentGovernanceToolEndpoints,
  type AgentGovernanceToolEndpoints,
} from "./agent-governance-tools.js";
import type { EndpointClientConstructor, FocusAgentEndpointMethodMap } from "./endpoint.js";

export interface AgentGovernanceEndpoints
  extends AgentGovernanceModelEndpoints,
    AgentGovernanceRoleEndpoints,
    AgentGovernanceToolEndpoints,
    AgentGovernanceMemoryEndpoints,
    AgentGovernanceDelegationEndpoints,
    AgentGovernanceModelRouterEndpoints,
    AgentGovernanceSelfRepairEndpoints,
    AgentGovernanceReviewEndpoints,
    AgentGovernanceContextEndpoints,
    AgentGovernanceTaskLedgerEndpoints,
    AgentGovernanceArtifactEndpoints,
    AgentGovernanceCriticEndpoints {}

const agentGovernanceEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceEndpoints> = {
  ...agentGovernanceModelEndpoints,
  ...agentGovernanceRoleEndpoints,
  ...agentGovernanceToolEndpoints,
  ...agentGovernanceMemoryEndpoints,
  ...agentGovernanceDelegationEndpoints,
  ...agentGovernanceModelRouterEndpoints,
  ...agentGovernanceSelfRepairEndpoints,
  ...agentGovernanceReviewEndpoints,
  ...agentGovernanceContextEndpoints,
  ...agentGovernanceTaskLedgerEndpoints,
  ...agentGovernanceArtifactEndpoints,
  ...agentGovernanceCriticEndpoints,
};

export function applyAgentGovernanceEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, agentGovernanceEndpoints);
}
