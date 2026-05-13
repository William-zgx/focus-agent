import {
  FocusAgentClient,
  FocusAgentRequestError,
  type FocusAgentAuthResponse,
  type FocusAgentLoginRequest,
  type FocusAgentPrincipalResponse,
  type FocusAgentRegisterRequest,
} from "@focus-agent/web-sdk";
import {
  createContext,
  type PropsWithChildren,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { appEnv } from "@/shared/config/env";

const TOKEN_STORAGE_KEY = "focus-agent-token";

interface FocusAgentContextValue {
  client: FocusAgentClient;
  principal: FocusAgentPrincipalResponse | null;
  isAdmin: boolean;
  ready: boolean;
  authError: string | null;
  authHint: "demo_token_disabled" | "manual_token" | null;
  authenticateWithDemoUser: () => Promise<boolean>;
  authenticateWithPassword: (request: FocusAgentLoginRequest) => Promise<boolean>;
  authenticateWithToken: (token: string) => Promise<boolean>;
  registerWithPassword: (request: FocusAgentRegisterRequest) => Promise<boolean>;
  refreshPrincipal: () => Promise<boolean>;
  logout: () => Promise<void>;
  clearStoredToken: () => void;
}

const FocusAgentContext = createContext<FocusAgentContextValue | null>(null);

function isUnauthorized(error: unknown): boolean {
  return error instanceof FocusAgentRequestError && (error.status === 401 || error.status === 403);
}

function authErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof FocusAgentRequestError && error.status === 401) {
    return "The supplied credentials are invalid or expired.";
  }

  if (error instanceof FocusAgentRequestError) {
    if (typeof error.data === "object" && error.data !== null && "message" in error.data) {
      const nested = error.data as { message?: unknown };
      if (typeof nested.message === "string") {
        return nested.message;
      }
    }
    if (error.message) {
      return error.message;
    }
    if (error.code) {
      const code = String(error.code);
      if (code) {
        return code;
      }
    }
  }
  return error instanceof Error ? error.message : fallback;
}

export function FocusAgentProvider({ children }: PropsWithChildren) {
  const client = useMemo(
    () =>
      new FocusAgentClient({
        baseUrl: appEnv.apiBaseUrl,
      }),
    [],
  );
  const [principal, setPrincipal] = useState<FocusAgentPrincipalResponse | null>(null);
  const [ready, setReady] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authHint, setAuthHint] = useState<"demo_token_disabled" | "manual_token" | null>(null);
  const authAttemptRef = useRef(0);
  const isAdmin = useMemo(() => {
    if (!principal) return false;
    return Boolean(
      principal.is_admin ||
        principal.roles?.includes("admin") ||
        principal.user?.roles.includes("admin"),
    );
  }, [principal]);

  function persistToken(token: string | null | undefined) {
    const nextToken = token?.trim();
    if (nextToken) {
      client.setToken(nextToken);
      try {
        window.localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
      } catch (error) {
        console.warn("Failed to persist Focus Agent auth token", error);
      }
      return;
    }
    client.setToken(undefined);
    try {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    } catch (error) {
      console.warn("Failed to clear Focus Agent auth token", error);
    }
  }

  function readStoredToken(): string | null {
    try {
      return window.localStorage.getItem(TOKEN_STORAGE_KEY);
    } catch (error) {
      console.warn("Failed to read Focus Agent auth token", error);
      return null;
    }
  }

  async function resolvePrincipalFromAuthResponse(response?: FocusAgentAuthResponse): Promise<FocusAgentPrincipalResponse> {
    if (response?.access_token) {
      persistToken(response.access_token);
    }
    if (response?.principal) {
      return response.principal;
    }
    return client.getPrincipal();
  }

  async function acceptAuthenticatedResponse(
    authAttemptId: number,
    response?: FocusAgentAuthResponse,
  ): Promise<boolean> {
    if (authAttemptRef.current !== authAttemptId) return false;
    const nextPrincipal = await resolvePrincipalFromAuthResponse(response);
    if (authAttemptRef.current !== authAttemptId) return false;
    setPrincipal(nextPrincipal);
    setAuthError(null);
    setAuthHint(null);
    setReady(true);
    return true;
  }

  async function refreshPrincipal(): Promise<boolean> {
    const authAttemptId = ++authAttemptRef.current;
    try {
      const nextPrincipal = await client.getPrincipal();
      if (authAttemptRef.current !== authAttemptId) return false;
      setPrincipal(nextPrincipal);
      setAuthError(null);
      setAuthHint(null);
      setReady(true);
      return true;
    } catch (error: unknown) {
      if (authAttemptRef.current === authAttemptId) {
        setPrincipal(null);
        setAuthError(isUnauthorized(error) ? null : authErrorMessage(error, "Failed to refresh the current session."));
        setAuthHint("manual_token");
        setReady(true);
      }
      return false;
    }
  }

  useEffect(() => {
    let cancelled = false;
    const authAttemptId = ++authAttemptRef.current;

    function shouldApplyBootstrapResult() {
      return !cancelled && authAttemptRef.current === authAttemptId;
    }

    async function bootstrap() {
      const savedToken = readStoredToken();
      if (savedToken?.trim()) {
        client.setToken(savedToken.trim());
      }

      try {
        const nextPrincipal = await client.getPrincipal();
        if (!shouldApplyBootstrapResult()) return;
        setPrincipal(nextPrincipal);
        setAuthError(null);
        setAuthHint(null);
        setReady(true);
        return;
      } catch (error: unknown) {
        if (!isUnauthorized(error)) {
          throw error;
        }
      }

      try {
        const response = await client.refresh();
        if (!shouldApplyBootstrapResult()) return;
        const nextPrincipal = await resolvePrincipalFromAuthResponse(response);
        if (!shouldApplyBootstrapResult()) return;
        setPrincipal(nextPrincipal);
        setAuthError(null);
        setAuthHint(null);
        setReady(true);
        return;
      } catch (error: unknown) {
        if (!isUnauthorized(error)) {
          throw error;
        }
      }

      if (shouldApplyBootstrapResult()) {
        persistToken(null);
        setPrincipal(null);
        setAuthError(null);
        setAuthHint("manual_token");
        setReady(true);
      }
    }

    void bootstrap().catch((error: unknown) => {
      if (shouldApplyBootstrapResult()) {
        console.error("Failed to bootstrap Focus Agent auth", error);
        persistToken(null);
        setPrincipal(null);
        setAuthError(authErrorMessage(error, "Failed to bootstrap Focus Agent auth."));
        setAuthHint("manual_token");
        setReady(true);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [client]);

  async function authenticateWithToken(token: string): Promise<boolean> {
    const authAttemptId = ++authAttemptRef.current;
    const nextToken = token.trim();
    if (!nextToken) {
      persistToken(null);
      if (authAttemptRef.current === authAttemptId) {
        setPrincipal(null);
        setAuthError("Missing bearer token.");
        setAuthHint("manual_token");
      }
      return false;
    }
    persistToken(nextToken);
    try {
      return await acceptAuthenticatedResponse(authAttemptId);
    } catch (error: unknown) {
      persistToken(null);
      if (authAttemptRef.current === authAttemptId) {
        setPrincipal(null);
        setAuthError(authErrorMessage(error, "Failed to authenticate with bearer token."));
        setAuthHint("manual_token");
        setReady(true);
      }
      return false;
    }
  }

  async function authenticateWithPassword(request: FocusAgentLoginRequest): Promise<boolean> {
    const authAttemptId = ++authAttemptRef.current;
    try {
      const response = await client.login(request);
      return await acceptAuthenticatedResponse(authAttemptId, response);
    } catch (error: unknown) {
      persistToken(null);
      if (authAttemptRef.current === authAttemptId) {
        setPrincipal(null);
        setAuthError(authErrorMessage(error, "Failed to sign in."));
        setAuthHint("manual_token");
        setReady(true);
      }
      return false;
    }
  }

  async function registerWithPassword(request: FocusAgentRegisterRequest): Promise<boolean> {
    const authAttemptId = ++authAttemptRef.current;
    try {
      const response = await client.register(request);
      return await acceptAuthenticatedResponse(authAttemptId, response);
    } catch (error: unknown) {
      persistToken(null);
      if (authAttemptRef.current === authAttemptId) {
        setPrincipal(null);
        setAuthError(authErrorMessage(error, "Failed to register."));
        setAuthHint("manual_token");
        setReady(true);
      }
      return false;
    }
  }

  async function authenticateWithDemoUser(): Promise<boolean> {
    const authAttemptId = ++authAttemptRef.current;
    try {
      const token = await client.createDemoToken({
        user_id: appEnv.demoUserId,
        tenant_id: appEnv.demoTenantId,
        scopes: ["chat", "branches"],
      });
      if (authAttemptRef.current !== authAttemptId) {
        return false;
      }
      return authenticateWithToken(token.access_token);
    } catch (error: unknown) {
      persistToken(null);
      if (authAttemptRef.current === authAttemptId) {
        setPrincipal(null);
        setAuthError(
          error instanceof FocusAgentRequestError && error.status === 404
            ? "Demo token bootstrap is disabled. Provide an existing bearer token to continue."
            : authErrorMessage(error, "Failed to create a demo token."),
        );
        setAuthHint(
          error instanceof FocusAgentRequestError && error.status === 404
            ? "demo_token_disabled"
            : "manual_token",
        );
        setReady(true);
      }
      return false;
    }
  }

  async function logout() {
    authAttemptRef.current += 1;
    try {
      await client.logout();
    } catch (error: unknown) {
      if (!isUnauthorized(error)) {
        console.warn("Failed to close Focus Agent session", error);
      }
    }
    persistToken(null);
    setPrincipal(null);
    setAuthError(null);
    setAuthHint("manual_token");
    setReady(true);
  }

  function clearStoredTokenAndReset() {
    authAttemptRef.current += 1;
    persistToken(null);
    setPrincipal(null);
    setAuthError(null);
    setAuthHint(null);
  }

  return (
    <FocusAgentContext.Provider
      value={{
        client,
        principal,
        isAdmin,
        ready,
        authError,
        authHint,
        authenticateWithDemoUser,
        authenticateWithPassword,
        authenticateWithToken,
        registerWithPassword,
        refreshPrincipal,
        logout,
        clearStoredToken: clearStoredTokenAndReset,
      }}
    >
      {children}
    </FocusAgentContext.Provider>
  );
}

export function useFocusAgent() {
  const context = useContext(FocusAgentContext);
  if (!context) {
    throw new Error("useFocusAgent must be used within FocusAgentProvider");
  }
  return context;
}
