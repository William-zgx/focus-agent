import { useRouterState } from "@tanstack/react-router";

export function useLastRouteParam(paramName: string): string | null {
	return useRouterState({
		select: (state) => {
			const lastMatch = state.matches[state.matches.length - 1];
			const routeParams = (lastMatch?.params ?? {}) as Partial<
				Record<string, string>
			>;
			const value = routeParams[paramName];
			return value ? String(value) : null;
		},
	});
}
