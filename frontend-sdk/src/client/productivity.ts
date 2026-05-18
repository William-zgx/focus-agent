import { appendQueryValue } from "./query.js";
import { applyEndpointMethods } from "./endpoint.js";
import type {
  EndpointClientConstructor,
  FocusAgentEndpointContext,
  FocusAgentEndpointMethodMap,
} from "./endpoint.js";
import type {
  FocusAgentCreateNoteRequest,
  FocusAgentCreateTaskRequest,
  FocusAgentCaptureNoteRequest,
  FocusAgentCaptureTaskRequest,
  FocusAgentListNotesRequest,
  FocusAgentListTasksRequest,
  FocusAgentNoteListResponse,
  FocusAgentNoteResponse,
  FocusAgentTaskEventListResponse,
  FocusAgentTaskListResponse,
  FocusAgentTaskResponse,
  FocusAgentUpdateNoteRequest,
  FocusAgentUpdateTaskRequest,
} from "../types.js";

function buildNotesQuery(request: FocusAgentListNotesRequest = {}): string {
  const params = new URLSearchParams();
  appendQueryValue(params, "q", request.q);
  appendQueryValue(params, "tag", request.tag);
  appendQueryValue(params, "source_kind", request.source_kind);
  appendQueryValue(params, "include_archived", request.include_archived);
  appendQueryValue(params, "limit", request.limit);
  appendQueryValue(params, "offset", request.offset);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function buildTasksQuery(request: FocusAgentListTasksRequest = {}): string {
  const params = new URLSearchParams();
  appendQueryValue(params, "status", request.status);
  appendQueryValue(params, "source_kind", request.source_kind);
  appendQueryValue(params, "include_archived", request.include_archived);
  appendQueryValue(params, "limit", request.limit);
  appendQueryValue(params, "offset", request.offset);
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function listNotes(
  this: FocusAgentEndpointContext,
  request: FocusAgentListNotesRequest = {},
): Promise<FocusAgentNoteListResponse> {
  return this.requestJson<FocusAgentNoteListResponse>(`/v1/notes${buildNotesQuery(request)}`, {
    method: "GET",
    headers: {},
  }, true);
}

async function createNote(
  this: FocusAgentEndpointContext,
  request: FocusAgentCreateNoteRequest,
): Promise<FocusAgentNoteResponse> {
  return this.requestJson<FocusAgentNoteResponse>("/v1/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function getNote(this: FocusAgentEndpointContext, noteId: string): Promise<FocusAgentNoteResponse> {
  return this.requestJson<FocusAgentNoteResponse>(`/v1/notes/${encodeURIComponent(noteId)}`, {
    method: "GET",
    headers: {},
  }, true);
}

async function updateNote(
  this: FocusAgentEndpointContext,
  noteId: string,
  request: FocusAgentUpdateNoteRequest,
): Promise<FocusAgentNoteResponse> {
  return this.requestJson<FocusAgentNoteResponse>(`/v1/notes/${encodeURIComponent(noteId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function listTasks(
  this: FocusAgentEndpointContext,
  request: FocusAgentListTasksRequest = {},
): Promise<FocusAgentTaskListResponse> {
  return this.requestJson<FocusAgentTaskListResponse>(`/v1/tasks${buildTasksQuery(request)}`, {
    method: "GET",
    headers: {},
  }, true);
}

async function createTask(
  this: FocusAgentEndpointContext,
  request: FocusAgentCreateTaskRequest,
): Promise<FocusAgentTaskResponse> {
  return this.requestJson<FocusAgentTaskResponse>("/v1/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function updateTask(
  this: FocusAgentEndpointContext,
  taskId: string,
  request: FocusAgentUpdateTaskRequest,
): Promise<FocusAgentTaskResponse> {
  return this.requestJson<FocusAgentTaskResponse>(`/v1/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function completeTask(this: FocusAgentEndpointContext, taskId: string): Promise<FocusAgentTaskResponse> {
  return this.requestJson<FocusAgentTaskResponse>(`/v1/tasks/${encodeURIComponent(taskId)}/complete`, {
    method: "POST",
    headers: {},
  }, true);
}

async function archiveTask(this: FocusAgentEndpointContext, taskId: string): Promise<FocusAgentTaskResponse> {
  return this.requestJson<FocusAgentTaskResponse>(`/v1/tasks/${encodeURIComponent(taskId)}/archive`, {
    method: "POST",
    headers: {},
  }, true);
}

async function listTaskEvents(
  this: FocusAgentEndpointContext,
  taskId: string,
): Promise<FocusAgentTaskEventListResponse> {
  return this.requestJson<FocusAgentTaskEventListResponse>(
    `/v1/tasks/${encodeURIComponent(taskId)}/events`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function captureNote(
  this: FocusAgentEndpointContext,
  request: FocusAgentCaptureNoteRequest,
): Promise<FocusAgentNoteResponse> {
  return this.requestJson<FocusAgentNoteResponse>("/v1/productivity/capture/note", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function captureTask(
  this: FocusAgentEndpointContext,
  request: FocusAgentCaptureTaskRequest,
): Promise<FocusAgentTaskResponse> {
  return this.requestJson<FocusAgentTaskResponse>("/v1/productivity/capture/task", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

export interface ProductivityEndpoints {
  listNotes: OmitThisParameter<typeof listNotes>;
  createNote: OmitThisParameter<typeof createNote>;
  getNote: OmitThisParameter<typeof getNote>;
  updateNote: OmitThisParameter<typeof updateNote>;
  listTasks: OmitThisParameter<typeof listTasks>;
  createTask: OmitThisParameter<typeof createTask>;
  updateTask: OmitThisParameter<typeof updateTask>;
  completeTask: OmitThisParameter<typeof completeTask>;
  archiveTask: OmitThisParameter<typeof archiveTask>;
  listTaskEvents: OmitThisParameter<typeof listTaskEvents>;
  captureNote: OmitThisParameter<typeof captureNote>;
  captureTask: OmitThisParameter<typeof captureTask>;
}

const productivityEndpoints: FocusAgentEndpointMethodMap<ProductivityEndpoints> = {
  listNotes,
  createNote,
  getNote,
  updateNote,
  listTasks,
  createTask,
  updateTask,
  completeTask,
  archiveTask,
  listTaskEvents,
  captureNote,
  captureTask,
};

export function applyProductivityEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, productivityEndpoints);
}
