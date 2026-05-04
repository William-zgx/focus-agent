export type FocusAgentUserStatus = "active" | "disabled" | "invited" | "deleted";

export interface FocusAgentUser {
  user_id: string;
  username?: string | null;
  display_name?: string | null;
  email?: string | null;
  tenant_id?: string | null;
  status: FocusAgentUserStatus | string;
  roles: string[];
  auth_provider?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  last_seen_at?: string | null;
  last_login_at?: string | null;
  password_updated_at?: string | null;
  metadata: Record<string, unknown>;
}

export interface FocusAgentRegisterRequest {
  username: string;
  password: string;
  display_name?: string | null;
  tenant_id?: string | null;
}

export interface FocusAgentLoginRequest {
  username: string;
  password: string;
}

export interface FocusAgentRefreshRequest {
  refresh_token?: string | null;
}

export interface FocusAgentChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface FocusAgentSession {
  session_id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  revoked_at?: string | null;
  last_seen_at?: string | null;
  user_agent?: string | null;
  ip_address?: string | null;
  metadata: Record<string, unknown>;
  current?: boolean;
}

export interface FocusAgentSessionListResponse {
  items: FocusAgentSession[];
  count: number;
}

export interface FocusAgentRevokeUserSessionRequest {
  session_id: string;
  reason?: string | null;
}

export interface FocusAgentAdminResetPasswordRequest {
  new_password: string;
  reason: string;
}

export interface FocusAgentAuthResponse {
  access_token: string;
  token_type?: "bearer" | string;
  refresh_token: string;
  expires_in_seconds: number;
  issuer: string;
  principal?: FocusAgentPrincipalResponse | null;
  user?: FocusAgentUser | null;
  session?: FocusAgentSession | null;
}

export interface FocusAgentDemoTokenRequest {
  user_id?: string;
  tenant_id?: string | null;
  scopes?: string[];
}

export interface FocusAgentTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
  issuer: string;
}

export interface FocusAgentPrincipalResponse {
  user_id: string;
  tenant_id?: string | null;
  scopes: string[];
  auth_enabled: boolean;
  user?: FocusAgentUser | null;
  roles?: string[];
  permissions?: string[];
  is_admin?: boolean;
}
