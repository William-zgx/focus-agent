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
  agentGovernanceMemoryEndpoints,
  type AgentGovernanceMemoryEndpoints,
} from "./agent-governance-memory.js";
import {
  agentGovernanceModelEndpoints,
  type AgentGovernanceModelEndpoints,
} from "./agent-governance-models.js";
import {
  agentGovernanceRoleEndpoints,
  type AgentGovernanceRoleEndpoints,
} from "./agent-governance-roles.js";
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
    AgentGovernanceContextEndpoints,
    AgentGovernanceArtifactEndpoints {}

const agentGovernanceEndpoints: FocusAgentEndpointMethodMap<AgentGovernanceEndpoints> = {
  ...agentGovernanceModelEndpoints,
  ...agentGovernanceRoleEndpoints,
  ...agentGovernanceToolEndpoints,
  ...agentGovernanceMemoryEndpoints,
  ...agentGovernanceContextEndpoints,
  ...agentGovernanceArtifactEndpoints,
};

export function applyAgentGovernanceEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, agentGovernanceEndpoints);
}
