import { useEffect } from "react";

export function readAdminSearchParam(key: string): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(key)?.trim() ?? "";
}

function syncParam(params: URLSearchParams, key: string, value: string) {
  const normalized = value.trim();
  if (!normalized) {
    params.delete(key);
    return;
  }
  params.set(key, normalized);
}

export function useAdminUrlSync(values: Record<string, string>) {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    for (const [key, value] of Object.entries(values)) {
      syncParam(url.searchParams, key, value);
    }
    const nextHref = `${url.pathname}${url.search}${url.hash}`;
    const currentHref = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (nextHref !== currentHref) {
      window.history.replaceState({}, "", nextHref);
    }
  }, [values]);
}
