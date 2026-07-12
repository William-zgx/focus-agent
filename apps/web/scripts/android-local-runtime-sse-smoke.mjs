import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const NativeReadableStream = globalThis.ReadableStream;
const streamRecords = [];

class TrackingReadableStream extends NativeReadableStream {
	constructor(source, strategy) {
		const record = {
			cancelCalls: 0,
			closeCalls: 0,
			errorCalls: 0,
			invalidCloseCalls: 0,
			invalidErrorCalls: 0,
			cancelled: false,
		};
		streamRecords.push(record);
		super(
			{
				cancel(reason) {
					record.cancelCalls += 1;
					record.cancelled = true;
					return source.cancel?.(reason);
				},
				start(controller) {
					const close = controller.close.bind(controller);
					const error = controller.error.bind(controller);
					controller.close = () => {
						record.closeCalls += 1;
						if (record.cancelled) {
							record.invalidCloseCalls += 1;
							return;
						}
						return close();
					};
					controller.error = (reason) => {
						record.errorCalls += 1;
						if (record.cancelled) {
							record.invalidErrorCalls += 1;
							return;
						}
						return error(reason);
					};
					return source.start?.(controller);
				},
			},
			strategy,
		);
	}
}

globalThis.ReadableStream = TrackingReadableStream;

const require = createRequire(import.meta.url);
const ts = require("../node_modules/typescript");
const appRoot = resolve(import.meta.dirname, "..");
const smokeBuildDir = resolve(appRoot, ".android-local-runtime-sse-smoke");

function wait(milliseconds) {
	return new Promise((resolvePromise) =>
		setTimeout(resolvePromise, milliseconds),
	);
}

function event(id, name) {
	return {
		id,
		event: name,
		data: { run_id: "local-run-smoke", status: "completed" },
	};
}

async function transpile(sourceName) {
	const sourcePath = resolve(appRoot, "src/android-local-runtime", sourceName);
	const source = await readFile(sourcePath, "utf8");
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
		result.outputText.replace(
			/from\s+(["'])\.\/constants\1/g,
			'from "./constants.mjs"',
		),
	);
}

function currentRecord() {
	const record = streamRecords.at(-1);
	assert.ok(record, "Expected an SSE stream record.");
	return record;
}

function assertNoSecondTerminalOperation(record) {
	assert.equal(record.invalidCloseCalls, 0);
	assert.equal(record.invalidErrorCalls, 0);
}

try {
	await rm(smokeBuildDir, { force: true, recursive: true });
	await mkdir(smokeBuildDir, { recursive: true });
	await Promise.all([transpile("constants.ts"), transpile("sse.ts")]);

	const { sseResponse } = await import(
		`${pathToFileURL(resolve(smokeBuildDir, "sse.mjs")).href}?t=${Date.now()}`
	);

	{
		const response = sseResponse([event("terminal", "run.completed")]);
		assert.equal(response.headers.get("Cache-Control"), "no-cache");
		assert.equal(response.headers.get("Content-Type"), "text/event-stream");
		const reader = response.body.getReader();
		const frame = await reader.read();
		assert.equal(frame.done, false);
		assert.match(
			new TextDecoder().decode(frame.value),
			/event: run\.completed/,
		);
		await reader.cancel("terminal event consumed");
		await wait(50);

		const record = currentRecord();
		assert.equal(record.cancelCalls, 1);
		assert.equal(record.closeCalls, 0);
		assert.equal(record.errorCalls, 0);
		assertNoSecondTerminalOperation(record);
	}

	{
		const response = sseResponse([
			event("metadata", "run.metadata"),
			event("completed", "run.completed"),
		]);
		const reader = response.body.getReader();
		const frames = [];
		for (;;) {
			const frame = await reader.read();
			if (frame.done) break;
			frames.push(new TextDecoder().decode(frame.value));
		}

		assert.equal(frames.length, 2);
		assert.match(frames[1], /event: run\.completed/);
		const record = currentRecord();
		assert.equal(record.cancelCalls, 0);
		assert.equal(record.closeCalls, 1);
		assert.equal(record.errorCalls, 0);
		assertNoSecondTerminalOperation(record);
	}

	{
		const controller = new AbortController();
		const abortReason = new DOMException("Stopped", "AbortError");
		const response = sseResponse(
			[event("metadata", "run.metadata"), event("completed", "run.completed")],
			controller.signal,
		);
		const reader = response.body.getReader();
		assert.equal((await reader.read()).done, false);
		controller.abort(abortReason);
		await assert.rejects(reader.read(), (error) => error === abortReason);
		await wait(50);

		const record = currentRecord();
		assert.equal(record.cancelCalls, 0);
		assert.equal(record.closeCalls, 0);
		assert.equal(record.errorCalls, 1);
		assertNoSecondTerminalOperation(record);
	}

	console.log("Android local runtime SSE smoke passed.");
} finally {
	globalThis.ReadableStream = NativeReadableStream;
	await rm(smokeBuildDir, { force: true, recursive: true });
}
