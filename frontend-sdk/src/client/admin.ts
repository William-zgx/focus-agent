import { unwrapUserResponse } from "./auth.js";
import { buildAdminUserQueryString, buildAuditEventQueryString } from "./query.js";
import { applyEndpointMethods } from "./endpoint.js";
import type { EndpointClientConstructor, FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentAuditEventListRequest,
  FocusAgentAuditEventListResponse,
  FocusAgentAdminResetPasswordRequest,
  FocusAgentCreateUserRequest,
  FocusAgentRevokeUserSessionRequest,
  FocusAgentUpdateUserRequest,
  FocusAgentUpdateUserRolesRequest,
  FocusAgentUpdateUserStatusRequest,
  FocusAgentSession,
  FocusAgentSessionListResponse,
  FocusAgentUser,
  FocusAgentUserListRequest,
  FocusAgentUserListResponse,
  FocusAgentUserSessionListRequest,
} from "../types.js";

function buildUserSessionQueryString(request: FocusAgentUserSessionListRequest = {}): string {
  const params = new URLSearchParams();
  if (request.include_revoked !== undefined) {
    params.append("include_revoked", String(request.include_revoked));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function listUserSessions(
  this: FocusAgentEndpointContext,
  userId: string,
  request: FocusAgentUserSessionListRequest = {},
): Promise<FocusAgentSessionListResponse> {
  return this.requestJson<FocusAgentSessionListResponse>(
    `/v1/admin/users/${encodeURIComponent(userId)}/sessions${buildUserSessionQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function revokeUserSession(
  this: FocusAgentEndpointContext,
  userId: string,
  request: FocusAgentRevokeUserSessionRequest,
): Promise<FocusAgentSession> {
  return this.requestJson<FocusAgentSession>(
    `/v1/admin/users/${encodeURIComponent(userId)}/sessions/revoke`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function resetUserPassword(
  this: FocusAgentEndpointContext,
  userId: string,
  request: FocusAgentAdminResetPasswordRequest,
): Promise<FocusAgentUser> {
  const response = await this.requestJson<FocusAgentUser | { user?: FocusAgentUser | null }>(
    `/v1/admin/users/${encodeURIComponent(userId)}/password`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
  return unwrapUserResponse(response);
}

async function listUsers(this: FocusAgentEndpointContext, request: FocusAgentUserListRequest = {}): Promise<FocusAgentUserListResponse> {
  return this.requestJson<FocusAgentUserListResponse>(
    `/v1/admin/users${buildAdminUserQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function createUser(this: FocusAgentEndpointContext, request: FocusAgentCreateUserRequest): Promise<FocusAgentUser> {
  const response = await this.requestJson<FocusAgentUser | { user?: FocusAgentUser | null }>(
    "/v1/admin/users",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
  return unwrapUserResponse(response);
}

async function getUser(this: FocusAgentEndpointContext, userId: string): Promise<FocusAgentUser> {
  const response = await this.requestJson<FocusAgentUser | { user?: FocusAgentUser | null }>(
    `/v1/admin/users/${encodeURIComponent(userId)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
  return unwrapUserResponse(response);
}

async function updateUser(
  this: FocusAgentEndpointContext,
  userId: string,
  request: FocusAgentUpdateUserRequest,
): Promise<FocusAgentUser> {
  const response = await this.requestJson<FocusAgentUser | { user?: FocusAgentUser | null }>(
    `/v1/admin/users/${encodeURIComponent(userId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
  return unwrapUserResponse(response);
}

async function updateUserStatus(
  this: FocusAgentEndpointContext,
  userId: string,
  request: FocusAgentUpdateUserStatusRequest,
): Promise<FocusAgentUser> {
  const response = await this.requestJson<FocusAgentUser | { user?: FocusAgentUser | null }>(
    `/v1/admin/users/${encodeURIComponent(userId)}/status`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
  return unwrapUserResponse(response);
}

async function updateUserRoles(
  this: FocusAgentEndpointContext,
  userId: string,
  request: FocusAgentUpdateUserRolesRequest,
): Promise<FocusAgentUser> {
  const response = await this.requestJson<FocusAgentUser | { user?: FocusAgentUser | null }>(
    `/v1/admin/users/${encodeURIComponent(userId)}/roles`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
  return unwrapUserResponse(response);
}

async function listAuditEvents(
  this: FocusAgentEndpointContext,
  request: FocusAgentAuditEventListRequest = {},
): Promise<FocusAgentAuditEventListResponse> {
  return this.requestJson<FocusAgentAuditEventListResponse>(
    `/v1/admin/audit-events${buildAuditEventQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

export interface AdminEndpoints {
  listUserSessions: OmitThisParameter<typeof listUserSessions>;
  revokeUserSession: OmitThisParameter<typeof revokeUserSession>;
  resetUserPassword: OmitThisParameter<typeof resetUserPassword>;
  listUsers: OmitThisParameter<typeof listUsers>;
  createUser: OmitThisParameter<typeof createUser>;
  getUser: OmitThisParameter<typeof getUser>;
  updateUser: OmitThisParameter<typeof updateUser>;
  updateUserStatus: OmitThisParameter<typeof updateUserStatus>;
  updateUserRoles: OmitThisParameter<typeof updateUserRoles>;
  listAuditEvents: OmitThisParameter<typeof listAuditEvents>;
}

const adminEndpoints: FocusAgentEndpointMethodMap<AdminEndpoints> = {
  listUserSessions,
  revokeUserSession,
  resetUserPassword,
  listUsers,
  createUser,
  getUser,
  updateUser,
  updateUserStatus,
  updateUserRoles,
  listAuditEvents,
};

export function applyAdminEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, adminEndpoints);
}
