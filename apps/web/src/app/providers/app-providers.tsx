import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type PropsWithChildren, Suspense, lazy, useState } from "react";

import { queryKeys } from "@/shared/query/query-keys";
import { FocusAgentProvider } from "@/shared/sdk/focus-agent-provider";

const STABLE_QUERY_STALE_TIME = 5 * 60_000;

const ReactQueryDevtools =
  import.meta.env.DEV
    ? lazy(() =>
        import("@tanstack/react-query-devtools").then((module) => ({
          default: module.ReactQueryDevtools,
        })),
      )
    : null;

export function AppProviders({ children }: PropsWithChildren) {
  const [queryClient] = useState(
    () => {
      const client = new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      });
      [
        queryKeys.models,
        queryKeys.agentRolePolicy,
        queryKeys.agentCapabilities,
        queryKeys.agentMemoryCuratorPolicy,
        queryKeys.agentDelegationPolicy,
        queryKeys.agentModelRouterPolicy,
        queryKeys.agentContextPolicy,
        queryKeys.agentTaskLedgerPolicy,
      ].forEach((queryKey) => {
        client.setQueryDefaults(queryKey, { staleTime: STABLE_QUERY_STALE_TIME });
      });
      return client;
    },
  );

  return (
    <QueryClientProvider client={queryClient}>
      <FocusAgentProvider>{children}</FocusAgentProvider>
      {ReactQueryDevtools ? (
        <Suspense fallback={null}>
          <ReactQueryDevtools initialIsOpen={false} />
        </Suspense>
      ) : null}
    </QueryClientProvider>
  );
}
