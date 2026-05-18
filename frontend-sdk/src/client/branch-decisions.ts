import { applyEndpointMethods } from "./endpoint.js";
import type {
	EndpointClientConstructor,
	FocusAgentEndpointContext,
	FocusAgentEndpointMethodMap,
} from "./endpoint.js";
import type {
	FocusAgentBranchDecisionConfig,
	FocusAgentBranchDecisionDismissRequest,
	FocusAgentBranchDecisionEvent,
	FocusAgentBranchDecisionListResponse,
} from "../types.js";

async function getBranchDecisionConfig(
	this: FocusAgentEndpointContext,
): Promise<FocusAgentBranchDecisionConfig> {
	return this.requestJson<FocusAgentBranchDecisionConfig>(
		"/v1/branch-decisions/config",
		{
			method: "GET",
			headers: {},
		},
		true,
	);
}

async function listThreadBranchDecisions(
	this: FocusAgentEndpointContext,
	threadId: string,
	options: {
		status?: string | null;
		action?: string | null;
		limit?: number;
	} = {},
): Promise<FocusAgentBranchDecisionListResponse> {
	const params = new URLSearchParams();
	if (options.status) params.set("status", options.status);
	if (options.action) params.set("action", options.action);
	if (options.limit) params.set("limit", String(options.limit));
	const suffix = params.toString() ? `?${params.toString()}` : "";
	return this.requestJson<FocusAgentBranchDecisionListResponse>(
		`/v1/threads/${encodeURIComponent(threadId)}/branch-decisions${suffix}`,
		{
			method: "GET",
			headers: {},
		},
		true,
	);
}

async function promoteBranchDecision(
	this: FocusAgentEndpointContext,
	threadId: string,
	decisionId: string,
): Promise<FocusAgentBranchDecisionEvent> {
	return this.requestJson<FocusAgentBranchDecisionEvent>(
		`/v1/threads/${encodeURIComponent(threadId)}/branch-decisions/${encodeURIComponent(decisionId)}/promote`,
		{
			method: "POST",
			headers: {},
		},
		true,
	);
}

async function dismissBranchDecision(
	this: FocusAgentEndpointContext,
	threadId: string,
	decisionId: string,
	request: FocusAgentBranchDecisionDismissRequest = {},
): Promise<FocusAgentBranchDecisionEvent> {
	return this.requestJson<FocusAgentBranchDecisionEvent>(
		`/v1/threads/${encodeURIComponent(threadId)}/branch-decisions/${encodeURIComponent(decisionId)}/dismiss`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(request),
		},
		true,
	);
}

export interface BranchDecisionEndpoints {
	getBranchDecisionConfig: OmitThisParameter<typeof getBranchDecisionConfig>;
	listThreadBranchDecisions: OmitThisParameter<
		typeof listThreadBranchDecisions
	>;
	promoteBranchDecision: OmitThisParameter<typeof promoteBranchDecision>;
	dismissBranchDecision: OmitThisParameter<typeof dismissBranchDecision>;
}

const branchDecisionEndpoints: FocusAgentEndpointMethodMap<BranchDecisionEndpoints> =
	{
		getBranchDecisionConfig,
		listThreadBranchDecisions,
		promoteBranchDecision,
		dismissBranchDecision,
	};

export function applyBranchDecisionEndpoints(
	Client: EndpointClientConstructor,
): void {
	applyEndpointMethods(Client, branchDecisionEndpoints);
}
