import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
	type PropsWithChildren,
	Suspense,
	lazy,
	useEffect,
	useState,
} from "react";

import { queryKeys } from "@/shared/query/query-keys";
import { FocusAgentProvider } from "@/shared/sdk/focus-agent-provider";

const STABLE_QUERY_STALE_TIME = 5 * 60_000;
const QUERY_DEVTOOLS_QUERY = "(min-width: 901px)";

const ReactQueryDevtools = import.meta.env.DEV
	? lazy(() =>
			import("@tanstack/react-query-devtools").then((module) => ({
				default: module.ReactQueryDevtools,
			})),
		)
	: null;

export function AppProviders({ children }: PropsWithChildren) {
	const [showsQueryDevtools, setShowsQueryDevtools] = useState(() =>
		typeof window === "undefined"
			? false
			: window.matchMedia(QUERY_DEVTOOLS_QUERY).matches,
	);
	const [queryClient] = useState(() => {
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
	});

	useEffect(() => {
		if (!ReactQueryDevtools) return;
		const query = window.matchMedia(QUERY_DEVTOOLS_QUERY);
		const syncQueryDevtools = () => setShowsQueryDevtools(query.matches);

		syncQueryDevtools();
		query.addEventListener("change", syncQueryDevtools);
		return () => query.removeEventListener("change", syncQueryDevtools);
	}, []);

	return (
		<QueryClientProvider client={queryClient}>
			<FocusAgentProvider>{children}</FocusAgentProvider>
			{ReactQueryDevtools && showsQueryDevtools ? (
				<Suspense fallback={null}>
					<ReactQueryDevtools
						buttonPosition="bottom-left"
						initialIsOpen={false}
					/>
				</Suspense>
			) : null}
		</QueryClientProvider>
	);
}
