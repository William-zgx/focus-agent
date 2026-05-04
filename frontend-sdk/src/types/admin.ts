import type { FocusAgentUser, FocusAgentUserStatus } from "./auth.js";

export interface FocusAgentUserListRequest {
  status?: string | string[] | null;
  role?: string | string[] | null;
  tenant_id?: string | null;
  query?: string | null;
  limit?: number;
  offset?: number;
}

export interface FocusAgentUserListResponse {
  items: FocusAgentUser[];
  count: number;
  limit: number;
  offset: number;
}

export interface FocusAgentCreateUserRequest {
  user_id: string;
  username?: string | null;
  display_name?: string | null;
  email?: string | null;
  tenant_id?: string | null;
  status?: FocusAgentUserStatus | string | null;
  roles?: string[];
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentUpdateUserRequest {
  username?: string | null;
  display_name?: string | null;
  email?: string | null;
  tenant_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentUpdateUserStatusRequest {
  status: FocusAgentUserStatus | string;
  reason?: string | null;
}

export interface FocusAgentUpdateUserRolesRequest {
  roles: string[];
  reason?: string | null;
}

export interface FocusAgentAuditEvent {
  event_id: string;
  actor_user_id?: string | null;
  tenant_id?: string | null;
  action: string;
  resource_type: string;
  resource_id?: string | null;
  decision: string;
  reason?: string | null;
  metadata: Record<string, unknown>;
  request_id?: string | null;
  created_at?: string | null;
}

export interface FocusAgentAuditEventListRequest {
  actor_user_id?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  decision?: string | null;
  limit?: number;
  offset?: number;
}

export interface FocusAgentAuditEventListResponse {
  items: FocusAgentAuditEvent[];
  count: number;
  limit: number;
  offset: number;
}
