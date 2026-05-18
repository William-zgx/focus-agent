import { applyEndpointMethods } from "./endpoint.js";
import type { EndpointClientConstructor, FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentApplyMergeDecisionRequest,
  FocusAgentApplyMergeDecisionResponse,
  FocusAgentBranchActionExecuteResponse,
  FocusAgentBranchRecord,
  FocusAgentConversationListResponse,
  FocusAgentConversationSummary,
  FocusAgentCreateConversationRequest,
  FocusAgentForkBranchRequest,
  FocusAgentRenameBranchRequest,
  FocusAgentUpdateConversationRequest,
  BranchTreeResponse,
  ThreadStateResponse,
  ThreadContextCompactRequest,
  ThreadContextCompactResponse,
  ThreadContextPreviewRequest,
  ThreadContextPreviewResponse,
  ThreadResolution,
} from "../types.js";

async function listConversations(this: FocusAgentEndpointContext): Promise<FocusAgentConversationListResponse> {
  return this.requestJson<FocusAgentConversationListResponse>("/v1/conversations", {
    method: "GET",
    headers: {},
  }, true);
}

async function createConversation(
  this: FocusAgentEndpointContext,
  request: FocusAgentCreateConversationRequest = {},
): Promise<FocusAgentConversationSummary> {
  return this.requestJson<FocusAgentConversationSummary>("/v1/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function renameConversation(
  this: FocusAgentEndpointContext,
  rootThreadId: string,
  request: FocusAgentUpdateConversationRequest,
): Promise<FocusAgentConversationSummary> {
  return this.requestJson<FocusAgentConversationSummary>(
    `/v1/conversations/${encodeURIComponent(rootThreadId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function archiveConversation(this: FocusAgentEndpointContext, rootThreadId: string): Promise<FocusAgentConversationSummary> {
  return this.requestJson<FocusAgentConversationSummary>(
    `/v1/conversations/${encodeURIComponent(rootThreadId)}/archive`,
    {
      method: "POST",
      headers: {},
    },
    true,
  );
}

async function activateConversation(this: FocusAgentEndpointContext, rootThreadId: string): Promise<FocusAgentConversationSummary> {
  return this.requestJson<FocusAgentConversationSummary>(
    `/v1/conversations/${encodeURIComponent(rootThreadId)}/activate`,
    {
      method: "POST",
      headers: {},
    },
    true,
  );
}

async function getThreadState(this: FocusAgentEndpointContext, threadId: string): Promise<ThreadStateResponse> {
  return this.requestJson<ThreadStateResponse>(`/v1/threads/${encodeURIComponent(threadId)}`, {
    method: "GET",
    headers: {},
  }, true);
}

async function getThreadResolution(this: FocusAgentEndpointContext, threadId: string): Promise<ThreadResolution> {
  return this.requestJson<ThreadResolution>(`/v1/threads/${encodeURIComponent(threadId)}/resolution`, {
    method: "GET",
    headers: {},
  }, true);
}

async function previewThreadContext(
  this: FocusAgentEndpointContext,
  threadId: string,
  request: ThreadContextPreviewRequest = {},
): Promise<ThreadContextPreviewResponse> {
  return this.requestJson<ThreadContextPreviewResponse>(
    `/v1/threads/${encodeURIComponent(threadId)}/context/preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function compactThreadContext(
  this: FocusAgentEndpointContext,
  threadId: string,
  request: ThreadContextCompactRequest = {},
): Promise<ThreadContextCompactResponse> {
  return this.requestJson<ThreadContextCompactResponse>(
    `/v1/threads/${encodeURIComponent(threadId)}/context/compact`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function executeBranchAction(
  this: FocusAgentEndpointContext,
  threadId: string,
  actionId: string,
): Promise<FocusAgentBranchActionExecuteResponse> {
  return this.requestJson<FocusAgentBranchActionExecuteResponse>(
    `/v1/threads/${encodeURIComponent(threadId)}/branch-actions/${encodeURIComponent(actionId)}/execute`,
    {
      method: "POST",
      headers: {},
    },
    true,
  );
}

async function dismissBranchAction(
  this: FocusAgentEndpointContext,
  threadId: string,
  actionId: string,
): Promise<ThreadStateResponse> {
  return this.requestJson<ThreadStateResponse>(
    `/v1/threads/${encodeURIComponent(threadId)}/branch-actions/${encodeURIComponent(actionId)}/dismiss`,
    {
      method: "POST",
      headers: {},
    },
    true,
  );
}

async function getBranchTree(this: FocusAgentEndpointContext, threadId: string): Promise<BranchTreeResponse> {
  return this.requestJson<BranchTreeResponse>(`/v1/branches/tree/${encodeURIComponent(threadId)}`, {
    method: "GET",
    headers: {},
  }, true);
}

async function forkBranch(this: FocusAgentEndpointContext, request: FocusAgentForkBranchRequest): Promise<FocusAgentBranchRecord> {
  return this.requestJson<FocusAgentBranchRecord>("/v1/branches/fork", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function archiveBranch(this: FocusAgentEndpointContext, threadId: string): Promise<FocusAgentBranchRecord> {
  return this.requestJson<FocusAgentBranchRecord>(`/v1/branches/${encodeURIComponent(threadId)}/archive`, {
    method: "POST",
    headers: {},
  }, true);
}

async function activateBranch(this: FocusAgentEndpointContext, threadId: string): Promise<FocusAgentBranchRecord> {
  return this.requestJson<FocusAgentBranchRecord>(`/v1/branches/${encodeURIComponent(threadId)}/activate`, {
    method: "POST",
    headers: {},
  }, true);
}

async function renameBranch(this: FocusAgentEndpointContext, threadId: string, request: FocusAgentRenameBranchRequest): Promise<FocusAgentBranchRecord> {
  return this.requestJson<FocusAgentBranchRecord>(`/v1/branches/${encodeURIComponent(threadId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function prepareMergeProposal(this: FocusAgentEndpointContext, threadId: string): Promise<ThreadStateResponse["merge_proposal"]> {
  return this.requestJson<ThreadStateResponse["merge_proposal"]>(
    `/v1/branches/${encodeURIComponent(threadId)}/proposal`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    },
    true,
  );
}

async function applyMergeDecision(
  this: FocusAgentEndpointContext,
  threadId: string,
  request: FocusAgentApplyMergeDecisionRequest,
): Promise<FocusAgentApplyMergeDecisionResponse> {
  return this.requestJson<FocusAgentApplyMergeDecisionResponse>(
    `/v1/branches/${encodeURIComponent(threadId)}/merge`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

export interface ThreadBranchEndpoints {
  listConversations: OmitThisParameter<typeof listConversations>;
  createConversation: OmitThisParameter<typeof createConversation>;
  renameConversation: OmitThisParameter<typeof renameConversation>;
  archiveConversation: OmitThisParameter<typeof archiveConversation>;
  activateConversation: OmitThisParameter<typeof activateConversation>;
  getThreadState: OmitThisParameter<typeof getThreadState>;
  getThreadResolution: OmitThisParameter<typeof getThreadResolution>;
  previewThreadContext: OmitThisParameter<typeof previewThreadContext>;
  compactThreadContext: OmitThisParameter<typeof compactThreadContext>;
  executeBranchAction: OmitThisParameter<typeof executeBranchAction>;
  dismissBranchAction: OmitThisParameter<typeof dismissBranchAction>;
  getBranchTree: OmitThisParameter<typeof getBranchTree>;
  forkBranch: OmitThisParameter<typeof forkBranch>;
  archiveBranch: OmitThisParameter<typeof archiveBranch>;
  activateBranch: OmitThisParameter<typeof activateBranch>;
  renameBranch: OmitThisParameter<typeof renameBranch>;
  prepareMergeProposal: OmitThisParameter<typeof prepareMergeProposal>;
  applyMergeDecision: OmitThisParameter<typeof applyMergeDecision>;
}

const threadBranchEndpoints: FocusAgentEndpointMethodMap<ThreadBranchEndpoints> = {
  listConversations,
  createConversation,
  renameConversation,
  archiveConversation,
  activateConversation,
  getThreadState,
  getThreadResolution,
  previewThreadContext,
  compactThreadContext,
  executeBranchAction,
  dismissBranchAction,
  getBranchTree,
  forkBranch,
  archiveBranch,
  activateBranch,
  renameBranch,
  prepareMergeProposal,
  applyMergeDecision,
};

export function applyThreadBranchEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, threadBranchEndpoints);
}
