import { applyEndpointMethods } from "./endpoint";
import type { EndpointClientConstructor, FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint";
import type {
  FocusAgentAuthResponse,
  FocusAgentChangePasswordRequest,
  FocusAgentDemoTokenRequest,
  FocusAgentPrincipalResponse,
  FocusAgentLoginRequest,
  FocusAgentRefreshRequest,
  FocusAgentRegisterRequest,
  FocusAgentTokenResponse,
  FocusAgentSession,
  FocusAgentSessionListResponse,
  FocusAgentUser,
} from "../types";

async function register(this: FocusAgentEndpointContext, request: FocusAgentRegisterRequest): Promise<FocusAgentAuthResponse> {
  return this.requestJson<FocusAgentAuthResponse>("/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, false);
}

async function login(this: FocusAgentEndpointContext, request: FocusAgentLoginRequest): Promise<FocusAgentAuthResponse> {
  return this.requestJson<FocusAgentAuthResponse>("/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, false);
}

async function logout(this: FocusAgentEndpointContext): Promise<void> {
  await this.requestJson<void>("/v1/auth/logout", {
    method: "POST",
    headers: {},
  }, true);
  this.setToken(undefined);
}

async function refresh(this: FocusAgentEndpointContext, request: FocusAgentRefreshRequest = {}): Promise<FocusAgentAuthResponse> {
  return this.requestJson<FocusAgentAuthResponse>("/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function changePassword(this: FocusAgentEndpointContext, request: FocusAgentChangePasswordRequest): Promise<void> {
  await this.requestJson<void>("/v1/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
}

async function listMySessions(this: FocusAgentEndpointContext): Promise<FocusAgentSessionListResponse> {
  const response = await this.requestJson<FocusAgentSessionListResponse & { sessions?: FocusAgentSession[] }>(
    "/v1/auth/sessions",
    {
      method: "GET",
      headers: {},
    },
    true,
  );
  const items = response.items ?? response.sessions ?? [];
  return { items, count: response.count ?? items.length };
}

async function revokeSession(this: FocusAgentEndpointContext, sessionId: string): Promise<FocusAgentSession | void> {
  return this.requestJson<FocusAgentSession | void>(
    `/v1/auth/sessions/${encodeURIComponent(sessionId)}/revoke`,
    {
      method: "POST",
      headers: {},
    },
    true,
  );
}

async function createDemoToken(this: FocusAgentEndpointContext, request: FocusAgentDemoTokenRequest = {}): Promise<FocusAgentTokenResponse> {
  return this.requestJson<FocusAgentTokenResponse>("/v1/auth/demo-token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, false);
}

async function getPrincipal(this: FocusAgentEndpointContext): Promise<FocusAgentPrincipalResponse> {
  return this.requestJson<FocusAgentPrincipalResponse>("/v1/auth/me", {
    method: "GET",
    headers: {},
  }, true);
}

export function unwrapUserResponse(response: FocusAgentUser | { user?: FocusAgentUser | null }): FocusAgentUser {
  if ("user" in response && response.user) {
    return response.user;
  }
  return response as FocusAgentUser;
}

export interface AuthEndpoints {
  register: OmitThisParameter<typeof register>;
  login: OmitThisParameter<typeof login>;
  logout: OmitThisParameter<typeof logout>;
  refresh: OmitThisParameter<typeof refresh>;
  changePassword: OmitThisParameter<typeof changePassword>;
  listMySessions: OmitThisParameter<typeof listMySessions>;
  revokeSession: OmitThisParameter<typeof revokeSession>;
  createDemoToken: OmitThisParameter<typeof createDemoToken>;
  getPrincipal: OmitThisParameter<typeof getPrincipal>;
}

const authEndpoints: FocusAgentEndpointMethodMap<AuthEndpoints> = {
  register,
  login,
  logout,
  refresh,
  changePassword,
  listMySessions,
  revokeSession,
  createDemoToken,
  getPrincipal,
};

export function applyAuthEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, authEndpoints);
}
