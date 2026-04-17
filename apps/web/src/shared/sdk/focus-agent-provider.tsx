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
  useState,
} from "react";

import { appEnv } from "@/shared/config/env";

const TOKEN_STORAGE_KEY = "focus-agent-token";

interface FocusAgentContextValue {
  client: FocusAgentClient;
  principal: FocusAgentPrincipalResponse | null;
  ready: boolean;
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

  useEffect(() => {
    let cancelled = false;

    function clearStoredToken() {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      client.setToken(undefined);
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
        client.setToken(savedToken);
      } else {
        await issueDemoToken();
      }

      let nextPrincipal: FocusAgentPrincipalResponse;
      try {
        nextPrincipal = await client.getPrincipal();
      } catch (error: unknown) {
        const shouldRetryWithFreshToken =
          Boolean(savedToken) &&
          (error instanceof FocusAgentRequestError ? error.status === 401 : true);
        if (!shouldRetryWithFreshToken) {
          throw error;
        }
        clearStoredToken();
        await issueDemoToken();
        nextPrincipal = await client.getPrincipal();
      }
      if (cancelled) return;
      setPrincipal(nextPrincipal);
      setReady(true);
    }

    void bootstrap().catch((error: unknown) => {
      console.error("Failed to bootstrap Focus Agent auth", error);
      if (!cancelled) {
        clearStoredToken();
        setReady(true);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <FocusAgentContext.Provider
      value={{
        client,
        principal,
        ready,
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
