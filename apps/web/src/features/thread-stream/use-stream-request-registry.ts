import { useEffect, useRef } from "react";

interface BeginStreamRequestResult {
  requestId: string;
  controller: AbortController;
}

export function useStreamRequestRegistry() {
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());
  const activeRequestIdsRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    return () => {
      for (const controller of abortControllersRef.current.values()) {
        controller.abort();
      }
      abortControllersRef.current.clear();
      activeRequestIdsRef.current.clear();
    };
  }, []);

  function beginStreamRequest(threadId: string): BeginStreamRequestResult {
    const requestId = `stream-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    abortControllersRef.current.get(threadId)?.abort();
    const controller = new AbortController();
    abortControllersRef.current.set(threadId, controller);
    activeRequestIdsRef.current.set(threadId, requestId);
    return { requestId, controller };
  }

  function isCurrentStreamRequest(threadId: string, requestId: string, controller: AbortController) {
    return activeRequestIdsRef.current.get(threadId) === requestId && !controller.signal.aborted;
  }

  function completeStreamRequest(threadId: string, requestId: string) {
    if (activeRequestIdsRef.current.get(threadId) !== requestId) {
      return false;
    }
    abortControllersRef.current.delete(threadId);
    activeRequestIdsRef.current.delete(threadId);
    return true;
  }

  function stopStreamRequest(threadId: string) {
    abortControllersRef.current.get(threadId)?.abort();
  }

  return {
    beginStreamRequest,
    completeStreamRequest,
    isCurrentStreamRequest,
    stopStreamRequest,
  };
}
