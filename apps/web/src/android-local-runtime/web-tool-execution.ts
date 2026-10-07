import type { FocusAgentEvent } from "@focus-agent/web-sdk";
import { nowIso } from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import { abortIfRequested } from "./model-provider";
import type {
	LocalRuntimeState,
	LocalWebFetchResult,
	LocalWebSearchResult,
	LocalWebSearchTimeRange,
} from "./types";
import { runLocalWebFetch } from "./web-fetch";
import { runLocalWebSearch } from "./web-search";

type LocalThreadMessage =
	LocalRuntimeState["threads"][string]["messages"][number];

export interface LocalWebToolRunContext {
	ctx: LocalFocusAgentRuntime;
	baseData: { run_id: string; thread_id: string };
	runSignal: AbortSignal;
	send: (event: FocusAgentEvent) => void;
	appendRunMessage: (runMessage: LocalThreadMessage) => void;
}

export interface LocalWebToolResults {
	webFetchResult: LocalWebFetchResult | null;
	webSearchResult: LocalWebSearchResult | null;
}

export async function executeLocalWebFetch(
	run: LocalWebToolRunContext,
	targetUrl: string,
	args: Record<string, unknown>,
	callId: string,
	sequence: number,
): Promise<LocalWebFetchResult | null> {
	const { ctx, baseData, runSignal, send, appendRunMessage } = run;
	send({
		id: `${callId}:call-delta`,
		event: "tool.call.delta",
		data: {
			...baseData,
			sequence,
			id: callId,
			name: "web_fetch",
			tool_call_id: callId,
			args_delta: JSON.stringify(args),
			raw: { id: callId, name: "web_fetch", args },
		},
	});
	send({
		id: `${callId}:requested`,
		event: "tool.requested",
		data: {
			...baseData,
			sequence,
			node: "android-local-runtime",
			tool_name: "web_fetch",
			tool_call_id: callId,
			args,
		},
	});
	appendRunMessage({
		id: ctx.nextId("message", "local-message"),
		type: "ai",
		content: "",
		created_at: nowIso(),
		tool_calls: [
			{
				id: callId,
				name: "web_fetch",
				args,
				function: {
					name: "web_fetch",
					arguments: JSON.stringify(args),
				},
			},
		],
	});
	try {
		const result = await runLocalWebFetch(
			targetUrl,
			runSignal,
			typeof args.max_chars === "number" ? args.max_chars : undefined,
			typeof args.offset === "number" ? args.offset : 0,
		);
		appendRunMessage({
			id: ctx.nextId("message", "local-message"),
			type: "tool",
			content: JSON.stringify(result),
			created_at: nowIso(),
			name: "web_fetch",
			status: "completed",
			tool_call_id: callId,
		});
		send({
			id: `${callId}:result`,
			event: "tool.result",
			data: {
				...baseData,
				sequence: sequence + 1,
				tool_name: "web_fetch",
				tool_call_id: callId,
				message: result.title || `web_fetch completed for ${targetUrl}`,
				output: result,
			},
		});
		return result;
	} catch (error) {
		abortIfRequested(runSignal);
		const messageText = error instanceof Error ? error.message : String(error);
		appendRunMessage({
			id: ctx.nextId("message", "local-message"),
			type: "tool",
			content: JSON.stringify({ error: messageText, url: targetUrl }),
			created_at: nowIso(),
			name: "web_fetch",
			status: "failed",
			tool_call_id: callId,
		});
		send({
			id: `${callId}:error`,
			event: "tool.error",
			data: {
				...baseData,
				sequence: sequence + 1,
				tool_name: "web_fetch",
				tool_call_id: callId,
				message: messageText,
				output: { error: messageText, url: targetUrl },
			},
		});
		return null;
	}
}

export async function executeLocalWebSearch(
	run: LocalWebToolRunContext,
	results: LocalWebToolResults,
	webSearchQueryText: string,
	webSearchArgs: Record<string, unknown>,
	webSearchTimeRangeValue: LocalWebSearchTimeRange | null,
	currentUtcTimeResult: string | null,
): Promise<void> {
	const { ctx, baseData, runSignal, send, appendRunMessage } = run;
	const runId = baseData.run_id;
	const webSearchCallId = `${runId}:web-search`;
	send({
		id: `${runId}:tool-call-delta`,
		event: "tool.call.delta",
		data: {
			...baseData,
			sequence: 4,
			id: webSearchCallId,
			name: "web_search",
			tool_call_id: webSearchCallId,
			args_delta: JSON.stringify(webSearchArgs),
			raw: {
				id: webSearchCallId,
				name: "web_search",
				args: webSearchArgs,
			},
		},
	});
	send({
		id: `${runId}:tool-requested`,
		event: "tool.requested",
		data: {
			...baseData,
			sequence: 4,
			node: "android-local-runtime",
			tool_name: "web_search",
			tool_call_id: webSearchCallId,
			args: webSearchArgs,
		},
	});
	appendRunMessage({
		id: ctx.nextId("message", "local-message"),
		type: "ai",
		content: "",
		created_at: nowIso(),
		tool_calls: [
			{
				id: webSearchCallId,
				name: "web_search",
				args: webSearchArgs,
				function: {
					name: "web_search",
					arguments: JSON.stringify(webSearchArgs),
				},
			},
		],
	});
	try {
		results.webSearchResult = await runLocalWebSearch(
			webSearchQueryText,
			runSignal,
			{
				time_range: webSearchTimeRangeValue,
				observed_at: currentUtcTimeResult ?? nowIso(),
			},
		);
		const webSearchResult = results.webSearchResult;
		appendRunMessage({
			id: ctx.nextId("message", "local-message"),
			type: "tool",
			content: JSON.stringify(webSearchResult),
			created_at: nowIso(),
			name: "web_search",
			status: "completed",
			tool_call_id: webSearchCallId,
		});
		send({
			id: `${runId}:tool-result`,
			event: "tool.result",
			data: {
				...baseData,
				sequence: 5,
				tool_name: "web_search",
				tool_call_id: webSearchCallId,
				message:
					webSearchResult.answer ||
					`web_search completed for ${webSearchQueryText}`,
				output: webSearchResult,
			},
		});
		// Search snippets are leads; read a source page before synthesis.
		const primaryUrl =
			webSearchResult.results.find((item) => /^https?:\/\//i.test(item.url))
				?.url || "";
		if (
			!results.webFetchResult &&
			ctx.localToolEnabled("web_fetch") &&
			primaryUrl
		) {
			results.webFetchResult = await executeLocalWebFetch(
				run,
				primaryUrl,
				{ url: primaryUrl },
				`${runId}:web-fetch-primary`,
				6,
			);
		}
	} catch (error) {
		abortIfRequested(runSignal);
		const messageText = error instanceof Error ? error.message : String(error);
		appendRunMessage({
			id: ctx.nextId("message", "local-message"),
			type: "tool",
			content: JSON.stringify({
				error: messageText,
				query: webSearchQueryText,
			}),
			created_at: nowIso(),
			name: "web_search",
			status: "failed",
			tool_call_id: webSearchCallId,
		});
		send({
			id: `${runId}:tool-error`,
			event: "tool.error",
			data: {
				...baseData,
				sequence: 5,
				tool_name: "web_search",
				tool_call_id: webSearchCallId,
				message: messageText,
				output: {
					error: messageText,
					query: webSearchQueryText,
				},
			},
		});
	}
}
