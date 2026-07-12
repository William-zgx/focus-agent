import type {
	BranchTreeNode,
	BranchTreeResponse,
	FocusAgentAdminConfig,
	FocusAgentApplyMergeDecisionRequest,
	FocusAgentApplyMergeDecisionResponse,
	FocusAgentAuditEventListResponse,
	FocusAgentBranchActionProposal,
	FocusAgentBranchDecisionConfig,
	FocusAgentBranchDecisionEvent,
	FocusAgentBranchRecord,
	FocusAgentForkBranchRequest,
	FocusAgentHarnessRunRequest,
	FocusAgentMergeProposal,
	FocusAgentModelsResponse,
	FocusAgentSessionListResponse,
	FocusAgentUser,
	FocusAgentUserListResponse,
	ThreadResolution,
	ThreadStateResponse,
} from "@focus-agent/web-sdk";
import { handleAdminConfig, touchAdminConfig } from "./admin-runtime";
import {
	handleAgent,
	handleLocalAgentContext,
	handleLocalAgentDelegation,
	handleLocalAgentMemory,
	handleLocalAgentModelRouter,
	handleLocalAgentTaskLedger,
	localAgentEmptyList,
	localCapabilities,
	localContextEvidenceRecord,
	localEnabledTools,
	localRoleDecision,
	localRolePolicy,
	localSelectedSkills,
	localSkillCatalogItems,
	localTool,
	localToolEnabled,
} from "./agent-runtime";
import {
	auditEvents,
	handleAuth,
	handleConversations,
	sessionList,
	touchConversation,
	userList,
} from "./auth-conversation-runtime";
import {
	applyMergeDecision,
	branchDecisionConfig,
	branchTree,
	branchTreeNode,
	createBranchActionFromDecision,
	forkBranchRecord,
	localBranchDecisions,
	prepareMergeProposal,
	recordLocalBranchDecision,
	setLocalBranchDecisions,
	threadResolution,
	updateBranchDecisionSummary,
	updateLocalBranchDecision,
} from "./branch-logic";
import {
	ANDROID_LOCAL_ADMIN_UNSUPPORTED_MESSAGE,
	ANDROID_LOCAL_AUTH_UNSUPPORTED_MESSAGE,
	LOCAL_TENANT_ID,
	LOCAL_USER_ID,
	STORAGE_KEY,
} from "./constants";
import { errorResponse, id, nowIso, routeSegments } from "./helpers";
import { LocalRunCancellationRegistry } from "./local-run-cancellation";
import {
	executeLocalAppTool,
	localArtifactsForThread,
	localSkillPayload,
} from "./local-tool-execution";
import {
	localAppToolPlan,
	localArtifactIdFromMessage,
	localMemoryIdFromMessage,
} from "./local-tool-planning";
import { handleLocalV1 } from "./local-v1-runtime";
import {
	handleMemory,
	handleObservability,
	localMemoryRecords,
	localObservabilityOverview,
	localTrajectoryDetail,
	localTrajectoryList,
	localTrajectoryPromotion,
	localTrajectoryReplay,
	localTrajectoryStats,
	localTrajectorySummary,
} from "./memory-observability-runtime";
import {
	readSecureModelSecrets,
	writeSecureModelSecrets,
} from "./model-provider";
import {
	adminConfigResponse,
	chatMessages,
	modelProvider,
	modelProviderLabel,
	modelsResponse,
	providerConfigForModel,
	providerMatchesModelPrefix,
	threadMessagesForProvider,
} from "./model-runtime";
import { initialState, localUser, normalizeStoredState } from "./state";
import { handleV2, streamRun } from "./stream-runtime";
import {
	handleBranchDecisions,
	handleBranches,
	handleThreads,
} from "./thread-branch-routes";
import type {
	ChatCompletionMessage,
	JsonRecord,
	LocalArtifact,
	LocalRuntimeSequence,
	LocalRuntimeState,
	LocalSkill,
	LocalToolExecution,
	LocalWebFetchResult,
	LocalWebSearchResult,
	ResolvedLocalModelProvider,
} from "./types";
import {
	applyPatchToWorkspace,
	fileDiff,
	languageForPath,
	localCommandFromMessage,
	localPatchFromMessage,
	localWorkspacePathFromMessage,
	normalizeWorkspacePath,
	workspaceBaseFiles,
	workspaceDiff,
	workspaceFileEntries,
	workspaceFiles,
	workspaceStatusEntries,
} from "./workspace-runtime";

export function createLocalFocusAgentFetch(): typeof fetch {
	const runtime = new LocalFocusAgentRuntime();
	return ((input, init) => runtime.fetch(input, init)) as typeof fetch;
}

export class LocalFocusAgentRuntime {
	modelSecrets: Record<string, { apiKey?: string }> = {};
	readonly runCancellations = new LocalRunCancellationRegistry();
	secretsReady: Promise<void> | null = null;
	state = this.loadState();

	constructor(
		private readonly modelSecretStorage: {
			read(): Promise<Record<string, { apiKey?: string }>>;
			write(secrets: Record<string, { apiKey?: string }>): Promise<void>;
		} = {
			read: readSecureModelSecrets,
			write: writeSecureModelSecrets,
		},
	) {}

	async fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
		if (init?.signal?.aborted) {
			throw init.signal.reason ?? new DOMException("Aborted", "AbortError");
		}
		const requestUrl =
			input instanceof Request
				? input.url
				: input instanceof URL
					? input.href
					: input;
		const url = new URL(requestUrl, window.location.origin);
		const method = (
			init?.method ?? (input instanceof Request ? input.method : "GET")
		).toUpperCase();
		const segments = routeSegments(url.pathname);
		const headers = new Headers(
			input instanceof Request ? input.headers : undefined,
		);
		if (init?.headers) {
			for (const [name, value] of new Headers(init.headers)) {
				headers.set(name, value);
			}
		}
		if (headers.get("Authorization")?.trim()) {
			return errorResponse(401, ANDROID_LOCAL_AUTH_UNSUPPORTED_MESSAGE);
		}
		await this.ensureSecrets();

		if (segments[0] === "v1") {
			return this.handleV1(method, segments.slice(1), url.searchParams, init);
		}
		if (segments[0] === "v2") {
			return this.handleV2(method, segments.slice(1), init);
		}
		return errorResponse(404, "Unsupported local runtime endpoint.");
	}

	loadState(): LocalRuntimeState {
		try {
			const raw = window.localStorage.getItem(STORAGE_KEY);
			if (!raw) return initialState();
			const parsed = JSON.parse(raw) as LocalRuntimeState;
			if (
				(parsed?.version !== 1 && parsed?.version !== 2) ||
				!parsed.threads ||
				!parsed.conversations
			) {
				return initialState();
			}
			const state = normalizeStoredState(parsed);
			window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
			return state;
		} catch {
			return initialState();
		}
	}

	persist(): void {
		try {
			this.writeStateToLocalStorage();
		} catch (error) {
			console.warn("Failed to persist Android local runtime state", error);
		}
	}

	private writeStateToLocalStorage(): void {
		const { modelSecrets: legacyModelSecrets, ...stateWithoutSecrets } =
			this.state;
		const persistedState = legacyModelSecrets
			? { ...stateWithoutSecrets, modelSecrets: legacyModelSecrets }
			: stateWithoutSecrets;
		window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persistedState));
	}

	async ensureSecrets(): Promise<void> {
		const activeAttempt = this.secretsReady ?? this.loadSecrets();
		this.secretsReady = activeAttempt;
		try {
			await activeAttempt;
		} catch (error) {
			if (this.secretsReady === activeAttempt) {
				this.secretsReady = null;
			}
			throw error;
		}
	}

	async loadSecrets(): Promise<void> {
		const storedSecrets = await this.modelSecretStorage.read();
		const legacySecrets = this.state.modelSecrets ?? {};
		this.modelSecrets = { ...legacySecrets, ...storedSecrets };
		if (this.state.modelSecrets) {
			const legacyModelSecrets = this.state.modelSecrets;
			await this.persistSecrets();
			delete this.state.modelSecrets;
			try {
				this.writeStateToLocalStorage();
			} catch (error) {
				this.state.modelSecrets = legacyModelSecrets;
				throw error;
			}
		}
	}

	async persistSecrets(): Promise<void> {
		await this.modelSecretStorage.write(this.modelSecrets);
	}

	nextId(prefix: keyof LocalRuntimeSequence, label: string): string {
		const value = this.state.sequence[prefix];
		this.state.sequence[prefix] += 1;
		return id(label, value);
	}

	currentUser(): FocusAgentUser {
		let user = this.state.users.find((item) => item.user_id === LOCAL_USER_ID);
		if (!user) {
			user = localUser();
			this.state.users.unshift(user);
			this.persist();
		}
		user.last_seen_at = nowIso();
		return user;
	}

	addAuditEvent(
		action: string,
		resourceType: string,
		resourceId?: string | null,
		metadata: JsonRecord = {},
	): void {
		this.state.auditEvents.unshift({
			event_id: this.nextId("audit", "local-audit"),
			actor_user_id: LOCAL_USER_ID,
			tenant_id: LOCAL_TENANT_ID,
			action,
			resource_type: resourceType,
			resource_id: resourceId ?? null,
			decision: "allowed",
			reason: "android-local-runtime",
			metadata,
			request_id: null,
			created_at: nowIso(),
		});
	}

	localAgentEmptyList(limit = 50) {
		return localAgentEmptyList(this, limit);
	}

	localTool(name: string) {
		return localTool(this, name);
	}

	localEnabledTools() {
		return localEnabledTools(this);
	}

	localToolEnabled(name: string): boolean {
		return localToolEnabled(this, name);
	}

	localCapabilities() {
		return localCapabilities(this);
	}

	localRolePolicy() {
		return localRolePolicy(this);
	}

	localRoleDecision(message: string, role = "planner") {
		return localRoleDecision(this, message, role);
	}

	localSkillCatalogItems() {
		return localSkillCatalogItems(this);
	}

	localSelectedSkills(message: string, hints: string[] = []) {
		return localSelectedSkills(this, message, hints);
	}

	localContextEvidenceRecord(
		input: { message?: unknown; thread_id?: unknown; turn_id?: unknown } = {},
	) {
		return localContextEvidenceRecord(this, input);
	}

	handleLocalAgentMemory(
		method: string,
		subresource?: string,
		third?: string,
		limit = 50,
	): Response {
		return handleLocalAgentMemory(this, method, subresource, third, limit);
	}

	handleLocalAgentDelegation(
		method: string,
		subresource?: string,
		limit = 50,
		init?: RequestInit,
	): Response {
		return handleLocalAgentDelegation(this, method, subresource, limit, init);
	}

	handleLocalAgentModelRouter(
		method: string,
		subresource?: string,
		limit = 50,
		init?: RequestInit,
	): Response {
		return handleLocalAgentModelRouter(this, method, subresource, limit, init);
	}

	handleLocalAgentContext(
		method: string,
		subresource?: string,
		limit = 50,
		init?: RequestInit,
	): Response {
		return handleLocalAgentContext(this, method, subresource, limit, init);
	}

	handleLocalAgentTaskLedger(
		method: string,
		subresource?: string,
		limit = 50,
		init?: RequestInit,
	): Response {
		return handleLocalAgentTaskLedger(this, method, subresource, limit, init);
	}

	localMemoryRecords() {
		return localMemoryRecords(this);
	}

	localTrajectoryList(searchParams: URLSearchParams) {
		return localTrajectoryList(this, searchParams);
	}

	localTrajectorySummary(thread: ThreadStateResponse) {
		return localTrajectorySummary(this, thread);
	}

	localTrajectoryDetail(turnId: string) {
		return localTrajectoryDetail(this, turnId);
	}

	localTrajectoryStats() {
		return localTrajectoryStats(this);
	}

	localObservabilityOverview(searchParams: URLSearchParams) {
		return localObservabilityOverview(this, searchParams);
	}

	localTrajectoryReplay(detail: JsonRecord, model?: string | null) {
		return localTrajectoryReplay(this, detail, model);
	}

	localTrajectoryPromotion(detail: JsonRecord) {
		return localTrajectoryPromotion(this, detail);
	}

	adminConfigResponse(): FocusAgentAdminConfig {
		return adminConfigResponse(this);
	}

	providerMatchesModelPrefix(
		provider: FocusAgentAdminConfig["models"]["providers"][number],
		modelProviderPrefix: string,
	): boolean {
		return providerMatchesModelPrefix(this, provider, modelProviderPrefix);
	}

	providerConfigForModel(selectedModel: string): {
		model: string;
		provider: FocusAgentAdminConfig["models"]["providers"][number] | null;
	} | null {
		return providerConfigForModel(this, selectedModel);
	}

	modelProvider(selectedModel: string): ResolvedLocalModelProvider | null {
		return modelProvider(this, selectedModel);
	}

	modelProviderLabel(selectedModel: string): string {
		return modelProviderLabel(this, selectedModel);
	}

	chatMessages(
		thread: ThreadStateResponse,
		webSearchResult?: LocalWebSearchResult | null,
		webFetchResult?: LocalWebFetchResult | null,
		localToolExecutions: LocalToolExecution[] = [],
	): ChatCompletionMessage[] {
		return chatMessages(
			this,
			thread,
			webSearchResult,
			webFetchResult,
			localToolExecutions,
		);
	}

	localAppToolPlan(
		thread: ThreadStateResponse,
		message: string,
	): Array<{ name: string; args: Record<string, unknown> }> {
		return localAppToolPlan(this, thread, message);
	}

	localArtifactIdFromMessage(message: string): string | null {
		return localArtifactIdFromMessage(this, message);
	}

	localMemoryIdFromMessage(message: string): string | null {
		return localMemoryIdFromMessage(this, message);
	}

	localArtifactsForThread(thread: ThreadStateResponse): LocalArtifact[] {
		return localArtifactsForThread(this, thread);
	}

	localSkillPayload(skill: LocalSkill): Record<string, unknown> {
		return localSkillPayload(this, skill);
	}

	workspaceFiles(): Record<string, string> {
		return workspaceFiles(this);
	}

	workspaceBaseFiles(): Record<string, string> {
		return workspaceBaseFiles(this);
	}

	normalizeWorkspacePath(value: unknown): string | null {
		return normalizeWorkspacePath(this, value);
	}

	localWorkspacePathFromMessage(message: string): string | null {
		return localWorkspacePathFromMessage(this, message);
	}

	localPatchFromMessage(message: string): string {
		return localPatchFromMessage(this, message);
	}

	localCommandFromMessage(message: string): string[] {
		return localCommandFromMessage(this, message);
	}

	workspaceFileEntries(pathValue: unknown = ".") {
		return workspaceFileEntries(this, pathValue);
	}

	languageForPath(path: string): string {
		return languageForPath(this, path);
	}

	fileDiff(path: string, before = "", after = ""): string {
		return fileDiff(this, path, before, after);
	}

	workspaceDiff(pathspec?: unknown): string {
		return workspaceDiff(this, pathspec);
	}

	workspaceStatusEntries(): string[] {
		return workspaceStatusEntries(this);
	}

	applyPatchToWorkspace(patch: string): string[] {
		return applyPatchToWorkspace(this, patch);
	}

	executeLocalAppTool(
		thread: ThreadStateResponse,
		name: string,
		args: Record<string, unknown>,
	): LocalToolExecution {
		return executeLocalAppTool(this, thread, name, args);
	}

	threadMessagesForProvider(
		thread: ThreadStateResponse,
	): ChatCompletionMessage[] {
		return threadMessagesForProvider(this, thread);
	}

	async handleV1(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Promise<Response> {
		return handleLocalV1(this, method, segments, searchParams, init);
	}

	handleAuth(method: string, segments: string[], init?: RequestInit): Response {
		return handleAuth(this, method, segments, init);
	}

	handleConversations(
		method: string,
		segments: string[],
		init?: RequestInit,
	): Response {
		return handleConversations(this, method, segments, init);
	}

	handleThreads(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		return handleThreads(this, method, segments, searchParams, init);
	}

	handleBranchDecisions(method: string, segments: string[]): Response {
		return handleBranchDecisions(this, method, segments);
	}

	handleBranches(
		method: string,
		segments: string[],
		init?: RequestInit,
	): Response {
		return handleBranches(this, method, segments, init);
	}

	handleMemory(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		return handleMemory(this, method, segments, searchParams, init);
	}

	handleObservability(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		return handleObservability(this, method, segments, searchParams, init);
	}

	handleAgent(
		method: string,
		segments: string[],
		searchParams: URLSearchParams,
		init?: RequestInit,
	): Response {
		return handleAgent(this, method, segments, searchParams, init);
	}

	async handleAdmin(
		method: string,
		segments: string[],
		_searchParams: URLSearchParams,
		init?: RequestInit,
	): Promise<Response> {
		if (segments[0] === "config") {
			return this.handleAdminConfig(method, segments[1], init);
		}
		return errorResponse(403, ANDROID_LOCAL_ADMIN_UNSUPPORTED_MESSAGE);
	}

	handleAdminUsers(
		_method: string,
		_userId: string | undefined,
		_subresource: string | undefined,
		_action: string | undefined,
		_searchParams: URLSearchParams,
		_init?: RequestInit,
	): Response {
		return errorResponse(403, ANDROID_LOCAL_ADMIN_UNSUPPORTED_MESSAGE);
	}

	async handleAdminConfig(
		method: string,
		resource?: string,
		init?: RequestInit,
	): Promise<Response> {
		return handleAdminConfig(this, method, resource, init);
	}

	handleV2(method: string, segments: string[], init?: RequestInit): Response {
		return handleV2(this, method, segments, init);
	}

	streamRun(
		threadId: string,
		request: FocusAgentHarnessRunRequest,
		signal?: AbortSignal,
	): Response {
		return streamRun(this, threadId, request, signal);
	}

	modelsResponse(): FocusAgentModelsResponse {
		return modelsResponse(this);
	}

	threadResolution(thread: ThreadStateResponse): ThreadResolution {
		return threadResolution(this, thread);
	}

	branchDecisionConfig(): FocusAgentBranchDecisionConfig {
		return branchDecisionConfig(this);
	}

	localBranchDecisions(threadId: string): FocusAgentBranchDecisionEvent[] {
		return localBranchDecisions(this, threadId);
	}

	setLocalBranchDecisions(
		threadId: string,
		decisions: FocusAgentBranchDecisionEvent[],
	): void {
		setLocalBranchDecisions(this, threadId, decisions);
	}

	updateBranchDecisionSummary(thread: ThreadStateResponse): void {
		updateBranchDecisionSummary(this, thread);
	}

	updateLocalBranchDecision(
		thread: ThreadStateResponse,
		decisionId: string,
		status: "promoted" | "dismissed",
		dismissReason: string | null,
	): FocusAgentBranchDecisionEvent | null {
		return updateLocalBranchDecision(
			this,
			thread,
			decisionId,
			status,
			dismissReason,
		);
	}

	createBranchActionFromDecision(
		thread: ThreadStateResponse,
		decision: FocusAgentBranchDecisionEvent,
		timestamp: string,
	): FocusAgentBranchActionProposal | null {
		return createBranchActionFromDecision(this, thread, decision, timestamp);
	}

	recordLocalBranchDecision(
		thread: ThreadStateResponse,
		message: string,
		runId: string,
	): FocusAgentBranchDecisionEvent | null {
		return recordLocalBranchDecision(this, thread, message, runId);
	}

	branchTree(rootThreadId: string): BranchTreeResponse {
		return branchTree(this, rootThreadId);
	}

	branchTreeNode(thread: ThreadStateResponse): BranchTreeNode {
		return branchTreeNode(this, thread);
	}

	forkBranchRecord(
		request: FocusAgentForkBranchRequest,
	): FocusAgentBranchRecord | null {
		return forkBranchRecord(this, request);
	}

	prepareMergeProposal(thread: ThreadStateResponse): FocusAgentMergeProposal {
		return prepareMergeProposal(this, thread);
	}

	applyMergeDecision(
		thread: ThreadStateResponse,
		request: FocusAgentApplyMergeDecisionRequest,
	): FocusAgentApplyMergeDecisionResponse {
		return applyMergeDecision(this, thread, request);
	}

	sessionList(
		userId: string,
		searchParams: URLSearchParams = new URLSearchParams(),
	): FocusAgentSessionListResponse {
		return sessionList(this, userId, searchParams);
	}

	userList(searchParams: URLSearchParams): FocusAgentUserListResponse {
		return userList(this, searchParams);
	}

	auditEvents(searchParams: URLSearchParams): FocusAgentAuditEventListResponse {
		return auditEvents(this, searchParams);
	}

	touchConversation(rootThreadId: string, message: string): void {
		touchConversation(this, rootThreadId, message);
	}

	touchAdminConfig(message: string): void {
		touchAdminConfig(this, message);
	}
}
