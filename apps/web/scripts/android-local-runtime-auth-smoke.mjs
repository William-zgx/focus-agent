import assert from "node:assert/strict";
import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

class MemoryStorage {
	#values = new Map();
	#writeError = null;

	clear() {
		this.#values.clear();
		this.#writeError = null;
	}

	failNextWrite(error) {
		this.#writeError = error;
	}

	getItem(key) {
		return this.#values.has(key) ? this.#values.get(key) : null;
	}

	removeItem(key) {
		this.#values.delete(key);
	}

	setItem(key, value) {
		if (this.#writeError) {
			const error = this.#writeError;
			this.#writeError = null;
			throw error;
		}
		this.#values.set(key, String(value));
	}
}

const localStorage = new MemoryStorage();
globalThis.window = {
	localStorage,
	location: { origin: "http://focus-agent.local" },
};
globalThis.localStorage = localStorage;

const require = createRequire(import.meta.url);
const ts = require("../node_modules/typescript");
const appRoot = resolve(import.meta.dirname, "..");
const runtimeSourceDir = resolve(appRoot, "src/android-local-runtime");
const smokeBuildDir = resolve(appRoot, ".android-local-runtime-auth-smoke");

function rewriteTranspiledLocalImports(outputText, sourceNames) {
	return outputText.replace(
		/from\s+(["'])(\.\/[^"']+)\1/g,
		(match, quote, specifier) => {
			const sourceName = `${specifier.slice(2)}.ts`;
			return sourceNames.has(sourceName)
				? `from ${quote}${specifier}.mjs${quote}`
				: match;
		},
	);
}

async function transpileRuntimeModules() {
	const sourceNames = new Set(
		(await readdir(runtimeSourceDir)).filter((name) => name.endsWith(".ts")),
	);
	await mkdir(smokeBuildDir, { recursive: true });
	for (const sourceName of sourceNames) {
		const sourcePath = resolve(runtimeSourceDir, sourceName);
		const source = (await readFile(sourcePath, "utf8")).replace(
			/\bimport\.meta\.env\./g,
			"process.env.",
		);
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
			rewriteTranspiledLocalImports(result.outputText, sourceNames),
		);
	}
}

async function expectStatus(response, status) {
	if (response.status !== status) {
		assert.fail(
			`Expected ${status}, received ${response.status}: ${await response.text()}`,
		);
	}
}

async function expectUnsupported(response, status) {
	await expectStatus(response, status);
	const body = await response.json();
	assert.match(
		body.detail?.message ?? "",
		/device-local single-user|Administrative and user-governance/i,
	);
}

async function request(runtime, path, init) {
	return runtime.fetch(`http://focus-agent.local${path}`, init);
}

function persistLegacyModelSecret(LocalFocusAgentRuntime, storageKey, apiKey) {
	const legacyRuntime = new LocalFocusAgentRuntime({
		read: async () => ({}),
		write: async () => undefined,
	});
	legacyRuntime.state.modelSecrets = { deepseek: { apiKey } };
	localStorage.setItem(storageKey, JSON.stringify(legacyRuntime.state));
}

try {
	await rm(smokeBuildDir, { force: true, recursive: true });
	await transpileRuntimeModules();
	const { LocalFocusAgentRuntime } = await import(
		`${pathToFileURL(resolve(smokeBuildDir, "local-focus-agent-runtime.mjs")).href}?t=${Date.now()}`
	);
	const { STORAGE_KEY } = await import(
		`${pathToFileURL(resolve(smokeBuildDir, "constants.mjs")).href}?t=${Date.now()}`
	);

	localStorage.clear();
	persistLegacyModelSecret(
		LocalFocusAgentRuntime,
		STORAGE_KEY,
		"legacy-success-key",
	);
	let successfulSecureWrite;
	const successfulMigration = new LocalFocusAgentRuntime({
		read: async () => ({}),
		write: async (secrets) => {
			const stateDuringSecureWrite = JSON.parse(
				localStorage.getItem(STORAGE_KEY),
			);
			assert.equal(
				stateDuringSecureWrite.modelSecrets.deepseek.apiKey,
				"legacy-success-key",
				"legacy state must remain until secure storage succeeds",
			);
			successfulSecureWrite = structuredClone(secrets);
		},
	});
	await successfulMigration.ensureSecrets();
	assert.equal(successfulSecureWrite.deepseek.apiKey, "legacy-success-key");
	assert.equal(successfulMigration.state.modelSecrets, undefined);
	assert.equal(
		JSON.stringify(JSON.parse(localStorage.getItem(STORAGE_KEY))).includes(
			"legacy-success-key",
		),
		false,
	);

	localStorage.clear();
	persistLegacyModelSecret(
		LocalFocusAgentRuntime,
		STORAGE_KEY,
		"legacy-retry-key",
	);
	let secureWriteAttempts = 0;
	const retryingMigration = new LocalFocusAgentRuntime({
		read: async () => ({}),
		write: async (secrets) => {
			secureWriteAttempts += 1;
			assert.equal(secrets.deepseek.apiKey, "legacy-retry-key");
			if (secureWriteAttempts === 1) {
				throw new Error("injected secure storage failure");
			}
			const stateDuringRetry = JSON.parse(localStorage.getItem(STORAGE_KEY));
			assert.equal(
				stateDuringRetry.modelSecrets.deepseek.apiKey,
				"legacy-retry-key",
			);
		},
	});
	await assert.rejects(
		retryingMigration.ensureSecrets(),
		/injected secure storage failure/,
	);
	assert.equal(secureWriteAttempts, 1);
	assert.equal(
		retryingMigration.state.modelSecrets.deepseek.apiKey,
		"legacy-retry-key",
	);
	assert.equal(
		JSON.parse(localStorage.getItem(STORAGE_KEY)).modelSecrets.deepseek.apiKey,
		"legacy-retry-key",
		"failed secure writes must preserve the retryable legacy key",
	);
	retryingMigration.persist();
	assert.equal(
		JSON.parse(localStorage.getItem(STORAGE_KEY)).modelSecrets.deepseek.apiKey,
		"legacy-retry-key",
		"ordinary state persistence must not erase a failed migration",
	);
	await retryingMigration.ensureSecrets();
	assert.equal(secureWriteAttempts, 2);
	assert.equal(retryingMigration.state.modelSecrets, undefined);
	assert.equal(
		JSON.stringify(JSON.parse(localStorage.getItem(STORAGE_KEY))).includes(
			"legacy-retry-key",
		),
		false,
	);

	localStorage.clear();
	persistLegacyModelSecret(
		LocalFocusAgentRuntime,
		STORAGE_KEY,
		"legacy-cleanup-retry-key",
	);
	let cleanupSecureWriteAttempts = 0;
	const cleanupRetryingMigration = new LocalFocusAgentRuntime({
		read: async () => ({}),
		write: async () => {
			cleanupSecureWriteAttempts += 1;
		},
	});
	localStorage.failNextWrite(new Error("injected legacy cleanup failure"));
	await assert.rejects(
		cleanupRetryingMigration.ensureSecrets(),
		/injected legacy cleanup failure/,
	);
	assert.equal(cleanupSecureWriteAttempts, 1);
	assert.equal(
		cleanupRetryingMigration.state.modelSecrets.deepseek.apiKey,
		"legacy-cleanup-retry-key",
	);
	assert.equal(
		JSON.parse(localStorage.getItem(STORAGE_KEY)).modelSecrets.deepseek.apiKey,
		"legacy-cleanup-retry-key",
	);
	await cleanupRetryingMigration.ensureSecrets();
	assert.equal(cleanupSecureWriteAttempts, 2);
	assert.equal(cleanupRetryingMigration.state.modelSecrets, undefined);
	assert.equal(
		JSON.stringify(JSON.parse(localStorage.getItem(STORAGE_KEY))).includes(
			"legacy-cleanup-retry-key",
		),
		false,
	);

	localStorage.clear();
	const initialRuntime = new LocalFocusAgentRuntime();
	initialRuntime.persist();
	const legacyState = JSON.parse(localStorage.getItem(STORAGE_KEY));
	legacyState.version = 1;
	legacyState.users = [
		{
			...legacyState.users[0],
			display_name: "Android Local Admin",
			roles: ["admin"],
			user_id: "android-local-admin",
		},
		{
			...legacyState.users[0],
			user_id: "unexpected-user",
			roles: ["admin"],
		},
	];
	legacyState.sessions = [
		{
			session_id: "local-session-0001",
			user_id: "android-local-admin",
			created_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
			expires_at: new Date(Date.now() + 86400000).toISOString(),
			metadata: { runtime: "android-local" },
			current: true,
		},
	];
	localStorage.setItem(STORAGE_KEY, JSON.stringify(legacyState));

	const runtime = new LocalFocusAgentRuntime();
	assert.equal(runtime.state.version, 2);
	assert.equal(runtime.state.accessMode, "device-local-single-user");
	assert.deepEqual(runtime.state.sessions, []);
	assert.equal(runtime.state.users.length, 1);
	assert.equal(runtime.state.users[0].user_id, "android-local-user");
	assert.deepEqual(runtime.state.users[0].roles, []);
	assert.equal(
		JSON.stringify(JSON.parse(localStorage.getItem(STORAGE_KEY))).includes(
			"android-local-token",
		),
		false,
	);

	const principalResponse = await request(runtime, "/v1/auth/me");
	await expectStatus(principalResponse, 200);
	const principal = await principalResponse.json();
	assert.equal(principal.auth_enabled, false);
	assert.equal(principal.is_admin, false);
	assert.deepEqual(principal.roles, []);
	assert.deepEqual(principal.scopes, [
		"chat",
		"branches",
		"device-local-config",
	]);
	assert.deepEqual(principal.permissions, [
		"chat:write",
		"branches:write",
		"device-local:configure",
	]);
	assert.equal(principal.user.metadata.device_local_configuration, true);

	await expectUnsupported(
		await request(runtime, "/v1/auth/me", {
			headers: { Authorization: "Bearer wrong-token" },
		}),
		401,
	);
	for (const [path, init] of [
		[
			"/v1/auth/login",
			{
				body: JSON.stringify({ password: "wrong", username: "any-user" }),
				headers: { "Content-Type": "application/json" },
				method: "POST",
			},
		],
		[
			"/v1/auth/register",
			{
				body: JSON.stringify({
					password: "new-password",
					username: "new-user",
				}),
				headers: { "Content-Type": "application/json" },
				method: "POST",
			},
		],
		["/v1/auth/demo-token", { method: "POST" }],
		["/v1/auth/refresh", { method: "POST" }],
		["/v1/auth/change-password", { method: "POST" }],
		["/v1/auth/sessions", undefined],
		["/v1/auth/sessions/local-session-0001/revoke", { method: "POST" }],
		["/v1/auth/logout", { method: "POST" }],
	]) {
		await expectUnsupported(await request(runtime, path, init), 403);
	}

	assert.deepEqual(
		runtime.state.sessions,
		[],
		"logout cannot pretend to revoke a nonexistent local session",
	);
	assert.deepEqual(runtime.state.users[0].roles, []);
	const localConfigResponse = await request(runtime, "/v1/admin/config");
	await expectStatus(localConfigResponse, 200);
	assert.ok((await localConfigResponse.json()).models.providers.length > 0);
	await expectStatus(
		await request(runtime, "/v1/admin/config/policies", {
			body: JSON.stringify({
				values: { auth_smoke_device_local_configuration: true },
			}),
			headers: { "Content-Type": "application/json" },
			method: "PATCH",
		}),
		200,
	);
	assert.equal(
		runtime.state.adminConfig.policies.items[0]?.key,
		"auth_smoke_device_local_configuration",
	);
	for (const path of ["/v1/admin/users", "/v1/admin/audit-events"]) {
		await expectUnsupported(await request(runtime, path), 403);
	}
	await expectUnsupported(
		await request(runtime, "/v1/admin/users", {
			headers: { Authorization: "Bearer wrong-token" },
		}),
		401,
	);

	localStorage.clear();
	const pmClearRuntime = new LocalFocusAgentRuntime();
	assert.equal(pmClearRuntime.state.version, 2);
	assert.equal(pmClearRuntime.state.accessMode, "device-local-single-user");
	assert.deepEqual(pmClearRuntime.state.sessions, []);
	assert.deepEqual(pmClearRuntime.currentUser().roles, []);
	const pmClearPrincipal = await request(pmClearRuntime, "/v1/auth/me");
	await expectStatus(pmClearPrincipal, 200);
	assert.equal((await pmClearPrincipal.json()).is_admin, false);

	console.log("Android local runtime auth smoke passed.");
} finally {
	await rm(smokeBuildDir, { force: true, recursive: true });
}
