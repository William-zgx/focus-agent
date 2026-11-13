import { useCallback, useEffect, useMemo, useRef } from "react";

interface BeginStreamRequestResult {
	requestId: string;
	controller: AbortController;
}

export function useStreamRequestRegistry() {
	const requestsRef = useRef<Map<string, BeginStreamRequestResult>>(new Map());

	useEffect(() => {
		return () => {
			for (const request of requestsRef.current.values()) {
				request.controller.abort();
			}
			requestsRef.current.clear();
		};
	}, []);

	const beginStreamRequest = useCallback(
		(threadId: string): BeginStreamRequestResult => {
			const requestId = `stream-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
			requestsRef.current.get(threadId)?.controller.abort();
			const request = { requestId, controller: new AbortController() };
			requestsRef.current.set(threadId, request);
			return request;
		},
		[],
	);

	const isCurrentStreamRequest = useCallback(
		(threadId: string, requestId: string, controller: AbortController) => {
			const current = requestsRef.current.get(threadId);
			return (
				current?.requestId === requestId &&
				current.controller === controller &&
				!controller.signal.aborted
			);
		},
		[],
	);

	const completeStreamRequest = useCallback(
		(threadId: string, requestId: string) => {
			if (requestsRef.current.get(threadId)?.requestId !== requestId) {
				return false;
			}
			requestsRef.current.delete(threadId);
			return true;
		},
		[],
	);

	const stopStreamRequest = useCallback((threadId: string) => {
		requestsRef.current.get(threadId)?.controller.abort();
		requestsRef.current.delete(threadId);
	}, []);

	const hasStreamRequest = useCallback((threadId: string) => {
		return requestsRef.current.has(threadId);
	}, []);

	return useMemo(
		() => ({
			beginStreamRequest,
			completeStreamRequest,
			hasStreamRequest,
			isCurrentStreamRequest,
			stopStreamRequest,
		}),
		[
			beginStreamRequest,
			completeStreamRequest,
			hasStreamRequest,
			isCurrentStreamRequest,
			stopStreamRequest,
		],
	);
}
