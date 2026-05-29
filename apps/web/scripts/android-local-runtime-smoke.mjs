import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

process.env.VITE_FOCUS_AGENT_TARGET = "android";
process.env.VITE_FOCUS_AGENT_APP_BASE = "/";
process.env.VITE_FOCUS_AGENT_ROUTER_BASE = "/";
process.env.VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH = "false";
process.env.VITE_FOCUS_AGENT_ENABLE_PRODUCTIVITY = "false";

class MemoryStorage {
	#values = new Map();

	clear() {
		this.#values.clear();
	}

	getItem(key) {
		return this.#values.has(key) ? this.#values.get(key) : null;
	}

	removeItem(key) {
		this.#values.delete(key);
	}

	setItem(key, value) {
		this.#values.set(key, String(value));
	}
}

const localStorage = new MemoryStorage();
globalThis.window = {
	localStorage,
	location: { origin: "http://focus-agent.local" },
};
globalThis.localStorage = localStorage;

const originalFetch = globalThis.fetch;
const providerRequests = [];
globalThis.fetch = async (input, init) => {
	const url = String(input);
	if (url === "https://api.openai.example.com/chat/completions") {
		const headers = init?.headers ?? {};
		const authorization =
			headers instanceof Headers
				? headers.get("Authorization")
				: (headers.Authorization ?? headers.authorization);
		const body = JSON.parse(String(init?.body ?? "{}"));
		const hasWebSearchContext = Array.isArray(body.messages)
			? body.messages.some(
					(message) =>
						typeof message.content === "string" &&
						message.content.includes("already executed web_search"),
				)
			: false;
		providerRequests.push({ authorization, body, url });
		return new Response(
			JSON.stringify({
				choices: [
					{
						message: {
							content: hasWebSearchContext
								? "很抱歉，我目前无法直接获取实时天气数据。"
								: `Provider response for ${body.model}`,
						},
					},
				],
			}),
			{
				headers: { "Content-Type": "application/json" },
				status: 200,
			},
		);
	}
	if (
		url.startsWith("https://duckduckgo.com/html/") ||
		url.startsWith("https://duckduckgo.com/lite/")
	) {
		const parsed = new URL(url);
		const query = parsed.searchParams.get("q");
		return new Response(
			[
				"<html><body>",
				'<div class="result">',
				`<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=${encodeURIComponent("https://example.com/focus-agent-android")}&amp;rut=smoke">Focus Agent Android local runtime</a>`,
				`<a class="result__snippet" href="//duckduckgo.com/l/?uddg=${encodeURIComponent("https://example.com/focus-agent-android")}">Search evidence for ${query}</a>`,
				"</div>",
				"</body></html>",
			].join(""),
			{
				headers: { "Content-Type": "text/html" },
				status: 200,
			},
		);
	}
	if (url.startsWith("https://api.duckduckgo.com/")) {
		const parsed = new URL(url);
		return new Response(
			JSON.stringify({
				Heading: "Android local search smoke",
				AbstractText: `Search evidence for ${parsed.searchParams.get("q")}`,
				AbstractURL: "https://example.com/focus-agent-search",
				RelatedTopics: [
					{
						Text: "Focus Agent Android local runtime - web search result",
						FirstURL: "https://example.com/focus-agent-android",
					},
				],
			}),
			{
				headers: { "Content-Type": "application/json" },
				status: 200,
			},
		);
	}
	if (url === "https://example.com/focus-agent-page") {
		return new Response(
			"<html><head><title>Focus Agent Android page</title></head><body><main>Fetched Android local runtime page content.</main></body></html>",
			{
				headers: { "Content-Type": "text/html" },
				status: 200,
			},
		);
	}
	return originalFetch(input, init);
};

const require = createRequire(import.meta.url);
const ts = require("../node_modules/typescript");
const appRoot = resolve(import.meta.dirname, "..");
const repoRoot = resolve(appRoot, "..", "..");
const smokeBuildDir = resolve(appRoot, ".android-local-runtime-smoke");
const androidLocalRuntimeModules = [
	{
		outputName: "constants.mjs",
		sourcePath: "src/android-local-runtime/constants.ts",
		specifier: "./constants",
	},
	{
		outputName: "types.mjs",
		sourcePath: "src/android-local-runtime/types.ts",
		specifier: "./types",
	},
	{
		outputName: "helpers.mjs",
		sourcePath: "src/android-local-runtime/helpers.ts",
		specifier: "./helpers",
	},
	{
		outputName: "local-v1-runtime.mjs",
		sourcePath: "src/android-local-runtime/local-v1-runtime.ts",
		specifier: "./local-v1-runtime",
	},
	{
		outputName: "local-text.mjs",
		sourcePath: "src/android-local-runtime/local-text.ts",
		specifier: "./local-text",
	},
	{
		outputName: "model-provider.mjs",
		sourcePath: "src/android-local-runtime/model-provider.ts",
		specifier: "./model-provider",
	},
	{
		outputName: "skills.mjs",
		sourcePath: "src/android-local-runtime/skills.ts",
		specifier: "./skills",
	},
	{
		outputName: "sse.mjs",
		sourcePath: "src/android-local-runtime/sse.ts",
		specifier: "./sse",
	},
	{
		outputName: "state.mjs",
		sourcePath: "src/android-local-runtime/state.ts",
		specifier: "./state",
	},
	{
		outputName: "web-fetch.mjs",
		sourcePath: "src/android-local-runtime/web-fetch.ts",
		specifier: "./web-fetch",
	},
	{
		outputName: "web-planning.mjs",
		sourcePath: "src/android-local-runtime/web-planning.ts",
		specifier: "./web-planning",
	},
	{
		outputName: "web-search.mjs",
		sourcePath: "src/android-local-runtime/web-search.ts",
		specifier: "./web-search",
	},
	{
		outputName: "agent-runtime.mjs",
		sourcePath: "src/android-local-runtime/agent-runtime.ts",
		specifier: "./agent-runtime",
	},
	{
		outputName: "memory-observability-runtime.mjs",
		sourcePath: "src/android-local-runtime/memory-observability-runtime.ts",
		specifier: "./memory-observability-runtime",
	},
	{
		outputName: "model-runtime.mjs",
		sourcePath: "src/android-local-runtime/model-runtime.ts",
		specifier: "./model-runtime",
	},
	{
		outputName: "local-tool-planning.mjs",
		sourcePath: "src/android-local-runtime/local-tool-planning.ts",
		specifier: "./local-tool-planning",
	},
	{
		outputName: "workspace-runtime.mjs",
		sourcePath: "src/android-local-runtime/workspace-runtime.ts",
		specifier: "./workspace-runtime",
	},
	{
		outputName: "local-tool-execution.mjs",
		sourcePath: "src/android-local-runtime/local-tool-execution.ts",
		specifier: "./local-tool-execution",
	},
	{
		outputName: "auth-conversation-runtime.mjs",
		sourcePath: "src/android-local-runtime/auth-conversation-runtime.ts",
		specifier: "./auth-conversation-runtime",
	},
	{
		outputName: "thread-branch-routes.mjs",
		sourcePath: "src/android-local-runtime/thread-branch-routes.ts",
		specifier: "./thread-branch-routes",
	},
	{
		outputName: "branch-logic.mjs",
		sourcePath: "src/android-local-runtime/branch-logic.ts",
		specifier: "./branch-logic",
	},
	{
		outputName: "admin-runtime.mjs",
		sourcePath: "src/android-local-runtime/admin-runtime.ts",
		specifier: "./admin-runtime",
	},
	{
		outputName: "stream-runtime.mjs",
		sourcePath: "src/android-local-runtime/stream-runtime.ts",
		specifier: "./stream-runtime",
	},
];
const androidLocalRuntimeImportOutputs = new Map(
	androidLocalRuntimeModules.map(({ outputName, specifier }) => [
		specifier,
		outputName,
	]),
);

function rewriteTranspiledLocalImports(outputText, importOutputs) {
	if (!importOutputs?.size) return outputText;
	return outputText.replace(
		/from\s+(["'])(\.\/[^"']+)\1/g,
		(match, quote, specifier) => {
			const outputName = importOutputs.get(specifier);
			return outputName ? `from ${quote}./${outputName}${quote}` : match;
		},
	);
}

async function loadTsModule(sourcePath, outputName, options = {}) {
	const rawSource = await readFile(sourcePath, "utf8");
	const source = rawSource.replace(/\bimport\.meta\.env\./g, "process.env.");
	const result = ts.transpileModule(source, {
		compilerOptions: {
			importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
			isolatedModules: true,
			jsx: ts.JsxEmit.ReactJSX,
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
	await mkdir(smokeBuildDir, { recursive: true });
	const outputPath = resolve(smokeBuildDir, outputName);
	const outputText = rewriteTranspiledLocalImports(
		result.outputText,
		options.importOutputs,
	);
	await writeFile(outputPath, outputText);
	if (options.importModule === false) return null;
	return import(`${pathToFileURL(outputPath).href}?t=${Date.now()}`);
}

function jsonBody(body) {
	return {
		body: JSON.stringify(body),
		headers: { "Content-Type": "application/json" },
		method: "POST",
	};
}

async function expectJson(response) {
	if (!response.ok) {
		assert.fail(await response.text());
	}
	return response.json();
}

async function expectStatus(response, status) {
	if (response.status !== status) {
		assert.fail(
			`Expected ${status}, received ${response.status}: ${await response.text()}`,
		);
	}
}

async function collectSse(response) {
	if (!response.ok) {
		assert.fail(await response.text());
	}
	assert.ok(response.body, "SSE response should include a body");
	const text = await response.text();
	return text
		.split(/\r?\n\r?\n/)
		.filter(Boolean)
		.map((frame) => {
			const event = { event: "message", data: "" };
			for (const line of frame.split(/\r?\n/)) {
				if (line.startsWith("event:")) event.event = line.slice(6).trim();
				if (line.startsWith("data:")) event.data += line.slice(5).trimStart();
			}
			return { event: event.event, data: JSON.parse(event.data) };
		});
}

function assertRecord(value, label) {
	assert.ok(
		value && typeof value === "object" && !Array.isArray(value),
		`${label} should be an object`,
	);
	return value;
}

function assertArray(value, label) {
	assert.ok(Array.isArray(value), `${label} should be an array`);
	return value;
}

function assertBoolean(value, label) {
	assert.equal(typeof value, "boolean", `${label} should be a boolean`);
}

function assertString(value, label) {
	assert.equal(typeof value, "string", `${label} should be a string`);
}

function assertNonEmptyString(value, label) {
	assertString(value, label);
	assert.ok(value.trim(), `${label} should not be empty`);
}

function assertNullableString(value, label) {
	assert.ok(
		value === null || value === undefined || typeof value === "string",
		`${label} should be a nullable string`,
	);
}

function assertConfigSourceContract(source, label) {
	const sourceRecord = assertRecord(source, label);
	assertNonEmptyString(sourceRecord.path, `${label}.path`);
	assertBoolean(sourceRecord.exists, `${label}.exists`);
	assertBoolean(sourceRecord.writable, `${label}.writable`);
}

function assertAdminConfigContract(config) {
	const configRecord = assertRecord(config, "admin config");
	const models = assertRecord(configRecord.models, "admin config models");
	assertConfigSourceContract(models.source, "admin config models source");
	assertNonEmptyString(models.default_model, "admin config default model");
	assertNullableString(models.helper_model, "admin config helper model");
	assertArray(models.model_choices, "admin config model choices").forEach(
		(choice, index) =>
			assertNonEmptyString(choice, `admin config model choice ${index}`),
	);
	assertBoolean(models.requires_restart, "admin config models requires_restart");
	assertArray(models.providers, "admin config model providers").forEach(
		(provider, index) => {
			const providerRecord = assertRecord(
				provider,
				`admin config model provider ${index}`,
			);
			assertNonEmptyString(providerRecord.id, `model provider ${index}.id`);
			assertNullableString(providerRecord.label, `model provider ${index}.label`);
			assertNullableString(
				providerRecord.backend_provider,
				`model provider ${index}.backend_provider`,
			);
			assertArray(providerRecord.aliases, `model provider ${index}.aliases`).forEach(
				(alias, aliasIndex) =>
					assertNonEmptyString(
						alias,
						`model provider ${index}.aliases[${aliasIndex}]`,
					),
			);
			assertNullableString(
				providerRecord.logo_slug,
				`model provider ${index}.logo_slug`,
			);
			assertNullableString(
				providerRecord.logo_letter,
				`model provider ${index}.logo_letter`,
			);
			assertNullableString(
				providerRecord.base_url_env,
				`model provider ${index}.base_url_env`,
			);
			assertNullableString(
				providerRecord.base_url_default,
				`model provider ${index}.base_url_default`,
			);
			assertBoolean(
				providerRecord.base_url_configured,
				`model provider ${index}.base_url_configured`,
			);
			assertNullableString(
				providerRecord.api_key_env,
				`model provider ${index}.api_key_env`,
			);
			assertBoolean(
				providerRecord.api_key_configured,
				`model provider ${index}.api_key_configured`,
			);
			assert.equal(
				Object.hasOwn(providerRecord, "api_key_default"),
				false,
				"admin config responses must not expose local provider secrets",
			);
		},
	);
	assertArray(models.models, "admin config model entries").forEach(
		(model, index) => {
			const modelRecord = assertRecord(model, `admin config model entry ${index}`);
			assertNonEmptyString(modelRecord.id, `model entry ${index}.id`);
			assertNullableString(modelRecord.label, `model entry ${index}.label`);
			assertBoolean(
				modelRecord.supports_thinking,
				`model entry ${index}.supports_thinking`,
			);
			assertBoolean(
				modelRecord.default_thinking_enabled,
				`model entry ${index}.default_thinking_enabled`,
			);
			assertRecord(modelRecord.request_kwargs, `model entry ${index}.request_kwargs`);
			assertRecord(
				modelRecord.thinking_enabled_request_kwargs,
				`model entry ${index}.thinking_enabled_request_kwargs`,
			);
			assertRecord(
				modelRecord.thinking_disabled_request_kwargs,
				`model entry ${index}.thinking_disabled_request_kwargs`,
			);
			assertNullableString(
				modelRecord.thinking_disabled_model_name,
				`model entry ${index}.thinking_disabled_model_name`,
			);
			assertNullableString(
				modelRecord.reasoning_effort,
				`model entry ${index}.reasoning_effort`,
			);
			assert.ok(
				modelRecord.no_temperature === null ||
					typeof modelRecord.no_temperature === "boolean",
				`model entry ${index}.no_temperature should be a nullable boolean`,
			);
			assertNullableString(
				modelRecord.thinking_enable_extra_body_type,
				`model entry ${index}.thinking_enable_extra_body_type`,
			);
			assertNullableString(
				modelRecord.thinking_disable_extra_body_type,
				`model entry ${index}.thinking_disable_extra_body_type`,
			);
			assertNullableString(
				modelRecord.thinking_disable_switch_model,
				`model entry ${index}.thinking_disable_switch_model`,
			);
		},
	);

	const tools = assertRecord(configRecord.tools, "admin config tools");
	assertConfigSourceContract(tools.source, "admin config tools source");
	assertBoolean(tools.requires_restart, "admin config tools requires_restart");
	assertArray(tools.providers, "admin config tool providers").forEach(
		(provider, index) => {
			const providerRecord = assertRecord(
				provider,
				`admin config tool provider ${index}`,
			);
			assertNonEmptyString(providerRecord.id, `tool provider ${index}.id`);
			assertBoolean(providerRecord.enabled, `tool provider ${index}.enabled`);
			assert.ok(
				providerRecord.order === null ||
					providerRecord.order === undefined ||
					Number.isFinite(providerRecord.order),
				`tool provider ${index}.order should be nullable number`,
			);
			assertRecord(providerRecord.metadata, `tool provider ${index}.metadata`);
			assertArray(providerRecord.overrides, `tool provider ${index}.overrides`);
		},
	);
	assertArray(tools.tools, "admin config tool entries").forEach((tool, index) => {
		const toolRecord = assertRecord(tool, `admin config tool ${index}`);
		assertNonEmptyString(toolRecord.name, `tool ${index}.name`);
		assertNonEmptyString(toolRecord.label, `tool ${index}.label`);
		assertString(toolRecord.description, `tool ${index}.description`);
		assertBoolean(toolRecord.enabled, `tool ${index}.enabled`);
		assertRecord(toolRecord.settings, `tool ${index}.settings`);
		const metadata = assertRecord(toolRecord.metadata, `tool ${index}.metadata`);
		assertNonEmptyString(metadata.runtime, `tool ${index}.metadata.runtime`);
		assertNonEmptyString(metadata.toolset, `tool ${index}.metadata.toolset`);
		assertBoolean(
			metadata.requires_workspace,
			`tool ${index}.metadata.requires_workspace`,
		);
		assertBoolean(
			metadata.requires_workspace_write,
			`tool ${index}.metadata.requires_workspace_write`,
		);
		assertBoolean(metadata.side_effect, `tool ${index}.metadata.side_effect`);
	});

	const policies = assertRecord(configRecord.policies, "admin config policies");
	assertConfigSourceContract(policies.source, "admin config policies source");
	assertBoolean(policies.requires_restart, "admin config policies requires_restart");
	assertArray(policies.items, "admin config policy items").forEach(
		(policy, index) => {
			const policyRecord = assertRecord(policy, `admin config policy ${index}`);
			assertNonEmptyString(policyRecord.key, `policy ${index}.key`);
			assertNullableString(policyRecord.env_key, `policy ${index}.env_key`);
			assertNonEmptyString(policyRecord.label, `policy ${index}.label`);
			assertNonEmptyString(
				policyRecord.value_type,
				`policy ${index}.value_type`,
			);
			assertNonEmptyString(policyRecord.source, `policy ${index}.source`);
			assertBoolean(policyRecord.editable, `policy ${index}.editable`);
			assertBoolean(policyRecord.sensitive, `policy ${index}.sensitive`);
			assertBoolean(
				policyRecord.requires_restart,
				`policy ${index}.requires_restart`,
			);
			assertArray(policyRecord.options, `policy ${index}.options`);
		},
	);

	const system = assertRecord(configRecord.system, "admin config system");
	assertConfigSourceContract(system.source, "admin config system source");
	assertArray(system.items, "admin config system items").forEach((item, index) => {
		const itemRecord = assertRecord(item, `admin config system item ${index}`);
		assertNonEmptyString(itemRecord.key, `system item ${index}.key`);
		assertNonEmptyString(itemRecord.label, `system item ${index}.label`);
		assertNonEmptyString(
			itemRecord.value_type,
			`system item ${index}.value_type`,
		);
		assertNonEmptyString(itemRecord.source, `system item ${index}.source`);
		assertBoolean(itemRecord.editable, `system item ${index}.editable`);
		assertBoolean(itemRecord.sensitive, `system item ${index}.sensitive`);
		assertBoolean(
			itemRecord.requires_restart,
			`system item ${index}.requires_restart`,
		);
		assertArray(itemRecord.options, `system item ${index}.options`);
	});
	assertNullableString(configRecord.updated_at, "admin config updated_at");
	assertNullableString(configRecord.updated_by, "admin config updated_by");
	assertNullableString(configRecord.message, "admin config message");
}

function assertModelsResponseContract(modelList, adminConfig) {
	const modelListRecord = assertRecord(modelList, "model list");
	assertNonEmptyString(modelListRecord.default_model, "model list default_model");
	const models = assertArray(modelListRecord.models, "model list models");
	assert.ok(models.length > 0, "model list should include at least one model");
	for (const [index, model] of models.entries()) {
		const modelRecord = assertRecord(model, `model list item ${index}`);
		assertNonEmptyString(modelRecord.id, `model list item ${index}.id`);
		assertNonEmptyString(modelRecord.provider, `model list item ${index}.provider`);
		assertNonEmptyString(
			modelRecord.provider_label,
			`model list item ${index}.provider_label`,
		);
		assertNullableString(
			modelRecord.provider_logo_slug,
			`model list item ${index}.provider_logo_slug`,
		);
		assertNullableString(
			modelRecord.provider_logo_letter,
			`model list item ${index}.provider_logo_letter`,
		);
		assertNonEmptyString(modelRecord.name, `model list item ${index}.name`);
		assertNonEmptyString(modelRecord.label, `model list item ${index}.label`);
		assertBoolean(modelRecord.is_default, `model list item ${index}.is_default`);
		assertBoolean(
			modelRecord.supports_thinking,
			`model list item ${index}.supports_thinking`,
		);
		assertBoolean(
			modelRecord.default_thinking_enabled,
			`model list item ${index}.default_thinking_enabled`,
		);
	}
	assert.ok(
		models.some(
			(model) =>
				model.id === modelListRecord.default_model && model.is_default === true,
		),
		"model list should mark the default model",
	);
	if (adminConfig) {
		assert.equal(modelListRecord.default_model, adminConfig.models.default_model);
		for (const model of adminConfig.models.models) {
			assert.ok(
				models.some((item) => item.id === model.id),
				`model list should expose admin model ${model.id}`,
			);
		}
	}
}

function assertLocalRuntimeExposeContract(runtime) {
	const adminConfig = runtime.adminConfigResponse();
	assertAdminConfigContract(adminConfig);
	assertModelsResponseContract(runtime.modelsResponse(), adminConfig);
	assert.equal(runtime.localToolEnabled("web_search"), true);
	assert.equal(runtime.localToolEnabled("productivity_capture"), false);
	const webSearchTool = runtime.localTool("web_search");
	assert.equal(webSearchTool.name, "web_search");
	assert.equal(webSearchTool.settings.provider, "duckduckgo");
	assert.ok(
		runtime.localEnabledTools().some((tool) => tool.name === "web_fetch"),
		"localEnabledTools should expose enabled app-local tools",
	);
	assert.ok(
		runtime.localCapabilities().some((tool) => tool.name === "web_search"),
		"localCapabilities should expose app-local tool behavior",
	);
	assert.equal(runtime.localRolePolicy().enabled, true);
	assert.equal(
		runtime.localRoleDecision("Plan an Android local task.").model_id,
		adminConfig.models.default_model,
	);
	assert.ok(
		runtime
			.localSelectedSkills("Need Android web search")
			.some((skill) => skill.skill_id === "local-web-tools"),
	);
	assert.equal(
		runtime.localContextEvidenceRecord({ message: "Android context" }).metadata
			.runtime,
		"android-local",
	);
	const resolvedDefaultProvider = runtime.providerConfigForModel(
		adminConfig.models.default_model,
	);
	assert.equal(resolvedDefaultProvider.model, adminConfig.models.default_model);
	assert.equal(
		resolvedDefaultProvider.provider.id,
		adminConfig.models.providers[0].id,
	);
	assert.equal(runtime.modelProvider(adminConfig.models.default_model), null);
	assert.equal(
		runtime.modelProviderLabel(adminConfig.models.default_model),
		adminConfig.models.providers[0].label,
	);
	const [thread] = Object.values(runtime.state.threads);
	assert.ok(
		runtime
			.localAppToolPlan(thread, "请列出产物列表并搜索技能 web tools")
			.some((tool) => tool.name === "artifact_list"),
		"localAppToolPlan should produce executable local tool plans",
	);
}

function assertLocalStreamContract(events, expectedThreadId) {
	assert.ok(Array.isArray(events), "stream events should be an array");
	assert.ok(events.length > 0, "stream should emit events");
	const terminal = events.at(-1);
	assert.equal(
		terminal.event,
		"run.completed",
		`stream should end with run.completed, got ${terminal.event}`,
	);
	const metadata = events.find((event) => event.event === "run.metadata");
	assert.ok(metadata, "stream should emit run.metadata");
	assertNonEmptyString(metadata.data.run_id, "stream run_id");
	assert.equal(metadata.data.thread_id, expectedThreadId);
	const runId = metadata.data.run_id;
	for (const [index, event] of events.entries()) {
		const data = assertRecord(event.data, `stream event ${index}.data`);
		if ("run_id" in data) {
			assert.equal(data.run_id, runId, `stream event ${index}.run_id`);
		}
		if ("thread_id" in data) {
			assert.equal(
				data.thread_id,
				expectedThreadId,
				`stream event ${index}.thread_id`,
			);
		}
		if (event.event === "tool.call.delta") {
			assertNonEmptyString(data.id, `tool.call.delta ${index}.id`);
			assertNonEmptyString(data.name, `tool.call.delta ${index}.name`);
			assertNonEmptyString(
				data.tool_call_id,
				`tool.call.delta ${index}.tool_call_id`,
			);
			assertString(data.args_delta, `tool.call.delta ${index}.args_delta`);
			assertRecord(data.raw, `tool.call.delta ${index}.raw`);
		}
		if (
			event.event === "tool.requested" ||
			event.event === "tool.result" ||
			event.event === "tool.error"
		) {
			assertNonEmptyString(data.tool_name, `tool event ${index}.tool_name`);
			assertNonEmptyString(data.tool_call_id, `tool event ${index}.tool_call_id`);
		}
	}
	assert.ok(
		events.some(
			(event) =>
				event.event === "run.status" && event.data.phase === "running",
		),
		"stream should emit a running status",
	);
	assert.ok(
		events.some(
			(event) =>
				event.event === "reasoning.delta" &&
				typeof event.data.delta === "string",
		),
		"stream should emit reasoning text",
	);
	const messageCompleted = events.find(
		(event) => event.event === "message.completed",
	);
	assert.ok(messageCompleted, "stream should emit message.completed");
	assertNonEmptyString(
		messageCompleted.data.content,
		"message.completed content",
	);
	assertNonEmptyString(
		messageCompleted.data.source,
		"message.completed source",
	);
	const terminalData = assertRecord(terminal.data, "run.completed data");
	assert.equal(terminalData.status, "completed");
	const threadState = assertRecord(
		terminalData.thread_state,
		"run.completed thread_state",
	);
	assert.equal(threadState.thread_id, expectedThreadId);
	assert.equal(threadState.assistant_message, messageCompleted.data.content);
	assert.equal(threadState.trace?.last_run_id, runId);
	const messages = assertArray(threadState.messages, "thread_state messages");
	assert.ok(messages.length >= 2, "thread_state should include user and assistant messages");
	assert.ok(
		messages.some(
			(message) =>
				message.type === "ai" &&
				message.content === messageCompleted.data.content,
		),
		"thread_state should include the completed assistant message",
	);
	for (const [index, message] of messages.entries()) {
		const messageRecord = assertRecord(message, `thread_state message ${index}`);
		assertNonEmptyString(messageRecord.id, `thread_state message ${index}.id`);
		assertNonEmptyString(messageRecord.type, `thread_state message ${index}.type`);
		assertNonEmptyString(
			messageRecord.created_at,
			`thread_state message ${index}.created_at`,
		);
	}
}

function assertSdkStreamStateContract(state, events, expectedThreadId) {
	const streamState = assertRecord(state, "SDK stream state");
	assert.equal(streamState.isClosed, true);
	assertNonEmptyString(streamState.visibleText, "SDK stream visibleText");
	const completed = events.find((event) => event.event === "message.completed");
	assert.equal(streamState.visibleText, completed.data.content);
	const latestTurnState = assertRecord(
		streamState.latestTurnState,
		"SDK stream latestTurnState",
	);
	assert.equal(latestTurnState.thread_id, expectedThreadId);
	assert.equal(latestTurnState.assistant_message, streamState.visibleText);
}

try {
	const { appEnv } = await loadTsModule(
		resolve(appRoot, "src/shared/config/env.ts"),
		"env.mjs",
	);
	assert.equal(appEnv.useLocalRuntime, true);
	assert.equal(appEnv.features.agentTeam, false);
	assert.equal(appEnv.features.agentGovernance, true);
	assert.equal(appEnv.features.agentMemory, true);
	assert.equal(appEnv.features.observability, true);
	assert.equal(appEnv.features.productivity, false);

	for (const { outputName, sourcePath } of androidLocalRuntimeModules) {
		await loadTsModule(resolve(appRoot, sourcePath), outputName, {
			importModule: false,
			importOutputs: androidLocalRuntimeImportOutputs,
		});
	}
	const { LocalFocusAgentRuntime, createLocalFocusAgentFetch } = await loadTsModule(
		resolve(appRoot, "src/android-local-runtime/local-focus-agent-runtime.ts"),
		"local-focus-agent-runtime.mjs",
		{ importOutputs: androidLocalRuntimeImportOutputs },
	);
	const directRuntime = new LocalFocusAgentRuntime();
	await directRuntime.ensureSecrets();
	assertLocalRuntimeExposeContract(directRuntime);
	const focusFetch = createLocalFocusAgentFetch();
	const { FocusAgentClient } = await import(
		pathToFileURL(resolve(repoRoot, "frontend-sdk/dist/index.js")).href
	);
	const sdkClient = new FocusAgentClient({
		baseUrl: "http://focus-agent.local",
		fetchImpl: focusFetch,
	});

	await expectStatus(
		await focusFetch("http://focus-agent.local/v1/notes"),
		404,
	);
	await expectStatus(
		await focusFetch("http://focus-agent.local/v1/tasks"),
		404,
	);
	await expectStatus(
		await focusFetch(
			"http://focus-agent.local/v1/productivity/capture/note",
			jsonBody({ payload: "hidden in Android" }),
		),
		404,
	);

	const adminConfig = await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/config"),
	);
	assertAdminConfigContract(adminConfig);
	const adminToolNames = adminConfig.tools.tools.map((tool) => tool.name);
	assert.ok(adminToolNames.includes("write_text_artifact"));
	assert.ok(adminToolNames.includes("artifact_list"));
	assert.ok(adminToolNames.includes("memory_search"));
	assert.ok(adminToolNames.includes("conversation_summary"));
	assert.ok(adminToolNames.includes("skills_search"));
	assert.ok(adminToolNames.includes("skill_install"));
	assert.ok(adminToolNames.includes("web_fetch"));
	assert.ok(adminToolNames.includes("web_search"));
	assert.ok(adminToolNames.includes("current_utc_time"));
	assert.equal(
		adminConfig.tools.tools.find((tool) => tool.name === "list_files")?.enabled,
		true,
	);
	assert.equal(
		adminConfig.tools.tools.find((tool) => tool.name === "web_search")?.settings
			.provider,
		"duckduckgo",
	);
	assert.equal(adminConfig.tools.providers[0].id, "android-local-web");
	const modelList = await expectJson(
		await focusFetch("http://focus-agent.local/v1/models"),
	);
	assertModelsResponseContract(modelList, adminConfig);
	assert.ok(
		modelList.models.some((model) => model.id === adminConfig.models.default_model),
		"Android local runtime should expose configured models through the Web SDK model endpoint",
	);
	const sdkModelList = await sdkClient.listModels();
	assertModelsResponseContract(sdkModelList, adminConfig);
	assert.ok(
		sdkModelList.models.some((model) => model.id === adminConfig.models.default_model),
		"Web SDK model listing should work against Android local runtime",
	);
	assert.equal((await sdkClient.getPrincipal()).user.user_id, "android-local-admin");
	assert.equal((await sdkClient.createDemoToken({})).token_type, "bearer");
	assert.equal(
		(await sdkClient.refresh({})).principal.user.user_id,
		"android-local-admin",
	);
	await sdkClient.changePassword({});
	const sdkSessions = await sdkClient.listMySessions();
	assert.ok(sdkSessions.count >= 1);
	await sdkClient.logout();
	assert.equal(
		(
			await sdkClient.register({
				username: "android-sdk-register",
				display_name: "Android SDK Register",
			})
		).principal.user.username,
		"android-sdk-register",
	);
	assert.equal(
		(
			await sdkClient.login({
				username: "android-sdk-login",
				password: "local",
			})
		).principal.user.username,
		"android-sdk-login",
	);
	assert.equal(
		(await sdkClient.listUsers({ query: "local", limit: 10 })).count >= 1,
		true,
		"Web SDK user listing should work against Android local runtime",
	);
	const sdkUser = await sdkClient.createUser({
		username: "android-sdk-user",
		display_name: "Android SDK User",
		roles: ["viewer"],
	});
	assert.equal((await sdkClient.getUser(sdkUser.user_id)).username, "android-sdk-user");
	assert.equal(
		(
			await sdkClient.updateUser(sdkUser.user_id, {
				display_name: "Android SDK User Updated",
			})
		).display_name,
		"Android SDK User Updated",
	);
	assert.equal(
		(await sdkClient.updateUserStatus(sdkUser.user_id, { status: "suspended" }))
			.status,
		"suspended",
	);
	assert.deepEqual(
		(await sdkClient.updateUserRoles(sdkUser.user_id, { roles: ["member"] }))
			.roles,
		["member"],
	);
	assert.ok(await sdkClient.resetUserPassword(sdkUser.user_id, {}));
	assert.ok((await sdkClient.listAuditEvents({ limit: 5 })).items);
	const sdkAdminConfig = await sdkClient.getAdminConfig();
	assertAdminConfigContract(sdkAdminConfig);
	assert.ok(
		await sdkClient.updateAdminModelConfig({
			default_model: adminConfig.models.default_model,
			helper_model: adminConfig.models.helper_model,
			model_choices: adminConfig.models.model_choices,
			models: adminConfig.models.models.map((model) => ({
				id: model.id,
				label: model.label,
			})),
		}),
	);
	assert.ok(
		await sdkClient.updateAdminToolConfig({
			providers: adminConfig.tools.providers,
			tools: adminConfig.tools.tools.map((tool) => ({
				enabled: tool.enabled,
				name: tool.name,
				settings: tool.settings,
			})),
		}),
	);
	assert.ok(
		await sdkClient.updateAdminPolicyConfig({
			values: { android_sdk_runtime_smoke: true },
		}),
	);
	const sdkAdminSessions = await sdkClient.listUserSessions("android-local-admin", {
		include_revoked: true,
	});
	assert.ok(sdkAdminSessions.count >= 1);
	assert.ok((await sdkClient.listAgentCapabilities()).items.length > 0);
	assert.ok((await sdkClient.listAgentToolsets()).items.length > 0);
	assert.equal((await sdkClient.getAgentRolePolicy()).enabled, true);
	assert.ok(
		(await sdkClient.dryRunAgentRoleRoute({ message: "Android SDK route" })).plan
			.decisions[0].model_id,
	);
	assert.ok((await sdkClient.listAgentRoleDecisions(5)).items);
	assert.deepEqual(
		(
			await sdkClient.routeAgentTools({
				available_tools: ["web_fetch", "notes_create"],
			})
		).plan.denied_tools,
		["notes_create"],
	);
	assert.ok((await sdkClient.listAgentToolRouteDecisions(5)).items);
	assert.equal((await sdkClient.getAgentMemoryCuratorPolicy()).enabled, true);
	assert.equal(
		(
			await sdkClient.evaluateAgentMemoryCurator({
				message: "Android SDK memory",
			})
		).decision.status,
		"skipped",
	);
	assert.ok((await sdkClient.listAgentMemoryCuratorDecisions(5)).items);
	assert.ok(
		(await sdkClient.getAgentSkillCatalog()).items.some(
			(skill) => skill.skill_id === "android-local-runtime",
		),
	);
	assert.ok(
		(await sdkClient.selectAgentSkills({ message: "Need Android web search" }))
			.skill_ids.length > 0,
	);
	assert.ok((await sdkClient.listAgentSkillSelections(5)).items);
	assert.ok(
		(
			await sdkClient.sendAgentSkillSelectionFeedback("android-sdk-selection", {
				rating: "up",
			})
		).items,
	);
	assert.equal(
		(
			await sdkClient.updateAgentSkillPreference("android-local-runtime", {
				enabled: true,
				pinned: true,
			})
		).skill.pinned,
		true,
	);
	assert.equal((await sdkClient.getAgentFeedbackTrend()).notes_tasks_capture_count, 0);
	assert.equal((await sdkClient.getAgentDelegationPolicy()).enabled, false);
	assert.equal(
		(await sdkClient.planAgentDelegation({ message: "Android SDK delegation" }))
			.plan.tasks.length,
		0,
	);
	assert.ok((await sdkClient.listAgentDelegationRuns(5)).items);
	assert.equal((await sdkClient.getAgentModelRouterPolicy()).enabled, true);
	assert.ok((await sdkClient.routeAgentModel({ role: "planner" })).decision.model);
	assert.ok((await sdkClient.listAgentModelRouterDecisions(5)).items);
	assert.ok((await sdkClient.listAgentSelfRepairFailures(5)).items);
	assert.ok(
		(await sdkClient.previewAgentSelfRepairPromotion({ failure_ids: ["sdk"] }))
			.preview,
	);
	assert.ok((await sdkClient.listAgentReviewQueue(5)).items);
	assert.equal(
		(await sdkClient.approveAgentReviewQueueItem("android-sdk-review")).item
			.status,
		"approve",
	);
	assert.equal(
		(await sdkClient.rejectAgentReviewQueueItem("android-sdk-review")).item.status,
		"reject",
	);
	assert.equal((await sdkClient.getAgentContextPolicy()).enabled, true);
	assert.ok(
		(
			await sdkClient.previewAgentContext({
				assembled_context: "Android SDK context",
			})
		).decision.budget,
	);
	assert.ok((await sdkClient.listAgentContextDecisions(5)).items);
	assert.ok((await sdkClient.listAgentContextArtifacts(5)).items);
	assert.equal(
		(await sdkClient.listAgentContextEvidence({ limit: 2 })).backend,
		"android-local",
	);
	assert.equal(
		(await sdkClient.explainAgentContext({ message: "Android SDK context" }))
			.backend,
		"android-local",
	);
	assert.equal((await sdkClient.getAgentTaskLedgerPolicy()).enabled, true);
	assert.equal(
		(await sdkClient.planAgentTaskLedger({ message: "Android SDK task" })).ledger
			.tasks.length,
		1,
	);
	assert.ok((await sdkClient.listAgentTaskLedgerRuns(5)).items);
	assert.ok((await sdkClient.listAgentArtifacts(5)).items);
	assert.ok(
		(await sdkClient.synthesizeAgentArtifacts({ message: "Android SDK artifact" }))
			.result,
	);
	assert.ok((await sdkClient.listAgentCriticVerdicts(5)).items);
	assert.equal(
		(await sdkClient.evaluateAgentCriticGate({ message: "Android SDK critic" }))
			.result.verdict,
		"pass",
	);
	assert.equal((await sdkClient.getObservabilityOverview()).trajectory_available, true);
	const sdkConversation = await sdkClient.createConversation({
		title: "Android SDK smoke",
	});
	assert.ok(
		(await sdkClient.listConversations()).conversations.some(
			(item) => item.root_thread_id === sdkConversation.root_thread_id,
		),
	);
	assert.equal(
		(
			await sdkClient.renameConversation(sdkConversation.root_thread_id, {
				title: "Android SDK smoke renamed",
			})
		).title,
		"Android SDK smoke renamed",
	);
	assert.equal(
		(await sdkClient.archiveConversation(sdkConversation.root_thread_id))
			.is_archived,
		true,
	);
	assert.equal(
		(await sdkClient.activateConversation(sdkConversation.root_thread_id))
			.is_archived,
		false,
	);
	assert.equal(
		(await sdkClient.getThreadState(sdkConversation.root_thread_id)).thread_id,
		sdkConversation.root_thread_id,
	);
	assert.equal(
		(await sdkClient.getThreadResolution(sdkConversation.root_thread_id))
			.input_thread_id,
		sdkConversation.root_thread_id,
	);
	assert.equal(
		(await sdkClient.previewThreadContext(sdkConversation.root_thread_id, {}))
			.context_usage.status,
		"ok",
	);
	assert.equal(
		(await sdkClient.compactThreadContext(sdkConversation.root_thread_id, {}))
			.thread_id,
		sdkConversation.root_thread_id,
	);
	const sdkFallbackEvents = [];
	const sdkFallbackState = await sdkClient.collectStream(
		await sdkClient.streamTurn({
			thread_id: sdkConversation.root_thread_id,
			message: "请用一句话介绍 Android 本地运行时。",
		}),
		{ onEvent: (event) => sdkFallbackEvents.push(event) },
	);
	assertLocalStreamContract(sdkFallbackEvents, sdkConversation.root_thread_id);
	assertSdkStreamStateContract(
		sdkFallbackState,
		sdkFallbackEvents,
		sdkConversation.root_thread_id,
	);
	assert.ok(
		sdkFallbackState.visibleText.includes("还没有配置模型 API Key"),
		"Android local runtime should provide a stable assistant fallback without API keys",
	);
	assert.equal(
		providerRequests.length,
		0,
		"assistant fallback should not call a configured provider before a local API key exists",
	);
	assert.equal(
		(await sdkClient.getBranchTree(sdkConversation.root_thread_id)).root.thread_id,
		sdkConversation.root_thread_id,
	);
	const sdkBranch = await sdkClient.forkBranch({
		parent_thread_id: sdkConversation.root_thread_id,
		branch_name: "Android SDK branch",
		branch_role: "explore_alternatives",
	});
	assert.ok(sdkBranch.child_thread_id);
	assert.equal(
		(
			await sdkClient.renameBranch(sdkBranch.child_thread_id, {
				branch_name: "Android SDK branch renamed",
			})
		).branch_name,
		"Android SDK branch renamed",
	);
	assert.equal((await sdkClient.archiveBranch(sdkBranch.child_thread_id)).is_archived, true);
	assert.equal((await sdkClient.activateBranch(sdkBranch.child_thread_id)).is_archived, false);
	assert.ok(await sdkClient.prepareMergeProposal(sdkBranch.child_thread_id));
	assert.equal(
		(
			await sdkClient.applyMergeDecision(sdkBranch.child_thread_id, {
				approved: true,
				mode: "summary_only",
			})
		).target_thread_id,
		sdkConversation.root_thread_id,
	);
	const sdkMemoryList = await sdkClient.listMemoryRecords({ limit: 5 });
	assert.ok(sdkMemoryList.items[0]?.memory_id);
	assert.ok(await sdkClient.getMemoryRecord(sdkMemoryList.items[0].memory_id));
	assert.ok((await sdkClient.getMemoryUsage(sdkMemoryList.items[0].memory_id)).memory_id);
	assert.ok((await sdkClient.listMemoryAuditEvents({ limit: 5 })).items);
	assert.ok(
		(
			await sdkClient.listMemoryRecordAuditEvents(
				sdkMemoryList.items[0].memory_id,
				{ limit: 5 },
			)
		).items,
	);
	assert.ok((await sdkClient.listMemoryCandidates({ limit: 5 })).items);
	const sdkStream = await sdkClient.streamTurn({
		thread_id: sdkConversation.root_thread_id,
		message: "请列出产物列表，验证 Android SDK stream。",
	});
	const sdkStreamEvents = [];
	const sdkStreamState = await sdkClient.collectStream(sdkStream, {
		onEvent: (event) => sdkStreamEvents.push(event),
	});
	assert.equal(sdkStreamState.isClosed, true);
	assertLocalStreamContract(sdkStreamEvents, sdkConversation.root_thread_id);
	assert.equal(
		sdkStreamState.latestTurnState?.thread_id,
		sdkConversation.root_thread_id,
	);
	assert.ok(
		sdkStreamState.toolEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "artifact_list",
		),
		"SDK collectStream should reduce Android local tool events",
	);
	const sdkHarnessStream = await sdkClient.streamHarnessRun(
		sdkConversation.root_thread_id,
		{ message: "Android SDK streamHarnessRun smoke." },
	);
	assert.equal((await sdkClient.collectStream(sdkHarnessStream)).isClosed, true);
	const sdkResumeStream = await sdkClient.streamResume({
		thread_id: sdkConversation.root_thread_id,
		resume: { run_id: "android-sdk-resume" },
	});
	assert.equal((await sdkClient.collectStream(sdkResumeStream)).isClosed, true);
	assert.deepEqual(
		await Array.fromAsync(
			await sdkClient.streamHarnessRunEvents("android-sdk-resume"),
		),
		[],
	);
	assert.equal(
		(await sdkClient.cancelHarnessRun("android-sdk-resume", {
			action: "interrupt",
		})).run.status,
		"interrupt",
	);
	const sdkTrajectories = await sdkClient.listTrajectoryTurns({ limit: 5 });
	assert.ok(sdkTrajectories.count > 0);
	assert.ok((await sdkClient.getTrajectoryStats()).stats);
	assert.equal(
		(await sdkClient.getTrajectoryTurn(sdkTrajectories.items[0].id)).item.id,
		sdkTrajectories.items[0].id,
	);
	assert.ok(
		(await sdkClient.replayTrajectoryTurn(sdkTrajectories.items[0].id, {}))
			.replay_result,
	);
	assert.ok(
		(await sdkClient.promoteTrajectoryTurn(sdkTrajectories.items[0].id, {}))
			.case_id,
	);
	assert.ok(
		(await sdkClient.batchPromoteTrajectoryTurnsPreview({
			turn_ids: [sdkTrajectories.items[0].id],
		})).items,
	);
	assert.ok(
		(await sdkClient.batchReplayCompareTrajectoryTurns({
			turn_ids: [sdkTrajectories.items[0].id],
		})).summary,
	);

	const principal = await expectJson(
		await focusFetch("http://focus-agent.local/v1/auth/me"),
	);
	assert.equal(principal.user.user_id, "android-local-admin");
	const registered = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/auth/register",
			jsonBody({ username: "android-register", display_name: "Android Register" }),
		),
	);
	assert.equal(registered.principal.user.username, "android-register");
	const loggedIn = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/auth/login",
			jsonBody({ username: "android-login", password: "local" }),
		),
	);
	assert.equal(loggedIn.principal.user.username, "android-login");
	const demoToken = await expectJson(
		await focusFetch("http://focus-agent.local/v1/auth/demo-token", jsonBody({})),
	);
	assert.equal(demoToken.token_type, "bearer");
	await expectJson(
		await focusFetch("http://focus-agent.local/v1/auth/refresh", jsonBody({})),
	);
	await expectStatus(
		await focusFetch(
			"http://focus-agent.local/v1/auth/change-password",
			jsonBody({}),
		),
		204,
	);
	const authSessions = await expectJson(
		await focusFetch("http://focus-agent.local/v1/auth/sessions"),
	);
	assert.ok(authSessions.count >= 1);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/auth/sessions/${authSessions.items[0].session_id}/revoke`,
					jsonBody({}),
				),
			)
		).revoked_at,
		"Android local auth should support session revocation",
	);
	await expectStatus(
		await focusFetch("http://focus-agent.local/v1/auth/logout", jsonBody({})),
		204,
	);

	const adminUsers = await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/users"),
	);
	assert.ok(adminUsers.count >= 1);
	const createdUser = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/admin/users",
			jsonBody({
				display_name: "Android Smoke User",
				email: "android-smoke@example.com",
				roles: ["viewer"],
				username: "android-smoke",
			}),
		),
	);
	assert.equal(createdUser.username, "android-smoke");
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/admin/users/${createdUser.user_id}`,
				),
			)
		).user_id,
		createdUser.user_id,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/admin/users/${createdUser.user_id}`,
					{ ...jsonBody({ display_name: "Android Smoke Updated" }), method: "PATCH" },
				),
			)
		).display_name,
		"Android Smoke Updated",
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/admin/users/${createdUser.user_id}/status`,
					jsonBody({ status: "suspended" }),
				),
			)
		).status,
		"suspended",
	);
	assert.deepEqual(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/admin/users/${createdUser.user_id}/roles`,
					{ ...jsonBody({ roles: ["member"] }), method: "PUT" },
				),
			)
		).roles,
		["member"],
	);
	await expectJson(
		await focusFetch(
			`http://focus-agent.local/v1/admin/users/${createdUser.user_id}/password`,
			jsonBody({}),
		),
	);
	const adminUserSessions = await expectJson(
		await focusFetch(
			`http://focus-agent.local/v1/admin/users/${principal.user.user_id}/sessions?include_revoked=true`,
		),
	);
	assert.ok(adminUserSessions.count >= 1);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/admin/users/${principal.user.user_id}/sessions/revoke`,
					jsonBody({ session_id: adminUserSessions.items[0].session_id }),
				),
			)
		).revoked_at,
		"Android local admin should support revoking user sessions",
	);
	const auditEvents = await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/audit-events"),
	);
	assert.ok(auditEvents.count >= 1);

	const deepseekProvider = {
		id: "deepseek",
		label: "DeepSeek",
		backend_provider: "openai-compatible",
		aliases: ["deepseek"],
		base_url_default: "https://api.deepseek.com",
		api_key_default: "deepseek-key",
	};
	const deepseekProviderWithoutSecret = {
		id: "deepseek",
		label: "DeepSeek",
		backend_provider: "openai-compatible",
		aliases: ["deepseek"],
		base_url_default: "https://api.deepseek.com",
	};
	const moonshotProvider = {
		id: "moonshot",
		label: "Moonshot",
		backend_provider: "openai-compatible",
		aliases: ["kimi"],
		base_url_default: "https://api.openai.example.com",
		api_key_default: "moonshot-key",
	};
	const moonshotProviderWithoutSecret = {
		id: "moonshot",
		label: "Moonshot",
		backend_provider: "openai-compatible",
		aliases: ["kimi"],
		base_url_default: "https://api.openai.example.com",
	};
	const multiProviderConfig = await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/config/models", {
			...jsonBody({
				default_model: "kimi:kimi-k2.6",
				helper_model: "deepseek-v4-pro",
				model_choices: ["deepseek-v4-pro", "kimi:kimi-k2.6"],
				providers: [deepseekProvider, moonshotProvider],
				models: [
					{ id: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
					{ id: "kimi:kimi-k2.6", label: "Kimi K2.6" },
				],
			}),
			method: "PATCH",
		}),
	);
	assertAdminConfigContract(multiProviderConfig);
	assertModelsResponseContract(
		await expectJson(await focusFetch("http://focus-agent.local/v1/models")),
		multiProviderConfig,
	);
	assert.equal(
		multiProviderConfig.models.providers.find(
			(provider) => provider.id === "moonshot",
		)?.api_key_configured,
		true,
	);
	const providerConversation = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/conversations",
			jsonBody({ title: "Android provider routing smoke" }),
		),
	);
	await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${providerConversation.root_thread_id}/runs/stream`,
			jsonBody({
				message: "Use the configured provider model.",
				model: "kimi:kimi-k2.6",
			}),
		),
	);
	assert.equal(providerRequests.length, 1);
	assert.equal(
		providerRequests[0].url,
		"https://api.openai.example.com/chat/completions",
	);
	assert.equal(providerRequests[0].authorization, "Bearer moonshot-key");
	assert.equal(providerRequests[0].body.model, "kimi-k2.6");

	await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/config/models", {
			...jsonBody({
				providers: [deepseekProvider],
			}),
			method: "PATCH",
		}),
	);
	const readdedProviderConfig = await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/config/models", {
			...jsonBody({
				providers: [deepseekProvider, moonshotProviderWithoutSecret],
			}),
			method: "PATCH",
		}),
	);
	assertAdminConfigContract(readdedProviderConfig);
	assert.equal(
		readdedProviderConfig.models.providers.find(
			(provider) => provider.id === "moonshot",
		)?.api_key_configured,
		false,
	);
	await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/config/models", {
			...jsonBody({
				default_model: "deepseek-v4-pro",
				helper_model: "deepseek-v4-pro",
				model_choices: ["deepseek-v4-pro"],
				providers: [],
				models: [{ id: "deepseek-v4-pro", label: "DeepSeek V4 Pro" }],
			}),
			method: "PATCH",
		}),
	);
	await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/config/models", {
			...jsonBody({
				providers: [deepseekProviderWithoutSecret],
			}),
			method: "PATCH",
		}),
	);
	const policyConfig = await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/config/policies", {
			...jsonBody({
				values: {
					android_local_runtime_smoke: true,
				},
			}),
			method: "PATCH",
		}),
	);
	assertAdminConfigContract(policyConfig);
	assert.equal(
		policyConfig.policies.items.find(
			(item) => item.key === "android_local_runtime_smoke",
		)?.value,
		true,
	);

	const capabilities = await expectJson(
		await focusFetch("http://focus-agent.local/v1/agent/capabilities"),
	);
	assert.ok(
		capabilities.items.some((tool) => tool.name === "write_text_artifact"),
	);
	assert.ok(capabilities.items.some((tool) => tool.name === "memory_search"));
	assert.ok(
		capabilities.items.some((tool) => tool.name === "conversation_summary"),
	);
	assert.ok(capabilities.items.some((tool) => tool.name === "skills_search"));
	assert.ok(capabilities.items.some((tool) => tool.name === "skill_install"));
	assert.ok(capabilities.items.some((tool) => tool.name === "web_fetch"));
	assert.ok(capabilities.items.some((tool) => tool.name === "web_search"));
	assert.ok(capabilities.items.some((tool) => tool.name === "list_files"));
	assert.ok(capabilities.items.some((tool) => tool.name === "git_status"));

	const toolsets = await expectJson(
		await focusFetch("http://focus-agent.local/v1/agent/toolsets"),
	);
	assert.ok(toolsets.count > 0);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/tool-router/decisions?limit=5",
				),
			)
		).items,
	);

	const rolePolicy = await expectJson(
		await focusFetch("http://focus-agent.local/v1/agent/roles/policy"),
	);
	assert.equal(rolePolicy.enabled, true);
	const roleDryRun = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/agent/roles/dry-run",
			jsonBody({ message: "Plan an Android local web lookup." }),
		),
	);
	assert.ok(
		roleDryRun.plan.decisions[0].model_id,
		"role dry-run should expose preview decisions for the Web panel",
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/roles/decisions?limit=5",
				),
			)
		).items,
	);

	const memoryPolicy = await expectJson(
		await focusFetch("http://focus-agent.local/v1/agent/memory/curator/policy"),
	);
	assert.equal(memoryPolicy.enabled, true);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/memory/curator/evaluate",
					jsonBody({ message: "Android local memory candidate" }),
				),
			)
		).decision.status,
		"skipped",
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/memory/curator/decisions?limit=5",
				),
			)
		).items,
	);

	const skillCatalog = await expectJson(
		await focusFetch("http://focus-agent.local/v1/agent/skills/catalog"),
	);
	assert.ok(
		skillCatalog.items.some(
			(skill) => skill.skill_id === "android-local-runtime",
		),
		"Android governance should expose local built-in skills",
	);
	const skillSelection = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/agent/skills/select",
			jsonBody({ message: "Need a web search skill for Android." }),
		),
	);
	assert.ok(
		skillSelection.skill_ids.includes("local-web-tools"),
		"Android skill selection should activate matching local skills",
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/skills/selections?limit=5",
				),
			)
		).items,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/skills/selections/android-selection/feedback",
					jsonBody({ rating: "up" }),
				),
			)
		).items,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/skills/android-local-runtime/preference",
					{ ...jsonBody({ enabled: true, pinned: true }), method: "PATCH" },
				),
			)
		).skill.pinned,
		true,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch("http://focus-agent.local/v1/agent/feedback/trend"),
			)
		).notes_tasks_capture_count,
		0,
	);

	const delegationPolicy = await expectJson(
		await focusFetch("http://focus-agent.local/v1/agent/delegation/policy"),
	);
	assert.equal(delegationPolicy.enabled, false);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/delegation/plan",
					jsonBody({ message: "Do not start Agent Team on Android." }),
				),
			)
		).plan.tasks.length,
		0,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/delegation/runs?limit=5",
				),
			)
		).items,
	);

	assert.equal(
		(
			await expectJson(
				await focusFetch("http://focus-agent.local/v1/agent/model-router/policy"),
			)
		).enabled,
		true,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/model-router/route",
					jsonBody({ role: "planner" }),
				),
			)
		).decision.model,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/model-router/decisions?limit=5",
				),
			)
		).items,
	);

	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/self-repair/failures?limit=5",
				),
			)
		).items,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/self-repair/promote-preview",
					jsonBody({ failure_ids: ["android-failure"] }),
				),
			)
		).preview,
	);

	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/review-queue?limit=5",
				),
			)
		).items,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/review-queue/android-review/approve",
					jsonBody({}),
				),
			)
		).item.status,
		"approve",
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/review-queue/android-review/reject",
					jsonBody({}),
				),
			)
		).item.status,
		"reject",
	);

	assert.equal(
		(
			await expectJson(
				await focusFetch("http://focus-agent.local/v1/agent/context/policy"),
			)
		).enabled,
		true,
	);
	const contextPreview = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/agent/context/preview",
			jsonBody({
				assembled_context: "Android local context ".repeat(80),
				role: "executor",
				state: { context_budget: { prompt_token_limit: 20, chars_per_token: 4 } },
			}),
		),
	);
	assert.ok(
		contextPreview.decision.budget.prompt_chars > 0,
		"context preview should expose Web panel budget fields",
	);
	assert.ok(
		"estimated_saved_chars" in contextPreview.decision.compression_plan,
		"context preview should expose a compression plan",
	);
	const contextEvidence = await expectJson(
		await focusFetch("http://focus-agent.local/v1/agent/context/evidence"),
	);
	assert.equal(contextEvidence.available, true);
	assert.equal(contextEvidence.backend, "android-local");
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/context/decisions?limit=5",
				),
			)
		).items,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/context/artifacts?limit=5",
				),
			)
		).items,
	);
	const contextExplain = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/agent/context/explain",
			jsonBody({ message: "Why this Android context?" }),
		),
	);
	assert.equal(contextExplain.item.evidence_id, contextExplain.evidence.evidence_id);

	assert.equal(
		(
			await expectJson(
				await focusFetch("http://focus-agent.local/v1/agent/task-ledger/policy"),
			)
		).enabled,
		true,
	);
	const taskLedgerPreview = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/agent/task-ledger/plan",
			jsonBody({ message: "Check Android local parity." }),
		),
	);
	assert.equal(taskLedgerPreview.ledger.tasks.length, 1);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/task-ledger/runs?limit=5",
				),
			)
		).items,
	);

	assert.ok(
		(
			await expectJson(
				await focusFetch("http://focus-agent.local/v1/agent/artifacts?limit=5"),
			)
		).items,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/artifacts/synthesize",
					jsonBody({ message: "Android artifact synthesis preview" }),
				),
			)
		).result,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/critic/verdicts?limit=5",
				),
			)
		).items,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/agent/critic/evaluate",
					jsonBody({ message: "Android critic smoke" }),
				),
			)
		).result.verdict,
		"pass",
	);

	const memoryList = await expectJson(
		await focusFetch("http://focus-agent.local/v1/memory"),
	);
	assert.equal(memoryList.available, true);
	assert.ok(memoryList.items[0]?.memory_id);
	const firstMemoryId = memoryList.items[0].memory_id;
	assert.equal(
		(
			await expectJson(
				await focusFetch(`http://focus-agent.local/v1/memory/${firstMemoryId}`),
			)
		).item.memory_id,
		firstMemoryId,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/memory/${firstMemoryId}/usage`,
				),
			)
		).memory_id,
		firstMemoryId,
	);
	await expectJson(
		await focusFetch(`http://focus-agent.local/v1/memory/${firstMemoryId}/audit`),
	);
	await expectJson(
		await focusFetch("http://focus-agent.local/v1/memory/candidates"),
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/memory/${firstMemoryId}/forget`,
					jsonBody({ reason: "android smoke" }),
				),
			)
		).forgotten,
		true,
	);

	const observabilityOverview = await expectJson(
		await focusFetch("http://focus-agent.local/v1/observability/overview"),
	);
	assert.equal(observabilityOverview.trajectory_available, true);

	const branchDecisionConfig = await expectJson(
		await focusFetch("http://focus-agent.local/v1/branch-decisions/config"),
	);
	assert.equal(branchDecisionConfig.recommendation_user_visible, true);
	assert.equal(branchDecisionConfig.recommendation_mode, "suggest");

	const conversation = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/conversations",
			jsonBody({ title: "Android parity smoke" }),
		),
	);
	const threadId = conversation.root_thread_id;
	assert.ok(
		(
			await expectJson(
				await focusFetch("http://focus-agent.local/v1/conversations"),
			)
		).conversations.some((item) => item.root_thread_id === threadId),
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/conversations/${threadId}`,
					{ ...jsonBody({ title: "Android parity smoke renamed" }), method: "PATCH" },
				),
			)
		).title,
		"Android parity smoke renamed",
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/conversations/${threadId}/archive`,
					jsonBody({}),
				),
			)
		).is_archived,
		true,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/conversations/${threadId}/activate`,
					jsonBody({}),
				),
			)
		).is_archived,
		false,
	);
	assert.equal(
		(await expectJson(await focusFetch(`http://focus-agent.local/v1/threads/${threadId}`)))
			.thread_id,
		threadId,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/threads/${threadId}/resolution`,
				),
			)
		).input_thread_id,
		threadId,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/threads/${threadId}/context/preview`,
					jsonBody({ draft_message: "preview Android context" }),
				),
			)
		).context_usage,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/threads/${threadId}/context/compact`,
					jsonBody({}),
				),
			)
		).thread_id,
		threadId,
	);
	assert.equal(
		(await expectJson(await focusFetch(`http://focus-agent.local/v1/branches/tree/${threadId}`)))
			.root.thread_id,
		threadId,
	);
	const manualBranch = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/branches/fork",
			jsonBody({
				branch_name: "Android manual branch",
				branch_role: "explore_alternatives",
				parent_thread_id: threadId,
			}),
		),
	);
	assert.ok(manualBranch.child_thread_id);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/branches/${manualBranch.child_thread_id}`,
					{
						...jsonBody({ branch_name: "Android manual branch renamed" }),
						method: "PATCH",
					},
				),
			)
		).branch_name,
		"Android manual branch renamed",
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/branches/${manualBranch.child_thread_id}/archive`,
					jsonBody({}),
				),
			)
		).is_archived,
		true,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/branches/${manualBranch.child_thread_id}/activate`,
					jsonBody({}),
				),
			)
		).is_archived,
		false,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/branches/${manualBranch.child_thread_id}/proposal`,
					jsonBody({}),
				),
			)
		).summary,
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/branches/${manualBranch.child_thread_id}/merge`,
					jsonBody({
						approved: true,
						mode: "summary_only",
						rationale: "Android smoke merge",
					}),
				),
			)
		).target_thread_id,
		threadId,
	);

	const searchEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${threadId}/runs/stream`,
			jsonBody({
				message: "今天 Focus Agent Android 有什么最新消息？请联网查一下。",
			}),
		),
	);
	assertLocalStreamContract(searchEvents, threadId);
	assert.ok(
		searchEvents.some(
			(event) =>
				event.event === "tool.call.delta" &&
				event.data.name === "current_utc_time",
		),
		"current_utc_time should emit SDK tool call deltas",
	);
	assert.ok(
		searchEvents.some(
			(event) =>
				event.event === "tool.requested" &&
				event.data.tool_name === "current_utc_time",
		),
		"current_utc_time should be emitted before temporal web search",
	);
	assert.ok(
		searchEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "current_utc_time",
		),
		"current_utc_time result should be emitted",
	);
	assert.ok(
		searchEvents.some(
			(event) =>
				event.event === "tool.call.delta" && event.data.name === "web_search",
		),
		"web_search should emit SDK tool call deltas",
	);
	assert.ok(
		searchEvents.some(
			(event) =>
				event.event === "tool.requested" &&
				event.data.tool_name === "web_search",
		),
		"web_search request should be emitted",
	);
	const searchRequest = searchEvents.find(
		(event) =>
			event.event === "tool.requested" &&
			event.data.tool_name === "web_search",
	);
	assert.ok(
		searchRequest?.data.args?.query.includes("原始查询："),
		"web_search should rewrite the user message into an anchored search query",
	);
	assert.ok(
		searchRequest?.data.args?.query.includes("当前UTC时间："),
		"temporal web_search queries should include the current UTC anchor",
	);
	assert.equal(
		searchRequest?.data.args?.query.includes("请联网查一下"),
		false,
		"web_search query should remove request wrapper text",
	);
	assert.ok(
		searchEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "web_search" &&
				event.data.output?.source === "duckduckgo_html" &&
				event.data.output?.results?.[0]?.url ===
					"https://example.com/focus-agent-android",
		),
		"web_search result should be emitted with normalized DuckDuckGo HTML output",
	);
	const searchReply = searchEvents.find(
		(event) => event.event === "message.completed",
	)?.data?.content;
	assert.ok(
		searchReply?.includes("我已在 Android 本地运行时执行网页搜索"),
		"Android web_search replies should acknowledge the executed local web search",
	);
	assert.equal(
		searchReply?.includes("无法联网"),
		false,
		"Android web_search replies should not deny web access after the tool succeeds",
	);
	assert.equal(
		searchReply?.includes("无法直接获取实时天气数据"),
		false,
		"Android web_search replies should recover from provider real-time data refusals",
	);

	const fetchEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${threadId}/runs/stream`,
			jsonBody({
				message: "请抓取 https://example.com/focus-agent-page 页面内容并总结。",
			}),
		),
	);
	assertLocalStreamContract(fetchEvents, threadId);
	assert.ok(
		fetchEvents.some(
			(event) =>
				event.event === "tool.call.delta" && event.data.name === "web_fetch",
		),
		"web_fetch should emit SDK tool call deltas",
	);
	assert.ok(
		fetchEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "web_fetch" &&
				event.data.output?.source === "android_local_web_fetch" &&
				event.data.output?.content.includes("Fetched Android local runtime"),
		),
		"web_fetch result should be emitted with readable page content",
	);
	const resumeEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${threadId}/runs/resume/stream`,
			jsonBody({ resume: { run_id: "android-resume" } }),
		),
	);
	assertLocalStreamContract(resumeEvents, threadId);
	assert.ok(
		resumeEvents.some((event) => event.event === "run.completed"),
		"streamResume should complete against the Android local runtime",
	);
	assert.deepEqual(
		await collectSse(
			await focusFetch(
				"http://focus-agent.local/v2/runs/android-resume/stream",
				jsonBody({}),
			),
		),
		[],
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v2/runs/android-resume/cancel",
					jsonBody({ action: "interrupt" }),
				),
			)
		).run.status,
		"interrupt",
	);

	const localWriteEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${threadId}/runs/stream`,
			jsonBody({
				message:
					"请保存为产物标题：Android Local Plan 内容：App 本地 artifact 能力，并记住 Android local runtime supports app-local memory.",
			}),
		),
	);
	assertLocalStreamContract(localWriteEvents, threadId);
	assert.ok(
		localWriteEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "write_text_artifact" &&
				event.data.output?.artifact_id,
		),
		"write_text_artifact should execute in Android local runtime",
	);
	assert.ok(
		localWriteEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "memory_save" &&
				event.data.output?.saved === true,
		),
		"memory_save should execute in Android local runtime",
	);

	const localReadEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${threadId}/runs/stream`,
			jsonBody({
				message:
					"请列出产物列表，搜索记忆 Android local runtime，并给我会话摘要，还要搜索技能 web tools。",
			}),
		),
	);
	assertLocalStreamContract(localReadEvents, threadId);
	assert.ok(
		localReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "artifact_list" &&
				event.data.output?.count >= 1,
		),
		"artifact_list should read app-local artifacts",
	);
	assert.ok(
		localReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "memory_search" &&
				event.data.output?.count >= 1,
		),
		"memory_search should read app-local memories",
	);
	assert.ok(
		localReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "conversation_summary" &&
				event.data.output?.thread_id === threadId,
		),
		"conversation_summary should expose local thread context",
	);
	assert.ok(
		localReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "skills_search" &&
				event.data.output?.count >= 1,
		),
		"skills_search should search Android local skills",
	);
	const skillWriteEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${threadId}/runs/stream`,
			jsonBody({
				message:
					"请 skill_install android-local-runtime，然后 skills_refresh_index。",
			}),
		),
	);
	assertLocalStreamContract(skillWriteEvents, threadId);
	assert.ok(
		skillWriteEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "skill_install" &&
				event.data.output?.installed === true,
		),
		"skill_install should work against Android built-in skills",
	);
	assert.ok(
		skillWriteEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "skills_refresh_index" &&
				event.data.output?.refreshed === true,
		),
		"skills_refresh_index should refresh Android built-in skills",
	);

	const workspaceReadEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${threadId}/runs/stream`,
			jsonBody({
				message:
					"请 list_files，并 read_file README.md，再 search_code android，做 codebase_stats，还要 git_status 和 git_log。",
			}),
		),
	);
	assertLocalStreamContract(workspaceReadEvents, threadId);
	assert.ok(
		workspaceReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "list_files" &&
				event.data.output?.results?.includes("README.md"),
		),
		"list_files should list Android app-local workspace files",
	);
	assert.ok(
		workspaceReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "read_file" &&
				event.data.output?.content?.includes(
					"Focus Agent Android Local Workspace",
				),
		),
		"read_file should read Android app-local workspace files",
	);
	assert.ok(
		workspaceReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "search_code" &&
				event.data.output?.count >= 1,
		),
		"search_code should search Android app-local workspace files",
	);
	assert.ok(
		workspaceReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "codebase_stats" &&
				event.data.output?.files_scanned >= 1,
		),
		"codebase_stats should inspect Android app-local workspace files",
	);
	assert.ok(
		workspaceReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "git_status" &&
				event.data.output?.branch === "android-local",
		),
		"git_status should inspect Android app-local workspace status",
	);
	assert.ok(
		workspaceReadEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "git_log" &&
				event.data.output?.count >= 1,
		),
		"git_log should return Android app-local workspace commits",
	);

	const workspaceWriteEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${threadId}/runs/stream`,
			jsonBody({
				message:
					"请 apply_patch 到 README.md，然后 git_diff，再 run_workspace_command `rg Patched`。",
			}),
		),
	);
	assertLocalStreamContract(workspaceWriteEvents, threadId);
	assert.ok(
		workspaceWriteEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "apply_patch" &&
				event.data.output?.applied === true,
		),
		"apply_patch should update Android app-local workspace files",
	);
	assert.ok(
		workspaceWriteEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "git_diff" &&
				event.data.output?.diff?.includes("Patched from Android local runtime"),
		),
		"git_diff should include Android app-local workspace changes",
	);
	assert.ok(
		workspaceWriteEvents.some(
			(event) =>
				event.event === "tool.result" &&
				event.data.tool_name === "run_workspace_command" &&
				event.data.output?.stdout?.includes(
					"Patched from Android local runtime",
				),
		),
		"run_workspace_command should run safe Android app-local command simulations",
	);

	const disabledToolConfig = await expectJson(
		await focusFetch("http://focus-agent.local/v1/admin/config/tools", {
			...jsonBody({
				tools: [
					{
						name: "web_fetch",
						enabled: true,
					},
					{
						name: "web_search",
						enabled: false,
						settings: adminConfig.tools.tools[1].settings,
					},
					{
						name: "current_utc_time",
						enabled: true,
					},
					{
						name: "productivity_capture",
						enabled: true,
					},
				],
			}),
			method: "PATCH",
		}),
	);
	assertAdminConfigContract(disabledToolConfig);
	assert.equal(
		disabledToolConfig.tools.tools.find((tool) => tool.name === "web_search")
			?.enabled,
		false,
	);
	const disabledCapabilities = await expectJson(
		await focusFetch("http://focus-agent.local/v1/agent/capabilities"),
	);
	assert.equal(
		disabledCapabilities.items.some((tool) => tool.name === "web_search"),
		false,
	);
	const toolRoute = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/agent/tool-router/route",
			jsonBody({
				available_tools: ["web_search", "current_utc_time", "notes_create"],
			}),
		),
	);
	assert.deepEqual(toolRoute.plan.allowed_tools, ["current_utc_time"]);
	assert.deepEqual(toolRoute.plan.denied_tools, ["web_search", "notes_create"]);
	assert.deepEqual(
		toolRoute.plan.decisions.map((decision) => decision.name),
		["current_utc_time", "web_search", "notes_create"],
	);
	const disabledSearchEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${threadId}/runs/stream`,
			jsonBody({
				message: "Please search the web for current Android runtime news.",
			}),
		),
	);
	assertLocalStreamContract(disabledSearchEvents, threadId);
	assert.equal(
		disabledSearchEvents.some(
			(event) =>
				event.event === "tool.requested" &&
				event.data.tool_name === "web_search",
		),
		false,
		"disabled web_search should not run",
	);

	const branchConversation = await expectJson(
		await focusFetch(
			"http://focus-agent.local/v1/conversations",
			jsonBody({ title: "Android branch recommendation smoke" }),
		),
	);
	const branchThreadId = branchConversation.root_thread_id;
	const branchEvents = await collectSse(
		await focusFetch(
			`http://focus-agent.local/v2/threads/${branchThreadId}/runs/stream`,
			jsonBody({
				message:
					"另外单独开新分支讨论 Android 发布计划，这和刚才搜索不是同一个主题。",
			}),
		),
	);
	assertLocalStreamContract(branchEvents, branchThreadId);
	const completed = branchEvents.find(
		(event) => event.event === "run.completed",
	);
	assert.equal(completed?.data.branch_decision?.status, "promoted");
	assert.equal(completed?.data.branch_action?.source, "branch_decision");
	assert.equal(completed?.data.branch_action?.status, "pending");
	assert.equal(
		completed?.data.thread_state?.branch_decision_summary?.latest_decision
			?.recommendation_user_visible,
		true,
	);

	const decisions = await expectJson(
		await focusFetch(
			`http://focus-agent.local/v1/threads/${branchThreadId}/branch-decisions?limit=5`,
		),
	);
	assert.equal(
		(await sdkClient.getBranchDecisionConfig()).recommendation_user_visible,
		true,
	);
	assert.equal(
		(await sdkClient.listThreadBranchDecisions(branchThreadId, { limit: 5 }))
			.items[0].decision_id,
		decisions.items[0].decision_id,
	);
	assert.equal(decisions.items[0].status, "promoted");
	assert.equal(
		decisions.items[0].promoted_action_id,
		completed.data.branch_action.action_id,
	);

	const executed = await expectJson(
		await focusFetch(
			`http://focus-agent.local/v1/threads/${branchThreadId}/branch-actions/${completed.data.branch_action.action_id}/execute`,
			jsonBody({}),
		),
	);
	assert.equal(executed.branch_action.status, "executed");
	assert.ok(executed.navigation?.thread_id);
	assert.ok(executed.branch_record?.child_thread_id);
	assert.equal(
		(
			await sdkClient.executeBranchAction(
				branchThreadId,
				completed.data.branch_action.action_id,
			)
		).branch_action.status,
		"executed",
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/threads/${branchThreadId}/branch-actions/${completed.data.branch_action.action_id}/dismiss`,
					jsonBody({}),
				),
			)
		).branch_actions.find(
			(action) => action.action_id === completed.data.branch_action.action_id,
		)?.status,
		"dismissed",
	);
	assert.equal(
		(
			await sdkClient.dismissBranchAction(
				branchThreadId,
				completed.data.branch_action.action_id,
			)
		).branch_actions.find(
			(action) => action.action_id === completed.data.branch_action.action_id,
		)?.status,
		"dismissed",
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/threads/${branchThreadId}/branch-decisions/${decisions.items[0].decision_id}/promote`,
					jsonBody({}),
				),
			)
		).status,
		"promoted",
	);
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/threads/${branchThreadId}/branch-decisions/${decisions.items[0].decision_id}/dismiss`,
					jsonBody({ reason: "android smoke" }),
				),
			)
		).status,
		"dismissed",
	);
	assert.equal(
		(
			await sdkClient.promoteBranchDecision(
				branchThreadId,
				decisions.items[0].decision_id,
			)
		).status,
		"promoted",
	);
	assert.equal(
		(
			await sdkClient.dismissBranchDecision(
				branchThreadId,
				decisions.items[0].decision_id,
				{ reason: "android sdk smoke" },
			)
		).status,
		"dismissed",
	);

	const trajectories = await expectJson(
		await focusFetch("http://focus-agent.local/v1/observability/trajectory"),
	);
	assert.ok(trajectories.count > 0);
	assert.ok(
		(
			await expectJson(
				await focusFetch("http://focus-agent.local/v1/observability/trajectory/stats"),
			)
		).stats,
	);
	const turnId = trajectories.items[0].id;
	assert.equal(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/observability/trajectory/${turnId}`,
				),
			)
		).item.id,
		turnId,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/observability/trajectory/${turnId}/replay`,
					jsonBody({ model: "deepseek-v4-pro" }),
				),
			)
		).replay_result,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					`http://focus-agent.local/v1/observability/trajectory/${turnId}/promote`,
					jsonBody({}),
				),
			)
		).case_id,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/observability/trajectory/batch/promote-preview",
					jsonBody({ turn_ids: [turnId] }),
				),
			)
		).items,
	);
	assert.ok(
		(
			await expectJson(
				await focusFetch(
					"http://focus-agent.local/v1/observability/trajectory/batch/replay-compare",
					jsonBody({ turn_ids: [turnId] }),
				),
			)
		).summary,
	);
	assert.ok(await sdkClient.revokeSession(authSessions.items[0].session_id));
	assert.ok(
		await sdkClient.revokeUserSession(principal.user.user_id, {
			session_id: adminUserSessions.items[0].session_id,
		}),
	);
	const sdkForgetList = await sdkClient.listMemoryRecords({ limit: 5 });
	assert.equal(
		(await sdkClient.forgetMemoryRecord(sdkForgetList.items[0].memory_id, {
			reason: "android sdk final forget",
		})).forgotten,
		true,
	);
} finally {
	await rm(smokeBuildDir, { force: true, recursive: true });
	globalThis.fetch = originalFetch;
}
