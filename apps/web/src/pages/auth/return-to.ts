import { appEnv } from "@/shared/config/env";

const AUTH_ROUTE_PATTERN = /^\/auth(?:$|[/?#])/;
const APP_ROUTE_PATTERN = /^\/app(?:$|[/?#])/;

function appBasePrefix() {
	return appEnv.routerBasePath === "/" ? "" : appEnv.routerBasePath;
}

function joinAppPath(path: string) {
	const normalizedPath = path.startsWith("/") ? path : `/${path}`;
	const joinedPath = `${appBasePrefix()}${normalizedPath}`;
	return joinedPath || "/";
}

export function normalizeAuthReturnTo(value: unknown): string {
	if (
		typeof value !== "string" ||
		!value.startsWith("/") ||
		value.startsWith("//")
	) {
		return "/";
	}
	const appRelativeValue = APP_ROUTE_PATTERN.test(value)
		? value.replace(/^\/app(?=\/|$|[?#])/, "") || "/"
		: value;
	const normalizedValue = appRelativeValue.startsWith("/")
		? appRelativeValue
		: `/${appRelativeValue}`;
	return AUTH_ROUTE_PATTERN.test(normalizedValue) ? "/" : normalizedValue;
}

export function appReturnToPath(returnTo: string): string {
	const normalizedReturnTo = normalizeAuthReturnTo(returnTo);
	return joinAppPath(normalizedReturnTo);
}

export function appAuthPath(
	path: "/login" | "/register" | "" = "",
	returnTo?: unknown,
): string {
	const normalizedReturnTo = normalizeAuthReturnTo(returnTo);
	const query = new URLSearchParams({
		return_to: normalizedReturnTo,
	}).toString();
	return `${joinAppPath(`/auth${path}`)}${query ? `?${query}` : ""}`;
}
