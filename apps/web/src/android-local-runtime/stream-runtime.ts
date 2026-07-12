import type {
	FocusAgentBranchDecisionEvent,
	FocusAgentEvent,
	FocusAgentHarnessRunCancelRequest,
	FocusAgentHarnessRunRequest,
	FocusAgentHarnessRunResponse,
	FocusAgentThreadHarnessRunsCancelResponse,
} from "@focus-agent/web-sdk";
import { DEFAULT_MODEL_ID, SSE_HEADERS } from "./constants";
import {
	clone,
	contextUsage,
	errorResponse,
	jsonResponse,
	nowIso,
	parseJsonBody,
	stringValue,
} from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import {
	deniesExecutedWebAccess,
	localReply,
	localReplyWithLocalTools,
	localReplyWithWebFetch,
	localReplyWithWebSearch,
	splitText,
} from "./local-text";
import { syncLocalThreadActiveSkills } from "./local-tool-execution";
import {
	abortIfRequested,
	missingProviderKeyReply,
	postOpenAiCompatibleChatCompletion,
	providerErrorMessage,
} from "./model-provider";
import { sseFrame, sseResponse } from "./sse";
import type {
	LocalToolExecution,
	LocalWebFetchResult,
	LocalWebSearchResult,
} from "./types";
import { runLocalWebFetch } from "./web-fetch";
import {
	shouldUseCurrentTimeTool,
	shouldUseWebFetch,
	shouldUseWebSearch,
	webFetchUrl,
	webSearchQuery,
} from "./web-planning";
import { runLocalWebSearch } from "./web-search";

export function handleV2(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	init?: RequestInit,
): Response {
	const [resource, threadOrRunId, runsOrAction, streamOrResume, maybeStream] =
		segments;
	if (
		resource === "threads" &&
		runsOrAction === "runs" &&
		streamOrResume === "cancel" &&
		method === "POST"
	) {
		const body = parseJsonBody(init) as FocusAgentHarnessRunCancelRequest;
		const action = body.action === "rollback" ? "rollback" : "interrupt";
		const cancelledRunIds = ctx.runCancellations.cancelThread(
			threadOrRunId,
			action,
		);
		return jsonResponse({
			thread_id: threadOrRunId,
			cancelled_run_ids: cancelledRunIds,
			cancelled_count: cancelledRunIds.length,
		} satisfies FocusAgentThreadHarnessRunsCancelResponse);
	}
	if (
		resource === "threads" &&
		runsOrAction === "runs" &&
		streamOrResume === "stream" &&
		method === "POST"
	) {
		const body = parseJsonBody(init) as FocusAgentHarnessRunRequest;
		return ctx.streamRun(threadOrRunId, body, init?.signal ?? undefined);
	}
	if (
		resource === "threads" &&
		runsOrAction === "runs" &&
		streamOrResume === "resume" &&
		maybeStream === "stream" &&
		method === "POST"
	) {
		return ctx.streamRun(
			threadOrRunId,
			{ message: "Resume local runtime turn." },
			init?.signal ?? undefined,
		);
	}
	if (resource === "runs" && runsOrAction === "stream" && method === "POST") {
		return sseResponse(
			[
				{
					id: `${threadOrRunId}:closed`,
					event: "run.closed",
					data: {
						run_id: threadOrRunId,
						status: "closed",
						source_node: "android-local-runtime",
						message: "No historical local events are available for this run.",
					},
				},
			],
			init?.signal ?? undefined,
		);
	}
	if (resource === "runs" && runsOrAction === "cancel" && method === "POST") {
		const body = parseJsonBody(init) as FocusAgentHarnessRunCancelRequest;
		const action = body.action === "rollback" ? "rollback" : "interrupt";
		if (!ctx.runCancellations.cancel(threadOrRunId, action)) {
			return errorResponse(404, `Active run not found: ${threadOrRunId}`);
		}
		return jsonResponse({
			run: {
				run_id: threadOrRunId,
				status: action,
				updated_at: nowIso(),
			},
			thread_state: null,
		} satisfies FocusAgentHarnessRunResponse);
	}
	return errorResponse(404, "Unsupported local stream route.");
}

export function streamRun(
	ctx: LocalFocusAgentRuntime,
	threadId: string,
	request: FocusAgentHarnessRunRequest,
	signal?: AbortSignal,
): Response {
	const thread = ctx.state.threads[threadId];
	if (!thread) return errorResponse(404, "Thread not found.");
	const runId = ctx.nextId("run", "local-run");
	const runSignal = ctx.runCancellations.register(runId, threadId, signal);
	const timestamp = nowIso();
	const message = stringValue(request.message);
	const selectedModel =
		request.model ||
		ctx.state.adminConfig.models.default_model ||
		DEFAULT_MODEL_ID;
	let branchDecision: FocusAgentBranchDecisionEvent | null = null;
	if (message.trim()) {
		thread.messages.push({
			id: ctx.nextId("message", "local-message"),
			type: "human",
			content: message,
			created_at: timestamp,
		});
		branchDecision = ctx.recordLocalBranchDecision(thread, message, runId);
	}
	thread.selected_model = selectedModel;
	thread.selected_thinking_mode = request.thinking_mode || "disabled";
	thread.context_usage = contextUsage(thread.messages);
	thread.trace = {
		...(thread.trace ?? {}),
		last_run_id: runId,
		runtime: "android-local",
	};
	ctx.touchConversation(thread.root_thread_id, message);
	ctx.persist();

	const baseData = { run_id: runId, thread_id: thread.thread_id };
	const runMessageIds = new Set<string>();
	const appendRunMessage = (
		runMessage: (typeof thread.messages)[number],
	): void => {
		thread.messages.push(runMessage);
		if (typeof runMessage.id === "string") {
			runMessageIds.add(runMessage.id);
		}
	};
	const discardRunMessages = () => {
		thread.messages = thread.messages.filter(
			(threadMessage) =>
				typeof threadMessage.id !== "string" ||
				!runMessageIds.has(threadMessage.id),
		);
		thread.context_usage = contextUsage(thread.messages);
	};
	const encoder = new TextEncoder();
	const body = new ReadableStream<Uint8Array>({
		start: async (controller) => {
			const send = (event: FocusAgentEvent) => {
				controller.enqueue(encoder.encode(sseFrame(event)));
			};
			try {
				if (runSignal.aborted) {
					throw runSignal.reason ?? new DOMException("Aborted", "AbortError");
				}
				send({
					id: `${runId}:1`,
					event: "run.metadata",
					data: { ...baseData, sequence: 1, source_node: "local-runtime" },
				});
				send({
					id: `${runId}:2`,
					event: "run.status",
					data: { ...baseData, sequence: 2, phase: "running" },
				});
				send({
					id: `${runId}:3`,
					event: "reasoning.delta",
					data: {
						...baseData,
						delta: "Using the Android in-app local runtime.",
						completed: true,
						content: "Using the Android in-app local runtime.",
					},
				});

				const isChinese = /[\u3400-\u9fff]/.test(message);
				const webSearchEnabled =
					ctx.localToolEnabled("web_search") && shouldUseWebSearch(message);
				let currentUtcTimeResult: string | null = null;
				if (
					webSearchEnabled &&
					ctx.localToolEnabled("current_utc_time") &&
					shouldUseCurrentTimeTool(message)
				) {
					const timeToolCallId = `${runId}:current-utc-time`;
					currentUtcTimeResult = nowIso();
					send({
						id: `${runId}:time-tool-call-delta`,
						event: "tool.call.delta",
						data: {
							...baseData,
							sequence: 4,
							id: timeToolCallId,
							name: "current_utc_time",
							tool_call_id: timeToolCallId,
							args_delta: "{}",
							raw: {
								id: timeToolCallId,
								name: "current_utc_time",
								args: {},
							},
						},
					});
					send({
						id: `${runId}:time-tool-requested`,
						event: "tool.requested",
						data: {
							...baseData,
							sequence: 4,
							node: "android-local-runtime",
							tool_name: "current_utc_time",
							tool_call_id: timeToolCallId,
							args: {},
						},
					});
					appendRunMessage({
						id: ctx.nextId("message", "local-message"),
						type: "ai",
						content: "",
						created_at: currentUtcTimeResult,
						tool_calls: [
							{
								id: timeToolCallId,
								name: "current_utc_time",
								args: {},
								function: {
									name: "current_utc_time",
									arguments: "{}",
								},
							},
						],
					});
					appendRunMessage({
						id: ctx.nextId("message", "local-message"),
						type: "tool",
						content: currentUtcTimeResult,
						created_at: currentUtcTimeResult,
						name: "current_utc_time",
						status: "completed",
						tool_call_id: timeToolCallId,
					});
					send({
						id: `${runId}:time-tool-result`,
						event: "tool.result",
						data: {
							...baseData,
							sequence: 5,
							tool_name: "current_utc_time",
							tool_call_id: timeToolCallId,
							message: currentUtcTimeResult,
							output: currentUtcTimeResult,
						},
					});
				}
				const webFetchEnabled =
					ctx.localToolEnabled("web_fetch") && shouldUseWebFetch(message);
				const webFetchCallId = `${runId}:web-fetch`;
				const webFetchTargetUrl = webFetchUrl(message);
				let webFetchResult: LocalWebFetchResult | null = null;
				if (webFetchEnabled) {
					send({
						id: `${runId}:fetch-tool-call-delta`,
						event: "tool.call.delta",
						data: {
							...baseData,
							sequence: 4,
							id: webFetchCallId,
							name: "web_fetch",
							tool_call_id: webFetchCallId,
							args_delta: JSON.stringify({ url: webFetchTargetUrl }),
							raw: {
								id: webFetchCallId,
								name: "web_fetch",
								args: { url: webFetchTargetUrl },
							},
						},
					});
					send({
						id: `${runId}:fetch-tool-requested`,
						event: "tool.requested",
						data: {
							...baseData,
							sequence: 4,
							node: "android-local-runtime",
							tool_name: "web_fetch",
							tool_call_id: webFetchCallId,
							args: { url: webFetchTargetUrl },
						},
					});
					appendRunMessage({
						id: ctx.nextId("message", "local-message"),
						type: "ai",
						content: "",
						created_at: nowIso(),
						tool_calls: [
							{
								id: webFetchCallId,
								name: "web_fetch",
								args: { url: webFetchTargetUrl },
								function: {
									name: "web_fetch",
									arguments: JSON.stringify({ url: webFetchTargetUrl }),
								},
							},
						],
					});
					try {
						webFetchResult = await runLocalWebFetch(
							webFetchTargetUrl,
							runSignal,
						);
						appendRunMessage({
							id: ctx.nextId("message", "local-message"),
							type: "tool",
							content: JSON.stringify(webFetchResult),
							created_at: nowIso(),
							name: "web_fetch",
							status: "completed",
							tool_call_id: webFetchCallId,
						});
						send({
							id: `${runId}:fetch-tool-result`,
							event: "tool.result",
							data: {
								...baseData,
								sequence: 5,
								tool_name: "web_fetch",
								tool_call_id: webFetchCallId,
								message:
									webFetchResult.title ||
									`web_fetch completed for ${webFetchTargetUrl}`,
								output: webFetchResult,
							},
						});
					} catch (error) {
						abortIfRequested(runSignal);
						const messageText =
							error instanceof Error ? error.message : String(error);
						appendRunMessage({
							id: ctx.nextId("message", "local-message"),
							type: "tool",
							content: JSON.stringify({
								error: messageText,
								url: webFetchTargetUrl,
							}),
							created_at: nowIso(),
							name: "web_fetch",
							status: "failed",
							tool_call_id: webFetchCallId,
						});
						send({
							id: `${runId}:fetch-tool-error`,
							event: "tool.error",
							data: {
								...baseData,
								sequence: 5,
								tool_name: "web_fetch",
								tool_call_id: webFetchCallId,
								message: messageText,
								output: {
									error: messageText,
									url: webFetchTargetUrl,
								},
							},
						});
					}
				}
				const webSearchCallId = `${runId}:web-search`;
				const webSearchQueryText = webSearchQuery(
					message,
					currentUtcTimeResult,
				);
				let webSearchResult: LocalWebSearchResult | null = null;
				if (webSearchEnabled) {
					send({
						id: `${runId}:tool-call-delta`,
						event: "tool.call.delta",
						data: {
							...baseData,
							sequence: 4,
							id: webSearchCallId,
							name: "web_search",
							tool_call_id: webSearchCallId,
							args_delta: JSON.stringify({ query: webSearchQueryText }),
							raw: {
								id: webSearchCallId,
								name: "web_search",
								args: { query: webSearchQueryText },
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
							args: { query: webSearchQueryText },
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
								args: { query: webSearchQueryText },
								function: {
									name: "web_search",
									arguments: JSON.stringify({
										query: webSearchQueryText,
									}),
								},
							},
						],
					});
					try {
						webSearchResult = await runLocalWebSearch(
							webSearchQueryText,
							runSignal,
						);
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
					} catch (error) {
						abortIfRequested(runSignal);
						const messageText =
							error instanceof Error ? error.message : String(error);
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
				const localToolExecutions: LocalToolExecution[] = [];
				const localToolPlan = ctx.localAppToolPlan(thread, message);
				for (const [index, plannedTool] of localToolPlan.entries()) {
					const localToolCallId = `${runId}:${plannedTool.name}:${index + 1}`;
					send({
						id: `${localToolCallId}:call-delta`,
						event: "tool.call.delta",
						data: {
							...baseData,
							sequence: 6 + index,
							id: localToolCallId,
							name: plannedTool.name,
							tool_call_id: localToolCallId,
							args_delta: JSON.stringify(plannedTool.args),
							raw: {
								id: localToolCallId,
								name: plannedTool.name,
								args: plannedTool.args,
							},
						},
					});
					send({
						id: `${localToolCallId}:requested`,
						event: "tool.requested",
						data: {
							...baseData,
							sequence: 6 + index,
							node: "android-local-runtime",
							tool_name: plannedTool.name,
							tool_call_id: localToolCallId,
							args: plannedTool.args,
						},
					});
					appendRunMessage({
						id: ctx.nextId("message", "local-message"),
						type: "ai",
						content: "",
						created_at: nowIso(),
						tool_calls: [
							{
								id: localToolCallId,
								name: plannedTool.name,
								args: plannedTool.args,
								function: {
									name: plannedTool.name,
									arguments: JSON.stringify(plannedTool.args),
								},
							},
						],
					});
					const execution = ctx.executeLocalAppTool(
						thread,
						plannedTool.name,
						plannedTool.args,
					);
					localToolExecutions.push(execution);
					appendRunMessage({
						id: ctx.nextId("message", "local-message"),
						type: "tool",
						content: JSON.stringify(execution.output),
						created_at: nowIso(),
						name: plannedTool.name,
						status: "completed",
						tool_call_id: localToolCallId,
					});
					send({
						id: `${localToolCallId}:result`,
						event: "tool.result",
						data: {
							...baseData,
							sequence: 7 + index,
							tool_name: plannedTool.name,
							tool_call_id: localToolCallId,
							message: execution.message,
							output: execution.output,
						},
					});
				}
				const resolvedProvider = ctx.modelProvider(selectedModel);
				let source = "local-runtime";
				let reply = "";
				if (!resolvedProvider) {
					reply = webFetchResult
						? localReplyWithWebFetch(message, webFetchResult)
						: webSearchResult
							? localReplyWithWebSearch(message, webSearchResult)
							: localToolExecutions.length > 0
								? localReplyWithLocalTools(message, localToolExecutions)
								: missingProviderKeyReply(
										ctx.modelProviderLabel(selectedModel),
										isChinese,
									);
				} else {
					const { model, provider } = resolvedProvider;
					source = provider.id;
					try {
						reply = await postOpenAiCompatibleChatCompletion({
							messages: ctx.chatMessages(
								thread,
								webSearchResult,
								webFetchResult,
								localToolExecutions,
							),
							model,
							provider,
							signal: runSignal,
						});
					} catch (error) {
						abortIfRequested(runSignal);
						reply = webFetchResult
							? localReplyWithWebFetch(message, webFetchResult)
							: webSearchResult
								? localReplyWithWebSearch(message, webSearchResult)
								: localToolExecutions.length > 0
									? localReplyWithLocalTools(message, localToolExecutions)
									: providerErrorMessage(error, isChinese);
					}
				}
				abortIfRequested(runSignal);
				if (!reply.trim()) {
					reply = localReply(message);
				}
				if (webSearchResult && deniesExecutedWebAccess(reply)) {
					reply = localReplyWithWebSearch(message, webSearchResult);
					source = "local-runtime";
				} else if (webFetchResult && deniesExecutedWebAccess(reply)) {
					reply = localReplyWithWebFetch(message, webFetchResult);
					source = "local-runtime";
				}

				appendRunMessage({
					id: ctx.nextId("message", "local-message"),
					type: "ai",
					content: reply,
					created_at: nowIso(),
					response_metadata: {
						model_name: selectedModel,
						provider: source,
						runtime: "android-local",
					},
					usage_metadata: {
						input_tokens: Math.ceil(message.length / 4),
						output_tokens: Math.ceil(reply.length / 4),
						total_tokens: Math.ceil((message.length + reply.length) / 4),
					},
				});
				thread.assistant_message = reply;
				thread.context_usage = contextUsage(thread.messages);
				ctx.persist();

				splitText(reply).forEach((delta, index) => {
					send({
						id: `${runId}:${index + 4}`,
						event: "message.delta",
						data: { ...baseData, delta, channel: "message" },
					});
				});
				send({
					id: `${runId}:message-completed`,
					event: "message.completed",
					data: { ...baseData, content: reply, source },
				});
				syncLocalThreadActiveSkills(ctx, thread);
				send({
					id: `${runId}:completed`,
					event: "run.completed",
					data: {
						...baseData,
						status: "completed",
						thread_state: clone(thread) as unknown as Record<string, unknown>,
						branch_action: branchDecision?.promoted_action_id
							? (thread.branch_actions.find(
									(action) =>
										action.action_id === branchDecision.promoted_action_id,
								) ?? null)
							: null,
						branch_decision: branchDecision,
					},
				});
				controller.close();
			} catch (error) {
				if (runSignal.aborted) {
					discardRunMessages();
					ctx.persist();
					controller.error(
						runSignal.reason ?? new DOMException("Aborted", "AbortError"),
					);
					return;
				}
				send({
					id: `${runId}:failed`,
					event: "run.failed",
					data: {
						...baseData,
						error: error instanceof Error ? error.message : String(error),
						message: "Android local runtime failed to complete the turn.",
					},
				});
				controller.close();
			} finally {
				ctx.runCancellations.release(runId);
			}
		},
	});
	return new Response(body, { headers: SSE_HEADERS });
}
