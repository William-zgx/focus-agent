import { errorResponse, jsonResponse } from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";

export async function handleLocalV1(
	runtime: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	searchParams: URLSearchParams,
	init?: RequestInit,
): Promise<Response> {
	const [resource] = segments;
	if (resource === "auth") {
		return runtime.handleAuth(method, segments.slice(1), init);
	}
	if (resource === "models" && method === "GET") {
		return jsonResponse(runtime.modelsResponse());
	}
	if (resource === "branch-decisions") {
		return runtime.handleBranchDecisions(method, segments.slice(1));
	}
	if (resource === "conversations") {
		return runtime.handleConversations(method, segments.slice(1), init);
	}
	if (resource === "threads") {
		return runtime.handleThreads(method, segments.slice(1), searchParams, init);
	}
	if (resource === "branches") {
		return runtime.handleBranches(method, segments.slice(1), init);
	}
	if (resource === "agent") {
		return runtime.handleAgent(method, segments.slice(1), searchParams, init);
	}
	if (resource === "memory") {
		return runtime.handleMemory(method, segments.slice(1), searchParams, init);
	}
	if (resource === "observability") {
		return runtime.handleObservability(
			method,
			segments.slice(1),
			searchParams,
			init,
		);
	}
	if (
		resource === "notes" ||
		resource === "tasks" ||
		resource === "productivity"
	) {
		return errorResponse(
			404,
			"Productivity is disabled in the Android local runtime.",
		);
	}
	if (resource === "admin") {
		return runtime.handleAdmin(method, segments.slice(1), searchParams, init);
	}
	return errorResponse(404, "Unsupported local runtime API route.");
}
