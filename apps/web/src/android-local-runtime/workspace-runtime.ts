import { clone, stringValue } from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import { afterCue } from "./local-text";
import { defaultWorkspaceFiles } from "./state";

export function workspaceFiles(
	ctx: LocalFocusAgentRuntime,
): Record<string, string> {
	ctx.state.workspaceFiles ??= defaultWorkspaceFiles();
	return ctx.state.workspaceFiles;
}

export function workspaceBaseFiles(
	ctx: LocalFocusAgentRuntime,
): Record<string, string> {
	ctx.state.workspaceBaseFiles ??= clone(ctx.workspaceFiles());
	return ctx.state.workspaceBaseFiles;
}

export function normalizeWorkspacePath(
	_ctx: LocalFocusAgentRuntime,
	value: unknown,
): string | null {
	const raw = stringValue(value).trim() || ".";
	if (raw.startsWith("/") || raw.includes("\0")) return null;
	const parts: string[] = [];
	for (const part of raw.split("/")) {
		if (!part || part === ".") continue;
		if (part === "..") return null;
		parts.push(part);
	}
	return parts.join("/") || ".";
}

export function localWorkspacePathFromMessage(
	_ctx: LocalFocusAgentRuntime,
	message: string,
): string | null {
	return message.match(/[\p{Letter}\p{Number}_./-]+\.[a-z0-9]+/iu)?.[0] ?? null;
}

export function localPatchFromMessage(
	ctx: LocalFocusAgentRuntime,
	message: string,
): string {
	const fenced = message.match(/```(?:diff|patch)?\s*([\s\S]*?)```/i)?.[1];
	if (fenced?.includes("diff --git")) return fenced.trim();
	const target = ctx.localWorkspacePathFromMessage(message) ?? "README.md";
	const normalizedTarget = ctx.normalizeWorkspacePath(target) ?? "README.md";
	return [
		`diff --git a/${normalizedTarget} b/${normalizedTarget}`,
		`--- a/${normalizedTarget}`,
		`+++ b/${normalizedTarget}`,
		"@@ -1,3 +1,4 @@",
		" # Focus Agent Android Local Workspace",
		" ",
		"+Patched from Android local runtime.",
		" This is an app-local virtual workspace used when Focus Agent runs on Android without a backend.",
		"",
	].join("\n");
}

export function localCommandFromMessage(
	_ctx: LocalFocusAgentRuntime,
	message: string,
): string[] {
	const fenced = message.match(/`([^`]+)`/)?.[1];
	const raw =
		fenced ??
		afterCue(message, [
			"run_workspace_command",
			"workspace command",
			"运行工作区命令",
			"执行命令",
		]) ??
		"ls";
	return raw.trim().split(/\s+/).filter(Boolean).slice(0, 8);
}

export function workspaceFileEntries(
	ctx: LocalFocusAgentRuntime,
	pathValue: unknown = ".",
) {
	const path = ctx.normalizeWorkspacePath(pathValue) ?? ".";
	const prefix = path === "." ? "" : `${path.replace(/\/$/, "")}/`;
	return Object.entries(ctx.workspaceFiles())
		.filter(
			([filePath]) =>
				path === "." || filePath === path || filePath.startsWith(prefix),
		)
		.sort(([left], [right]) => left.localeCompare(right));
}

export function languageForPath(
	_ctx: LocalFocusAgentRuntime,
	path: string,
): string {
	if (path.endsWith(".ts") || path.endsWith(".tsx")) return "TypeScript";
	if (path.endsWith(".js") || path.endsWith(".jsx")) return "JavaScript";
	if (path.endsWith(".py")) return "Python";
	if (path.endsWith(".md")) return "Markdown";
	if (path.endsWith(".json")) return "JSON";
	return "Text";
}

export function fileDiff(
	_ctx: LocalFocusAgentRuntime,
	path: string,
	before = "",
	after = "",
): string {
	if (before === after) return "";
	const beforeLines = before.split("\n");
	const afterLines = after.split("\n");
	const lines = [
		`diff --git a/${path} b/${path}`,
		before ? `--- a/${path}` : "--- /dev/null",
		after ? `+++ b/${path}` : "+++ /dev/null",
		`@@ -1,${Math.max(1, beforeLines.length)} +1,${Math.max(1, afterLines.length)} @@`,
		...beforeLines
			.filter((line, index) => line !== afterLines[index])
			.map((line) => `-${line}`),
		...afterLines
			.filter((line, index) => line !== beforeLines[index])
			.map((line) => `+${line}`),
	];
	return lines.join("\n");
}

export function workspaceDiff(
	ctx: LocalFocusAgentRuntime,
	pathspec?: unknown,
): string {
	const normalizedPathspec = ctx.normalizeWorkspacePath(pathspec ?? ".");
	const baseFiles = ctx.workspaceBaseFiles();
	const currentFiles = ctx.workspaceFiles();
	const allPaths = [
		...new Set([...Object.keys(baseFiles), ...Object.keys(currentFiles)]),
	].sort();
	return allPaths
		.filter(
			(path) =>
				!normalizedPathspec ||
				normalizedPathspec === "." ||
				path === normalizedPathspec ||
				path.startsWith(`${normalizedPathspec}/`),
		)
		.map((path) =>
			ctx.fileDiff(path, baseFiles[path] ?? "", currentFiles[path] ?? ""),
		)
		.filter(Boolean)
		.join("\n");
}

export function workspaceStatusEntries(ctx: LocalFocusAgentRuntime): string[] {
	const baseFiles = ctx.workspaceBaseFiles();
	const currentFiles = ctx.workspaceFiles();
	const allPaths = [
		...new Set([...Object.keys(baseFiles), ...Object.keys(currentFiles)]),
	].sort();
	return allPaths.flatMap((path) => {
		if (!(path in baseFiles)) return [`?? ${path}`];
		if (!(path in currentFiles)) return [` D ${path}`];
		if (baseFiles[path] !== currentFiles[path]) return [` M ${path}`];
		return [];
	});
}

export function applyPatchToWorkspace(
	ctx: LocalFocusAgentRuntime,
	patch: string,
): string[] {
	if (patch.length > 20000)
		throw new Error("patch exceeds Android local limit.");
	if (
		/new file mode 120000|new file mode 160000|Subproject commit/i.test(patch)
	) {
		throw new Error("Symlink and submodule patches are not supported.");
	}
	const changedFiles: string[] = [];
	const fileSections = patch.split(/^diff --git /m).filter(Boolean);
	for (const rawSection of fileSections) {
		const section = `diff --git ${rawSection}`;
		const path = ctx.normalizeWorkspacePath(
			section.match(/^\+\+\+ b\/(.+)$/m)?.[1],
		);
		if (!path || path === ".")
			throw new Error("Patch path must stay inside workspace root.");
		const original = ctx.workspaceFiles()[path] ?? "";
		const originalLines = original.split("\n");
		const outputLines: string[] = [];
		let cursor = 0;
		const hunkMatches = [
			...section.matchAll(/^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@.*$/gm),
		];
		if (hunkMatches.length === 0) continue;
		for (let hunkIndex = 0; hunkIndex < hunkMatches.length; hunkIndex += 1) {
			const match = hunkMatches[hunkIndex];
			const start = Math.max(0, Number(match[1]) - 1);
			outputLines.push(...originalLines.slice(cursor, start));
			cursor = start;
			const hunkStart = (match.index ?? 0) + match[0].length + 1;
			const hunkEnd = hunkMatches[hunkIndex + 1]?.index ?? section.length;
			const hunkLines = section.slice(hunkStart, hunkEnd).split(/\r?\n/);
			for (const line of hunkLines) {
				if (!line) continue;
				const marker = line[0];
				const text = line.slice(1);
				if (marker === " ") {
					outputLines.push(originalLines[cursor] ?? text);
					cursor += 1;
				} else if (marker === "-") {
					cursor += 1;
				} else if (marker === "+") {
					outputLines.push(text);
				}
			}
		}
		outputLines.push(...originalLines.slice(cursor));
		ctx.workspaceFiles()[path] =
			`${outputLines.join("\n").replace(/\n+$/u, "")}\n`;
		changedFiles.push(path);
	}
	return changedFiles;
}
