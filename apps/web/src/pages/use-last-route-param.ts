import { useRouterState } from "@tanstack/react-router";

export function useLastRouteParam(paramName: string): string | null {
	return useRouterState({
		select: (state) => {
			const routeParams = (state.matches.at(-1)?.params ?? {}) as Partial<
				Record<string, string>
			>;
			const value = routeParams[paramName];
			return value ? String(value) : null;
		},
	});
}
