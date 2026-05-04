import { applyEndpointMethods } from "./endpoint";
import {
  agentGovernanceArtifactEndpoints,
  type AgentGovernanceArtifactEndpoints,
} from "./agent-governance-artifacts";
import {
  agentGovernanceContextEndpoints,
  type AgentGovernanceContextEndpoints,
} from "./agent-governance-context";
import {
  agentGovernanceCriticEndpoints,
  type AgentGovernanceCriticEndpoints,
} from "./agent-governance-critic";
import {
  agentGovernanceDelegationEndpoints,
  type AgentGovernanceDelegationEndpoints,
} from "./agent-governance-delegation";
import {
  agentGovernanceMemoryEndpoints,
  type AgentGovernanceMemoryEndpoints,
} from "./agent-governance-memory";
import {
  agentGovernanceModelRouterEndpoints,
  type AgentGovernanceModelRouterEndpoints,
} from "./agent-governance-model-router";
import {
  agentGovernanceModelEndpoints,
  type AgentGovernanceModelEndpoints,
} from "./agent-governance-models";
import {
  agentGovernanceReviewEndpoints,
  type AgentGovernanceReviewEndpoints,
} from "./agent-governance-review";
import {
  agentGovernanceRoleEndpoints,
  type AgentGovernanceRoleEndpoints,
} from "./agent-governance-roles";
import {
  agentGovernanceSelfRepairEndpoints,
  type AgentGovernanceSelfRepairEndpoints,
} from "./agent-governance-self-repair";
import {
  agentGovernanceTaskLedgerEndpoints,
  type AgentGovernanceTaskLedgerEndpoints,
} from "./agent-governance-task-ledger";
import {
  agentGovernanceToolEndpoints,
  type AgentGovernanceToolEndpoints,
} from "./agent-governance-tools";
import type { EndpointClientConstructor, FocusAgentEndpointMethodMap } from "./endpoint";

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
