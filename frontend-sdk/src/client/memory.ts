import { appendQueryValue } from "./query.js";
import { applyEndpointMethods } from "./endpoint.js";
import type { EndpointClientConstructor, FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentForgetMemoryRequest,
  FocusAgentForgetMemoryResponse,
  FocusAgentMemoryAuditEventListRequest,
  FocusAgentMemoryAuditEventListResponse,
  FocusAgentMemoryCandidateListRequest,
  FocusAgentMemoryCandidateListResponse,
  FocusAgentMemoryDetailResponse,
  FocusAgentMemoryListRequest,
  FocusAgentMemoryListResponse,
  FocusAgentMemoryRecord,
} from "../types.js";

function buildMemoryListQueryString(request: FocusAgentMemoryListRequest = {}): string {
  const params = new URLSearchParams();
  appendQueryValue(params, "namespace", request.namespace);
  appendQueryValue(params, "kind", request.kind);
  appendQueryValue(params, "scope", request.scope);
  appendQueryValue(params, "visibility", request.visibility);
  appendQueryValue(params, "status", request.status);
  appendQueryValue(params, "user_id", request.user_id);
  appendQueryValue(params, "root_thread_id", request.root_thread_id);
  appendQueryValue(params, "source_thread_id", request.source_thread_id);
  appendQueryValue(params, "source_branch_id", request.source_branch_id);
  appendQueryValue(params, "limit", request.limit);
  appendQueryValue(params, "offset", request.offset);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function buildMemoryAuditQueryString(request: FocusAgentMemoryAuditEventListRequest = {}): string {
  const params = new URLSearchParams();
  appendQueryValue(params, "memory_id", request.memory_id);
  appendQueryValue(params, "limit", request.limit);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function buildMemoryCandidateQueryString(request: FocusAgentMemoryCandidateListRequest = {}): string {
  const params = new URLSearchParams();
  appendQueryValue(params, "status", request.status);
  appendQueryValue(params, "root_thread_id", request.root_thread_id);
  appendQueryValue(params, "limit", request.limit);
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function listMemoryRecords(
  this: FocusAgentEndpointContext,
  request: FocusAgentMemoryListRequest = {},
): Promise<FocusAgentMemoryListResponse> {
  return this.requestJson<FocusAgentMemoryListResponse>(
    `/v1/memory${buildMemoryListQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function getMemoryRecord(this: FocusAgentEndpointContext, memoryId: string): Promise<FocusAgentMemoryRecord | null> {
  const response = await this.requestJson<FocusAgentMemoryDetailResponse>(
    `/v1/memory/${encodeURIComponent(memoryId)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
  return response.item ?? null;
}

async function listMemoryAuditEvents(
  this: FocusAgentEndpointContext,
  request: FocusAgentMemoryAuditEventListRequest = {},
): Promise<FocusAgentMemoryAuditEventListResponse> {
  return this.requestJson<FocusAgentMemoryAuditEventListResponse>(
    `/v1/memory/audit${buildMemoryAuditQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function listMemoryRecordAuditEvents(
  this: FocusAgentEndpointContext,
  memoryId: string,
  request: Omit<FocusAgentMemoryAuditEventListRequest, "memory_id"> = {},
): Promise<FocusAgentMemoryAuditEventListResponse> {
  return this.requestJson<FocusAgentMemoryAuditEventListResponse>(
    `/v1/memory/${encodeURIComponent(memoryId)}/audit${buildMemoryAuditQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function forgetMemoryRecord(
  this: FocusAgentEndpointContext,
  memoryId: string,
  request: FocusAgentForgetMemoryRequest = {},
): Promise<FocusAgentForgetMemoryResponse> {
  return this.requestJson<FocusAgentForgetMemoryResponse>(
    `/v1/memory/${encodeURIComponent(memoryId)}/forget`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function listMemoryCandidates(
  this: FocusAgentEndpointContext,
  request: FocusAgentMemoryCandidateListRequest = {},
): Promise<FocusAgentMemoryCandidateListResponse> {
  return this.requestJson<FocusAgentMemoryCandidateListResponse>(
    `/v1/memory/candidates${buildMemoryCandidateQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

export interface MemoryEndpoints {
  listMemoryRecords: OmitThisParameter<typeof listMemoryRecords>;
  getMemoryRecord: OmitThisParameter<typeof getMemoryRecord>;
  listMemoryAuditEvents: OmitThisParameter<typeof listMemoryAuditEvents>;
  listMemoryRecordAuditEvents: OmitThisParameter<typeof listMemoryRecordAuditEvents>;
  forgetMemoryRecord: OmitThisParameter<typeof forgetMemoryRecord>;
  listMemoryCandidates: OmitThisParameter<typeof listMemoryCandidates>;
}

const memoryEndpoints: FocusAgentEndpointMethodMap<MemoryEndpoints> = {
  listMemoryRecords,
  getMemoryRecord,
  listMemoryAuditEvents,
  listMemoryRecordAuditEvents,
  forgetMemoryRecord,
  listMemoryCandidates,
};

export function applyMemoryEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, memoryEndpoints);
}
