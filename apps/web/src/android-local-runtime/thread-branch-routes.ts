import type {
	FocusAgentApplyMergeDecisionRequest,
	FocusAgentBranchActionExecuteResponse,
	FocusAgentBranchDecisionListResponse,
	FocusAgentForkBranchRequest,
	FocusAgentRenameBranchRequest,
	ThreadContextPreviewRequest,
	ThreadContextPreviewResponse,
} from "@focus-agent/web-sdk";
import {
	contextUsage,
	errorResponse,
	jsonResponse,
	nowIso,
	parseJsonBody,
	searchParamNumber,
	stringValue,
} from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import { threadBranchRecord } from "./state";

export function handleThreads(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	searchParams: URLSearchParams,
	init?: RequestInit,
): Response {
	const [threadId, resource, subresource, action] = segments;
	if (!threadId) return errorResponse(404, "Thread id is required.");
	const thread = ctx.state.threads[threadId];
	if (!thread) return errorResponse(404, "Thread not found.");
	if (!resource && method === "GET") {
		return jsonResponse(thread);
	}
	if (resource === "resolution" && method === "GET") {
		return jsonResponse(ctx.threadResolution(thread));
	}
	if (
		resource === "context" &&
		subresource === "preview" &&
		method === "POST"
	) {
		const body = parseJsonBody(init) as ThreadContextPreviewRequest;
		const previewMessages = body.draft_message
			? [...thread.messages, { type: "human", content: body.draft_message }]
			: thread.messages;
		return jsonResponse({
			context_usage: contextUsage(previewMessages),
		} satisfies ThreadContextPreviewResponse);
	}
	if (
		resource === "context" &&
		subresource === "compact" &&
		method === "POST"
	) {
		thread.rolling_summary = thread.messages
			.slice(-6)
			.map(
				(message) => `${message.type ?? "message"}: ${message.content ?? ""}`,
			)
			.join("\n")
			.slice(0, 1200);
		thread.context_usage = contextUsage(thread.messages);
		ctx.persist();
		return jsonResponse(thread);
	}
	if (resource === "branch-decisions" && !subresource && method === "GET") {
		const status = searchParams.get("status");
		const actionFilter = searchParams.get("action");
		const limit = searchParamNumber(searchParams, "limit", 20);
		const items = ctx
			.localBranchDecisions(thread.thread_id)
			.filter((item) => !status || item.status === status)
			.filter((item) => !actionFilter || item.action === actionFilter)
			.slice(0, limit);
		return jsonResponse({
			items,
			count: items.length,
		} satisfies FocusAgentBranchDecisionListResponse);
	}
	if (
		resource === "branch-decisions" &&
		subresource &&
		(action === "promote" || action === "dismiss") &&
		method === "POST"
	) {
		const body = parseJsonBody(init) as { reason?: string | null };
		const updated = ctx.updateLocalBranchDecision(
			thread,
			subresource,
			action === "promote" ? "promoted" : "dismissed",
			body.reason ?? null,
		);
		if (!updated) return errorResponse(404, "Branch decision not found.");
		ctx.persist();
		return jsonResponse(updated);
	}
	if (
		resource === "branch-actions" &&
		subresource &&
		action === "execute" &&
		method === "POST"
	) {
		const actionProposal = thread.branch_actions.find(
			(item) => item.action_id === subresource,
		);
		if (!actionProposal) return errorResponse(404, "Branch action not found.");
		actionProposal.status = "executed";
		actionProposal.executed_at = nowIso();
		const targetThreadId = actionProposal.target_parent_thread_id || threadId;
		const record = ctx.forkBranchRecord({
			parent_thread_id: targetThreadId,
			branch_name: actionProposal.suggested_branch_name ?? undefined,
			branch_role: actionProposal.branch_role,
		});
		if (!record) return errorResponse(404, "Parent thread not found.");
		actionProposal.navigation = {
			root_thread_id: record.root_thread_id,
			thread_id: record.child_thread_id,
		};
		const response: FocusAgentBranchActionExecuteResponse = {
			thread_state: thread,
			branch_action: actionProposal,
			branch_record: record,
			navigation: actionProposal.navigation,
		};
		ctx.persist();
		return jsonResponse(response);
	}
	if (
		resource === "branch-actions" &&
		subresource &&
		action === "dismiss" &&
		method === "POST"
	) {
		const actionProposal = thread.branch_actions.find(
			(item) => item.action_id === subresource,
		);
		if (!actionProposal) return errorResponse(404, "Branch action not found.");
		actionProposal.status = "dismissed";
		actionProposal.dismissed_at = nowIso();
		ctx.persist();
		return jsonResponse(thread);
	}
	return errorResponse(404, "Unsupported local thread route.");
}

export function handleBranchDecisions(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
): Response {
	const [resource] = segments;
	if (resource === "config" && method === "GET") {
		return jsonResponse(ctx.branchDecisionConfig());
	}
	return errorResponse(404, "Unsupported local branch decision route.");
}

export function handleBranches(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	init?: RequestInit,
): Response {
	const [resource, threadIdOrAction, action] = segments;
	if (resource === "tree" && threadIdOrAction && method === "GET") {
		return jsonResponse(ctx.branchTree(threadIdOrAction));
	}
	if (resource === "fork" && method === "POST") {
		const body = parseJsonBody(init) as FocusAgentForkBranchRequest;
		const record = ctx.forkBranchRecord(body);
		return record
			? jsonResponse(record)
			: errorResponse(404, "Parent thread not found.");
	}
	if (!resource) return errorResponse(404, "Branch route is required.");
	const thread = ctx.state.threads[resource];
	if (!thread) return errorResponse(404, "Branch thread not found.");
	if (!action && method === "PATCH") {
		const body = parseJsonBody(init) as FocusAgentRenameBranchRequest;
		if (!thread.branch_meta) {
			return errorResponse(400, "Root thread cannot be renamed as a branch.");
		}
		thread.branch_meta.branch_name =
			stringValue(body.branch_name).trim() || thread.branch_meta.branch_name;
		ctx.persist();
		const record = threadBranchRecord(thread);
		return record
			? jsonResponse(record)
			: errorResponse(404, "Branch not found.");
	}
	if (threadIdOrAction === "archive" && method === "POST") {
		if (!thread.branch_meta) {
			return errorResponse(400, "Root thread cannot be archived as a branch.");
		}
		thread.branch_meta.is_archived = true;
		thread.branch_meta.archived_at = nowIso();
		ctx.persist();
		return jsonResponse(threadBranchRecord(thread));
	}
	if (threadIdOrAction === "activate" && method === "POST") {
		if (!thread.branch_meta) {
			return errorResponse(400, "Root thread cannot be activated as a branch.");
		}
		thread.branch_meta.is_archived = false;
		thread.branch_meta.archived_at = null;
		ctx.persist();
		return jsonResponse(threadBranchRecord(thread));
	}
	if (threadIdOrAction === "proposal" && method === "POST") {
		const proposal = ctx.prepareMergeProposal(thread);
		ctx.persist();
		return jsonResponse(proposal);
	}
	if (threadIdOrAction === "merge" && method === "POST") {
		const body = parseJsonBody(init) as FocusAgentApplyMergeDecisionRequest;
		return jsonResponse(ctx.applyMergeDecision(thread, body));
	}
	return errorResponse(404, "Unsupported local branch route.");
}
