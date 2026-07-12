import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

class MemoryStorage {
	#values = new Map();

	getItem(key) {
		return this.#values.has(key) ? this.#values.get(key) : null;
	}

	setItem(key, value) {
		this.#values.set(key, String(value));
	}
}

const cancellableRequests = [];
const pluginCalls = [];
const localStorage = new MemoryStorage();
globalThis.window = {
	Capacitor: {
		Plugins: {
			FocusAgentCancellableHttp: {
				cancel: async (options) => {
					pluginCalls.push({ method: "cancel", options });
				},
				postJson: async (options) => {
					pluginCalls.push({ method: "postJson", options });
					cancellableRequests.push(options);
					return new Promise(() => {});
				},
			},
		},
		PluginHeaders: [{ name: "FocusAgentCancellableHttp", methods: [] }],
		getPlatform: () => "android",
		isNativePlatform: () => true,
		isPluginAvailable: (name) => name === "FocusAgentCancellableHttp",
	},
	localStorage,
	location: { origin: "http://focus-agent.local" },
};
globalThis.localStorage = localStorage;

const require = createRequire(import.meta.url);
const ts = require("../node_modules/typescript");
const appRoot = resolve(import.meta.dirname, "..");
const smokeBuildDir = resolve(
	appRoot,
	".android-local-runtime-cancellation-smoke",
);
const transpiledSources = new Set();

function rewriteTranspiledImports(outputText) {
	return outputText
		.replace(
			/from\s+(["'])(\.\/[^"']+)\1/g,
			(_match, quote, specifier) =>
				`from ${quote}${specifier.endsWith(".mjs") ? specifier : `${specifier}.mjs`}${quote}`,
		)
		.replace(/from\s+(["'])@capacitor\/core\1/g, 'from "./capacitor-core.mjs"');
}

async function transpile(sourceName) {
	if (transpiledSources.has(sourceName)) return;
	transpiledSources.add(sourceName);
	const sourcePath = resolve(appRoot, "src/android-local-runtime", sourceName);
	const source = (await readFile(sourcePath, "utf8")).replace(
		/\bimport\.meta\.env\./g,
		"process.env.",
	);
	for (const match of source.matchAll(/from\s+["']\.\/([^"']+)["']/g)) {
		await transpile(`${match[1]}.ts`);
	}
	const result = ts.transpileModule(source, {
		compilerOptions: {
			importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
			isolatedModules: true,
			module: ts.ModuleKind.ES2022,
			target: ts.ScriptTarget.ES2022,
			verbatimModuleSyntax: false,
		},
		fileName: sourcePath,
		reportDiagnostics: true,
	});
	const diagnostics = result.diagnostics?.filter(
		(diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error,
	);
	if (diagnostics?.length) {
		assert.fail(
			ts.formatDiagnosticsWithColorAndContext(diagnostics, {
				getCanonicalFileName: (fileName) => fileName,
				getCurrentDirectory: () => appRoot,
				getNewLine: () => "\n",
			}),
		);
	}
	await writeFile(
		resolve(smokeBuildDir, sourceName.replace(/\.ts$/, ".mjs")),
		rewriteTranspiledImports(result.outputText),
	);
}

try {
	await rm(smokeBuildDir, { force: true, recursive: true });
	await mkdir(smokeBuildDir, { recursive: true });
	await writeFile(
		resolve(smokeBuildDir, "capacitor-core.mjs"),
		[
			"export const Capacitor = globalThis.window.Capacitor;",
			"export const CapacitorHttp = {};",
			"export function registerPlugin(name) {",
			"  return globalThis.window.Capacitor.Plugins[name];",
			"}",
		].join("\n"),
	);
	await transpile("model-provider.ts");
	await transpile("local-focus-agent-runtime.ts");

	const { postOpenAiCompatibleChatCompletion } = await import(
		`${pathToFileURL(resolve(smokeBuildDir, "model-provider.mjs")).href}?t=${Date.now()}`
	);
	const controller = new AbortController();
	const pending = postOpenAiCompatibleChatCompletion({
		messages: [{ content: "cancel this request", role: "user" }],
		model: "test-model",
		provider: {
			apiKey: "test-key",
			baseUrl: "https://provider.example.test",
			id: "test",
			label: "Test",
		},
		signal: controller.signal,
	});

	await new Promise((resolvePromise) => setTimeout(resolvePromise, 0));
	assert.equal(cancellableRequests.length, 1);
	const [{ request_id: requestId }] = cancellableRequests;
	assert.match(requestId, /^provider-[A-Za-z0-9_-]+$/);

	controller.abort(new DOMException("Stopped", "AbortError"));
	await assert.rejects(pending, (error) => error?.name === "AbortError");
	assert.deepEqual(
		pluginCalls.filter((call) => call.method === "cancel"),
		[{ method: "cancel", options: { request_id: requestId } }],
	);

	const { LocalFocusAgentRuntime } = await import(
		`${pathToFileURL(resolve(smokeBuildDir, "local-focus-agent-runtime.mjs")).href}?t=${Date.now()}`
	);
	const runtime = new LocalFocusAgentRuntime();
	await runtime.ensureSecrets();
	runtime.modelSecrets.deepseek = { apiKey: "runtime-test-key" };
	const [threadId] = Object.keys(runtime.state.threads);

	async function waitFor(predicate, label) {
		for (let attempt = 0; attempt < 100; attempt += 1) {
			if (predicate()) return;
			await new Promise((resolvePromise) => setTimeout(resolvePromise, 0));
		}
		assert.fail(`Timed out waiting for ${label}`);
	}

	async function readStream(response) {
		assert.ok(response.body, "local runtime stream should include a body");
		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let text = "";
		try {
			while (true) {
				const { done, value } = await reader.read();
				if (done) return { error: null, text };
				text += decoder.decode(value, { stream: true });
			}
		} catch (error) {
			return { error, text };
		}
	}

	function emittedEventNames(text) {
		return [...text.matchAll(/^event:\s*(.+)$/gm)].map((match) =>
			match[1].trim(),
		);
	}

	function postBody(body, signal) {
		return {
			body: JSON.stringify(body),
			headers: { "Content-Type": "application/json" },
			method: "POST",
			signal,
		};
	}

	function assertNoAssistantOrCompletion(thread, streamResult) {
		assert.equal(streamResult.error?.name, "AbortError");
		const eventNames = emittedEventNames(streamResult.text);
		assert.equal(eventNames.includes("run.completed"), false);
		assert.equal(eventNames.includes("message.completed"), false);
		assert.equal(
			thread.messages.some((message) => message.type === "ai"),
			false,
		);
		assert.equal(thread.assistant_message, null);
		const persistedState = JSON.parse(
			localStorage.getItem("focus-agent-android-local-runtime-state"),
		);
		assert.equal(
			persistedState.threads[thread.thread_id].messages.some(
				(message) => message.type === "ai",
			),
			false,
		);
		assert.equal(
			persistedState.threads[thread.thread_id].assistant_message,
			null,
		);
	}

	const uiController = new AbortController();
	const runResponse = runtime.streamRun(
		threadId,
		{ message: "Cancel this Android local run." },
		uiController.signal,
	);
	const runRead = readStream(runResponse);
	await waitFor(
		() => runtime.runCancellations.size === 1,
		"run cancellation registration",
	);
	await waitFor(
		() => cancellableRequests.length === 2,
		"runtime provider request",
	);
	const [activeRunId] = runtime.runCancellations.runIds();
	const runCancelResponse = await runtime.fetch(
		`http://focus-agent.local/v2/runs/${activeRunId}/cancel`,
		postBody({ action: "interrupt" }),
	);
	assert.equal(runCancelResponse.status, 200);
	assert.equal((await runCancelResponse.json()).run.status, "interrupt");
	assert.equal(
		uiController.signal.aborted,
		false,
		"runtime cancellation must not abort the caller-owned UI signal",
	);
	const runResult = await runRead;
	await waitFor(
		() => runtime.runCancellations.size === 0,
		"run cancellation cleanup",
	);
	assertNoAssistantOrCompletion(runtime.state.threads[threadId], runResult);
	assert.equal(
		(
			await runtime.fetch(
				`http://focus-agent.local/v2/runs/${activeRunId}/cancel`,
				postBody({ action: "interrupt" }),
			)
		).status,
		404,
		"inactive runs must not report a successful cancellation",
	);

	const firstThreadUiController = new AbortController();
	const secondThreadUiController = new AbortController();
	const firstThreadRead = readStream(
		runtime.streamRun(
			threadId,
			{ message: "Cancel this first thread run." },
			firstThreadUiController.signal,
		),
	);
	const secondThreadRead = readStream(
		runtime.streamRun(
			threadId,
			{ message: "Cancel this second thread run." },
			secondThreadUiController.signal,
		),
	);
	await waitFor(
		() => runtime.runCancellations.size === 2,
		"thread run registrations",
	);
	await waitFor(
		() => cancellableRequests.length === 4,
		"thread provider requests",
	);
	const activeThreadRunIds = runtime.runCancellations.runIds();
	const threadCancelResponse = await runtime.fetch(
		`http://focus-agent.local/v2/threads/${threadId}/runs/cancel`,
		postBody({ action: "rollback" }),
	);
	assert.equal(threadCancelResponse.status, 200);
	const threadCancelPayload = await threadCancelResponse.json();
	assert.deepEqual(
		[...threadCancelPayload.cancelled_run_ids].sort(),
		[...activeThreadRunIds].sort(),
	);
	assert.equal(threadCancelPayload.cancelled_count, 2);
	assert.equal(firstThreadUiController.signal.aborted, false);
	assert.equal(secondThreadUiController.signal.aborted, false);
	const [firstThreadResult, secondThreadResult] = await Promise.all([
		firstThreadRead,
		secondThreadRead,
	]);
	await waitFor(
		() => runtime.runCancellations.size === 0,
		"thread cancellation cleanup",
	);
	assertNoAssistantOrCompletion(
		runtime.state.threads[threadId],
		firstThreadResult,
	);
	assertNoAssistantOrCompletion(
		runtime.state.threads[threadId],
		secondThreadResult,
	);

	const uiAbortController = new AbortController();
	const uiAbortRead = readStream(
		runtime.streamRun(
			threadId,
			{ message: "Stop this run from the Android UI signal." },
			uiAbortController.signal,
		),
	);
	await waitFor(
		() => runtime.runCancellations.size === 1,
		"UI abort run registration",
	);
	await waitFor(
		() => cancellableRequests.length === 5,
		"UI abort provider request",
	);
	uiAbortController.abort(new DOMException("Stopped by UI", "AbortError"));
	const uiAbortResult = await uiAbortRead;
	await waitFor(
		() => runtime.runCancellations.size === 0,
		"UI abort cancellation cleanup",
	);
	assertNoAssistantOrCompletion(runtime.state.threads[threadId], uiAbortResult);
	assert.equal(
		pluginCalls.filter((call) => call.method === "cancel").length,
		5,
		"each provider request should receive one native cancellation",
	);

	console.log("Android local runtime cancellation smoke passed.");
} finally {
	await rm(smokeBuildDir, { force: true, recursive: true });
}
