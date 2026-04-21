import {
  FocusAgentClient,
  FocusAgentRequestError,
  type FocusAgentPrincipalResponse,
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
  ready: boolean;
  authError: string | null;
  authHint: "demo_token_disabled" | "manual_token" | null;
  authenticateWithToken: (token: string) => Promise<boolean>;
  clearStoredToken: () => void;
}

const FocusAgentContext = createContext<FocusAgentContextValue | null>(null);

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

  useEffect(() => {
    let cancelled = false;

    function clearStoredToken() {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      client.setToken(undefined);
    }

    async function authenticateStoredToken(
      token: string,
      { persist }: { persist: boolean },
    ): Promise<boolean> {
      const authAttemptId = ++authAttemptRef.current;
      const nextToken = token.trim();
      if (!nextToken) {
        clearStoredToken();
        if (!cancelled && authAttemptRef.current === authAttemptId) {
          setPrincipal(null);
          setAuthError("Missing bearer token.");
          setAuthHint("manual_token");
        }
        return false;
      }
      client.setToken(nextToken);
      try {
        const nextPrincipal = await client.getPrincipal();
        if (cancelled || authAttemptRef.current != authAttemptId) return false;
        if (persist) {
          window.localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
        }
        setPrincipal(nextPrincipal);
        setAuthError(null);
        setAuthHint(null);
        return true;
      } catch (error: unknown) {
        clearStoredToken();
        if (!cancelled && authAttemptRef.current === authAttemptId) {
          setPrincipal(null);
          setAuthError(
            error instanceof FocusAgentRequestError && error.status === 401
                ? "Bearer token is invalid or expired."
                : error instanceof Error
                  ? error.message
                  : "Failed to authenticate with bearer token.",
          );
          setAuthHint("manual_token");
        }
        return false;
      }
    }

    async function issueDemoToken() {
      const token = await client.createDemoToken({
        user_id: appEnv.demoUserId,
        tenant_id: appEnv.demoTenantId,
        scopes: ["chat", "branches"],
      });
      if (cancelled) return null;
      window.localStorage.setItem(TOKEN_STORAGE_KEY, token.access_token);
      client.setToken(token.access_token);
      return token.access_token;
    }

    async function bootstrap() {
      const savedToken = window.localStorage.getItem(TOKEN_STORAGE_KEY);
      if (savedToken) {
        const authenticated = await authenticateStoredToken(savedToken, { persist: true });
        if (authenticated) {
          setReady(true);
          return;
        }
      }

      try {
        const nextPrincipal = await client.getPrincipal();
        if (cancelled) return;
        setPrincipal(nextPrincipal);
        setAuthError(null);
        setReady(true);
        return;
      } catch (error: unknown) {
        const status = error instanceof FocusAgentRequestError ? error.status : null;
        if (status !== 401 && status !== 403) {
          throw error;
        }
      }

      try {
        const token = await issueDemoToken();
        if (!token || cancelled) return;
        const authenticated = await authenticateStoredToken(token, { persist: true });
        if (!cancelled) {
          setReady(true);
        }
      } catch (error: unknown) {
        clearStoredToken();
        if (!cancelled) {
          setPrincipal(null);
          setAuthError(
            error instanceof FocusAgentRequestError && error.status === 404
              ? "Demo token bootstrap is disabled. Provide an existing bearer token to continue."
              : error instanceof Error
                ? error.message
                : "Failed to bootstrap Focus Agent auth.",
          );
          setAuthHint(
            error instanceof FocusAgentRequestError && error.status === 404
              ? "demo_token_disabled"
              : "manual_token",
          );
          setReady(true);
        }
      }
    }

    void bootstrap().catch((error: unknown) => {
      console.error("Failed to bootstrap Focus Agent auth", error);
      if (!cancelled) {
        clearStoredToken();
        setPrincipal(null);
        setAuthError(error instanceof Error ? error.message : "Failed to bootstrap Focus Agent auth.");
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
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      client.setToken(undefined);
      if (authAttemptRef.current === authAttemptId) {
        setPrincipal(null);
        setAuthError("Missing bearer token.");
        setAuthHint("manual_token");
      }
      return false;
    }
    client.setToken(nextToken);
    try {
      const nextPrincipal = await client.getPrincipal();
      if (authAttemptRef.current != authAttemptId) {
        return false;
      }
      window.localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
      setPrincipal(nextPrincipal);
      setAuthError(null);
      setAuthHint(null);
      setReady(true);
      return true;
    } catch (error: unknown) {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      client.setToken(undefined);
      if (authAttemptRef.current === authAttemptId) {
        setPrincipal(null);
        setAuthError(
          error instanceof FocusAgentRequestError && error.status === 401
            ? "Bearer token is invalid or expired."
            : error instanceof Error
              ? error.message
              : "Failed to authenticate with bearer token.",
        );
        setAuthHint("manual_token");
        setReady(true);
      }
      return false;
    }
  }

  function clearStoredTokenAndReset() {
    authAttemptRef.current += 1;
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    client.setToken(undefined);
    setPrincipal(null);
    setAuthError(null);
    setAuthHint(null);
  }

  return (
    <FocusAgentContext.Provider
      value={{
        client,
        principal,
        ready,
        authError,
        authHint,
        authenticateWithToken,
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
