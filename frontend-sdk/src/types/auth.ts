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
}
