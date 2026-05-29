import type {
	BranchTreeNode,
	BranchTreeResponse,
	FocusAgentApplyMergeDecisionRequest,
	FocusAgentApplyMergeDecisionResponse,
	FocusAgentBranchActionProposal,
	FocusAgentBranchDecisionConfig,
	FocusAgentBranchDecisionEvent,
	FocusAgentBranchDecisionSummary,
	FocusAgentBranchRecord,
	FocusAgentForkBranchRequest,
	FocusAgentMergeProposal,
	MergeMode,
	ThreadResolution,
	ThreadStateResponse,
} from "@focus-agent/web-sdk";
import { LOCAL_USER_ID } from "./constants";
import { clone, contextUsage, nowIso } from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import {
	containsAny,
	localBranchHandoffMessage,
	suggestedBranchName,
	textWords,
} from "./local-text";
import { newThreadState, threadBranchRecord } from "./state";

export function threadResolution(
	_ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
): ThreadResolution {
	const meta = thread.branch_meta;
	return {
		input_thread_id: thread.thread_id,
		root_thread_id: thread.root_thread_id,
		source_thread_id: thread.thread_id,
		branch_id: meta?.branch_id ?? null,
		is_root: thread.thread_id === thread.root_thread_id,
		branch_status: meta?.branch_status ?? "active",
		diagnostic: "resolved by android local runtime",
	};
}

export function branchDecisionConfig(
	_ctx: LocalFocusAgentRuntime,
): FocusAgentBranchDecisionConfig {
	return {
		enabled: true,
		mode: "suggest",
		min_confidence: 0.7,
		split_threshold: 0.65,
		conclude_threshold: 0.7,
		merge_candidate_threshold: 0.75,
		rate_limit_per_hour: 3,
		recommendation_enabled: true,
		recommendation_mode: "suggest",
		recommendation_min_confidence: 0.72,
		recommendation_semantic_enabled: true,
		recommendation_semantic_model: null,
		recommendation_user_visible: true,
		recommendation_diagnostics: {
			code: "android_local_runtime",
			message: "Android local runtime uses a local heuristic for Focus Score.",
		},
		diagnostic: "Android local runtime",
	};
}

export function localBranchDecisions(
	ctx: LocalFocusAgentRuntime,
	threadId: string,
): FocusAgentBranchDecisionEvent[] {
	ctx.state.branchDecisions ??= {};
	return ctx.state.branchDecisions[threadId] ?? [];
}

export function setLocalBranchDecisions(
	ctx: LocalFocusAgentRuntime,
	threadId: string,
	decisions: FocusAgentBranchDecisionEvent[],
): void {
	ctx.state.branchDecisions ??= {};
	ctx.state.branchDecisions[threadId] = decisions.slice(0, 20);
}

export function updateBranchDecisionSummary(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
): void {
	const decisions = ctx.localBranchDecisions(thread.thread_id);
	const latest = decisions[0] ?? null;
	const summary: FocusAgentBranchDecisionSummary = {
		latest_decision: latest,
		actionable: Boolean(
			latest &&
				latest.status === "suggested" &&
				!latest.promoted_action_id &&
				(latest.action === "fork_child_branch" ||
					latest.action === "fork_sibling_branch" ||
					latest.action === "split"),
		),
		pending_action_id:
			latest?.status === "promoted"
				? (latest.promoted_action_id ?? null)
				: null,
		dismissed_count: decisions.filter((item) => item.status === "dismissed")
			.length,
	};
	thread.branch_decision_summary = latest ? summary : null;
}

export function updateLocalBranchDecision(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
	decisionId: string,
	status: "promoted" | "dismissed",
	dismissReason: string | null,
): FocusAgentBranchDecisionEvent | null {
	const decisions = ctx.localBranchDecisions(thread.thread_id);
	const index = decisions.findIndex((item) => item.decision_id === decisionId);
	if (index < 0) return null;
	const decision = { ...decisions[index] };
	decision.status = status;
	decision.dismiss_reason =
		status === "dismissed" ? (dismissReason ?? "user_dismissed") : null;
	decision.updated_at = nowIso();
	decision.executed_at = decision.executed_at ?? nowIso();
	if (status === "promoted" && !decision.promoted_action_id) {
		ctx.createBranchActionFromDecision(thread, decision, decision.updated_at);
	}
	decisions[index] = decision;
	ctx.setLocalBranchDecisions(thread.thread_id, decisions);
	ctx.updateBranchDecisionSummary(thread);
	return decision;
}

export function createBranchActionFromDecision(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
	decision: FocusAgentBranchDecisionEvent,
	timestamp: string,
): FocusAgentBranchActionProposal | null {
	if (
		decision.action !== "fork_child_branch" &&
		decision.action !== "fork_sibling_branch"
	) {
		return null;
	}
	const targetParentThreadId = decision.target_parent_thread_id;
	if (!targetParentThreadId) return null;
	const actionId = ctx.nextId("action", "local-branch-action");
	decision.promoted_action_id = actionId;
	const actionProposal: FocusAgentBranchActionProposal = {
		action_id: actionId,
		kind: decision.action,
		status: "pending",
		root_thread_id: thread.root_thread_id,
		source_thread_id: thread.thread_id,
		target_parent_thread_id: targetParentThreadId,
		suggested_branch_name: decision.suggested_branch_name,
		branch_role: "explore_alternatives",
		reason: decision.rationale,
		created_at: timestamp,
		executed_at: null,
		dismissed_at: null,
		failed_at: null,
		error: null,
		navigation: null,
		source: "branch_decision",
		source_decision_id: decision.decision_id,
		source_decision_status: decision.status,
		source_decision_mode: decision.mode,
		confidence: decision.score,
		rationale: decision.rationale,
		recommendation_user_visible: true,
		diagnostic: decision.diagnostic,
		handoff_message: localBranchHandoffMessage(
			decision.suggested_branch_name ?? "",
		),
	};
	thread.branch_actions = [...thread.branch_actions, actionProposal];
	return actionProposal;
}

export function recordLocalBranchDecision(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
	message: string,
	runId: string,
): FocusAgentBranchDecisionEvent | null {
	const compactMessage = message.replace(/\s+/g, " ").trim();
	if (!compactMessage) return null;
	const isChinese = /[\u3400-\u9fff]/.test(compactMessage);
	const priorMessages = thread.messages.slice(0, -1);
	const priorText = priorMessages
		.slice(-8)
		.map((item) => String(item.content ?? ""))
		.join(" ");
	const messageWords = textWords(compactMessage);
	const priorWords = new Set(textWords(priorText));
	const overlap = messageWords.filter((word) => priorWords.has(word)).length;
	const overlapRatio = messageWords.length ? overlap / messageWords.length : 0;
	const explicitBranchCue = containsAny(compactMessage, [
		"new branch",
		"separate branch",
		"side branch",
		"branch off",
		"fork",
		"different topic",
		"another topic",
		"switch topic",
		"unrelated",
		"explore alternative",
		"alternative path",
		"what about",
		"新分支",
		"另起",
		"单独",
		"换个话题",
		"另外",
		"题外",
		"不相关",
		"另一条线",
	]);
	const stayCue = containsAny(compactMessage, [
		"continue current",
		"same branch",
		"stay in current",
		"keep going",
		"继续当前",
		"当前分支",
		"不用分支",
		"留在当前",
	]);
	let relatedness = priorWords.size
		? Math.min(0.95, Math.max(0.24, 0.34 + overlapRatio * 0.65))
		: 0.82;
	if (explicitBranchCue) relatedness = Math.min(relatedness, 0.34);
	if (stayCue) relatedness = Math.max(relatedness, 0.78);
	const hasConversationContext = priorMessages.length >= 2;
	const hasPendingAction = thread.branch_actions.some(
		(action) => action.status === "pending",
	);
	const shouldFork =
		!stayCue &&
		!hasPendingAction &&
		(explicitBranchCue ||
			(hasConversationContext &&
				messageWords.length >= 4 &&
				relatedness < 0.42));
	const action = shouldFork
		? thread.branch_meta
			? "fork_sibling_branch"
			: "fork_child_branch"
		: "continue_current";
	const targetParentThreadId = shouldFork
		? (thread.branch_meta?.parent_thread_id ?? thread.thread_id)
		: null;
	const score = shouldFork
		? Math.max(0.72, Math.min(0.96, 1 - relatedness))
		: relatedness;
	const timestamp = nowIso();
	const decisionId = ctx.nextId("action", "local-branch-decision");
	const diagnostic = {
		code: "android_local_focus_score",
		message: shouldFork
			? "Message appears better handled in a separate branch."
			: "Message appears related enough to continue in the current branch.",
		gate_reason: shouldFork ? "eligible" : "continue_current",
		threshold: shouldFork ? 0.72 : 0.65,
		semantic_classifier_status: "local_heuristic",
		semantic_relatedness: relatedness,
		semantic_relationship: shouldFork ? "topic_shift" : "related",
	};
	const signals = [
		{
			name: "semantic_relatedness",
			value: relatedness,
			score: relatedness,
			weight: 1,
			evidence_refs: [],
			rationale: "Estimated from lexical overlap with recent local context.",
		},
		{
			name: "explicit_branch_cue",
			value: explicitBranchCue,
			score: explicitBranchCue ? 1 : 0,
			weight: 0.5,
			evidence_refs: [],
			rationale:
				"Checks whether the user explicitly asked for a separate path.",
		},
	];
	const decision: FocusAgentBranchDecisionEvent = {
		decision_id: decisionId,
		user_id: LOCAL_USER_ID,
		root_thread_id: thread.root_thread_id,
		source_thread_id: thread.thread_id,
		branch_id: thread.branch_meta?.branch_id ?? null,
		recommendation_target: action,
		target_parent_thread_id: targetParentThreadId,
		suggested_branch_name: shouldFork
			? suggestedBranchName(compactMessage, isChinese)
			: null,
		confidence: score,
		action,
		status: shouldFork ? "promoted" : "skipped",
		mode: "suggest",
		score,
		threshold: shouldFork ? 0.72 : 0.65,
		signals,
		rationale: shouldFork
			? "Local Focus Score detected a likely topic shift."
			: "Local Focus Score keeps this turn on the current branch.",
		idempotency_key: `${thread.thread_id}:${runId}`,
		request_id: runId,
		trace_id: runId,
		promoted_action_id: null,
		dismiss_reason: null,
		error: null,
		recommendation_user_visible: true,
		diagnostic,
		metadata: {
			phase: "pre_turn",
			recommendation_target: action,
			recommendation_user_visible: true,
			semantic_classifier_status: "local_heuristic",
			semantic_relatedness: relatedness,
			semantic_relationship: shouldFork ? "topic_shift" : "related",
			semantic_reason: diagnostic.message,
			diagnostic,
			target_parent_thread_id: targetParentThreadId,
		},
		created_at: timestamp,
		updated_at: timestamp,
		executed_at: shouldFork ? timestamp : null,
	};
	if (shouldFork && targetParentThreadId) {
		const actionProposal = ctx.createBranchActionFromDecision(
			thread,
			decision,
			timestamp,
		);
		if (actionProposal) {
			actionProposal.handoff_message =
				localBranchHandoffMessage(compactMessage);
		}
	}
	ctx.setLocalBranchDecisions(thread.thread_id, [
		decision,
		...ctx.localBranchDecisions(thread.thread_id),
	]);
	ctx.updateBranchDecisionSummary(thread);
	return decision;
}

export function branchTree(
	ctx: LocalFocusAgentRuntime,
	rootThreadId: string,
): BranchTreeResponse {
	const rootThread = ctx.state.threads[rootThreadId];
	const actualRootThread =
		rootThread?.root_thread_id && ctx.state.threads[rootThread.root_thread_id]
			? ctx.state.threads[rootThread.root_thread_id]
			: rootThread;
	if (!actualRootThread) {
		return {
			root: ctx.branchTreeNode(newThreadState(rootThreadId, rootThreadId)),
			archived_branches: [],
		};
	}
	const root = ctx.branchTreeNode(actualRootThread);
	const archivedBranches: BranchTreeNode[] = [];
	const attachChildren = (node: BranchTreeNode) => {
		const children = Object.values(ctx.state.threads)
			.filter(
				(thread) => thread.branch_meta?.parent_thread_id === node.thread_id,
			)
			.map((thread) => ctx.branchTreeNode(thread));
		for (const child of children) {
			attachChildren(child);
			if (child.is_archived) {
				archivedBranches.push(child);
			} else {
				node.children.push(child);
			}
		}
	};
	attachChildren(root);
	return { root, archived_branches: archivedBranches };
}

export function branchTreeNode(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
): BranchTreeNode {
	const meta = thread.branch_meta;
	const conversation = ctx.state.conversations.find(
		(item) => item.root_thread_id === thread.root_thread_id,
	);
	return {
		thread_id: thread.thread_id,
		root_thread_id: thread.root_thread_id,
		parent_thread_id: meta?.parent_thread_id ?? null,
		branch_id: meta?.branch_id ?? null,
		branch_name: meta?.branch_name ?? conversation?.title ?? "Main",
		branch_role: meta?.branch_role ?? "main",
		branch_status: meta?.branch_status ?? "active",
		is_archived: Boolean(meta?.is_archived),
		archived_at: meta?.archived_at ?? null,
		branch_depth: meta?.branch_depth ?? 0,
		fork_strategy: meta?.fork_strategy ?? "root",
		token_usage: {
			input_tokens: thread.context_usage?.used_tokens ?? 0,
			output_tokens: 0,
			total_tokens: thread.context_usage?.used_tokens ?? 0,
		},
		children: [],
	};
}

export function forkBranchRecord(
	ctx: LocalFocusAgentRuntime,
	request: FocusAgentForkBranchRequest,
): FocusAgentBranchRecord | null {
	const parentThread = ctx.state.threads[request.parent_thread_id];
	if (!parentThread) {
		return null;
	}
	const threadId = ctx.nextId("thread", "local-thread");
	const branchId = ctx.nextId("branch", "local-branch");
	const parentDepth = parentThread.branch_meta?.branch_depth ?? 0;
	const thread = newThreadState(threadId, parentThread.root_thread_id);
	thread.messages = clone(parentThread.messages);
	thread.context_usage = contextUsage(thread.messages);
	thread.branch_meta = {
		branch_id: branchId,
		root_thread_id: parentThread.root_thread_id,
		parent_thread_id: parentThread.thread_id,
		return_thread_id: parentThread.root_thread_id,
		branch_name:
			request.branch_name?.trim() ||
			(request.language === "zh" ? "本地分支" : "Local branch"),
		branch_role: request.branch_role ?? "explore_alternatives",
		branch_depth: parentDepth + 1,
		branch_status: "active",
		is_archived: false,
		archived_at: null,
		fork_checkpoint_id: request.fork_checkpoint_id ?? null,
		fork_strategy: request.name_source ?? "manual",
	};
	ctx.state.threads[threadId] = thread;
	ctx.persist();
	const record = threadBranchRecord(thread);
	if (!record) {
		return null;
	}
	return record;
}

export function prepareMergeProposal(
	_ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
): FocusAgentMergeProposal {
	const lastAssistantMessage = [...thread.messages]
		.reverse()
		.find((message) => message.type === "ai");
	const summary =
		String(lastAssistantMessage?.content ?? "").slice(0, 500) ||
		"Local branch summary.";
	const proposal: FocusAgentMergeProposal = {
		summary,
		key_findings: ["Conversation state was produced locally on Android."],
		open_questions: [],
		evidence_refs: [],
		artifacts: [],
		recommended_import_mode: "summary_only",
	};
	thread.merge_proposal = proposal;
	if (thread.branch_meta) {
		thread.branch_meta.branch_status = "awaiting_merge_review";
	}
	return proposal;
}

export function applyMergeDecision(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
	request: FocusAgentApplyMergeDecisionRequest,
): FocusAgentApplyMergeDecisionResponse {
	const approved = request.approved ?? true;
	const proposal = thread.merge_proposal ?? ctx.prepareMergeProposal(thread);
	const mode: MergeMode = request.mode ?? proposal.recommended_import_mode;
	const targetThreadId =
		request.target === "return_thread"
			? (thread.branch_meta?.return_thread_id ?? thread.root_thread_id)
			: thread.root_thread_id;
	const targetThread = ctx.state.threads[targetThreadId];
	thread.merge_decision = { ...request, approved, decided_at: nowIso() };
	if (approved && targetThread) {
		const imported = {
			branch_id: thread.branch_meta?.branch_id ?? thread.thread_id,
			branch_name: thread.branch_meta?.branch_name ?? "Local branch",
			mode,
			summary: request.proposal_overrides?.summary ?? proposal.summary,
			key_findings:
				request.proposal_overrides?.key_findings ?? proposal.key_findings,
			evidence_refs:
				request.proposal_overrides?.evidence_refs ?? proposal.evidence_refs,
			artifacts: request.proposal_overrides?.artifacts ?? proposal.artifacts,
			rationale: request.rationale ?? null,
		};
		targetThread.merge_queue.push(imported);
		targetThread.messages.push({
			id: ctx.nextId("message", "local-message"),
			type: "ai",
			content: `Merged local branch "${imported.branch_name}": ${imported.summary}`,
			created_at: nowIso(),
		});
		targetThread.context_usage = contextUsage(targetThread.messages);
		if (thread.branch_meta) {
			thread.branch_meta.branch_status = "merged";
		}
		ctx.persist();
		return { imported, target_thread_id: targetThreadId };
	}
	if (thread.branch_meta) {
		thread.branch_meta.branch_status = "discarded";
	}
	ctx.persist();
	return { imported: null, target_thread_id: targetThreadId };
}
