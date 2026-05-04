const AUTH_ROUTE_PATTERN = /^\/auth(?:$|[/?#])/;

export function normalizeAuthReturnTo(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return "/";
  }
  return AUTH_ROUTE_PATTERN.test(value) ? "/" : value;
}

export function appReturnToPath(returnTo: string): string {
  return `/app${returnTo.startsWith("/") ? returnTo : `/${returnTo}`}`;
}

export function appAuthPath(path: "/login" | "/register" | "" = "", returnTo?: unknown): string {
  const normalizedReturnTo = normalizeAuthReturnTo(returnTo);
  const query = new URLSearchParams({ return_to: normalizedReturnTo }).toString();
  return `/app/auth${path}${query ? `?${query}` : ""}`;
}
