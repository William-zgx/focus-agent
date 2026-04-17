export const appEnv = {
  apiBaseUrl: import.meta.env.VITE_FOCUS_AGENT_API_BASE_URL || window.location.origin,
  demoUserId: import.meta.env.VITE_FOCUS_AGENT_DEMO_USER_ID || "researcher-1",
  demoTenantId: import.meta.env.VITE_FOCUS_AGENT_DEMO_TENANT_ID || "demo-tenant",
};
