import type {
	LocalToolExecution,
	LocalWebFetchResult,
	LocalWebSearchResult,
} from "./types";

export function localReply(message: string): string {
	const trimmedMessage = message.trim();
	const isChinese = /[\u3400-\u9fff]/.test(trimmedMessage);
	if (isChinese) {
		return [
			"本地 Android 运行时已处理这条消息。",
			"",
			trimmedMessage
				? `你刚才说：${trimmedMessage}`
				: "这次请求没有包含新的用户消息。",
			"",
			"当前构建不会连接 Focus Agent 后端；对话、分支、账号和管理数据都保存在 App 本地。",
		].join("\n");
	}
	return [
		"The Android local runtime handled this turn.",
		"",
		trimmedMessage
			? `You said: ${trimmedMessage}`
			: "This request did not include a new user message.",
		"",
		"This build does not connect to the Focus Agent backend; chat, branch, account, and admin data stay inside the app.",
	].join("\n");
}

export function splitText(text: string, maxChunkLength = 48): string[] {
	const chunks: string[] = [];
	for (let index = 0; index < text.length; index += maxChunkLength) {
		chunks.push(text.slice(index, index + maxChunkLength));
	}
	return chunks.length ? chunks : [""];
}

export function textWords(text: string): string[] {
	const normalized = text.toLowerCase();
	const latinTerms = normalized.match(/[a-z0-9][a-z0-9_-]{2,}/g) ?? [];
	const hanChars = normalized.match(/\p{Script=Han}/gu) ?? [];
	const hanTerms = hanChars.flatMap((char, index) =>
		hanChars[index + 1] ? [`${char}${hanChars[index + 1]}`] : [],
	);
	return [...new Set([...latinTerms, ...hanTerms])];
}

export function containsAny(text: string, patterns: string[]): boolean {
	const normalized = text.toLowerCase();
	return patterns.some((pattern) => normalized.includes(pattern));
}

export function suggestedBranchName(
	message: string,
	isChinese: boolean,
): string {
	const compact = message.replace(/\s+/g, " ").trim();
	if (!compact) return isChinese ? "本地分支" : "Local branch";
	const prefix = isChinese ? "探索：" : "Explore: ";
	return `${prefix}${compact.slice(0, 48)}`;
}

export function localBranchHandoffMessage(message: string): string | null {
	const compact = message.replace(/\s+/g, " ").trim();
	return compact || null;
}

export function slugifyArtifactTitle(title: string): string {
	const cleaned = title
		.trim()
		.toLowerCase()
		.replace(/[^\p{Letter}\p{Number}\s_-]+/gu, "")
		.replace(/\s+/g, "-")
		.replace(/-+/g, "-")
		.replace(/^-|-$/g, "");
	return `${cleaned || "artifact"}.md`;
}

export function quotedText(message: string): string | null {
	const match =
		message.match(/["“”']([^"“”']{2,})["“”']/u) ??
		message.match(/《([^》]{2,})》/u);
	return match?.[1]?.trim() ?? null;
}

export function afterCue(message: string, cues: string[]): string | null {
	const normalized = message.replace(/\s+/g, " ").trim();
	for (const cue of cues) {
		const index = normalized.toLowerCase().indexOf(cue.toLowerCase());
		if (index < 0) continue;
		const value = normalized.slice(index + cue.length).trim();
		if (value) return value;
	}
	return null;
}

function compactWebSearchSummary(result: LocalWebSearchResult): string {
	const lines = result.results.slice(0, 3).map((item, index) => {
		const url = item.url ? ` (${item.url})` : "";
		return `${index + 1}. ${item.title}${url}: ${item.snippet}`;
	});
	return [result.answer, ...lines].filter(Boolean).join("\n");
}

function compactWebFetchSummary(result: LocalWebFetchResult): string {
	return [
		result.title ? `${result.title} (${result.final_url})` : result.final_url,
		result.content,
	]
		.filter(Boolean)
		.join("\n")
		.slice(0, 1800);
}

export function localReplyWithWebSearch(
	message: string,
	searchResult: LocalWebSearchResult,
): string {
	const isChinese = /[\u3400-\u9fff]/.test(message);
	const summary = compactWebSearchSummary(searchResult);
	if (isChinese) {
		return [
			"我已在 Android 本地运行时执行网页搜索，并基于搜索结果给出回答。",
			"",
			summary || `搜索请求：${searchResult.query}`,
		].join("\n");
	}
	return [
		"I ran a web search in the Android local runtime and answered from the search results.",
		"",
		summary || `Search query: ${searchResult.query}`,
	].join("\n");
}

export function localReplyWithWebFetch(
	message: string,
	fetchResult: LocalWebFetchResult,
): string {
	const isChinese = /[\u3400-\u9fff]/.test(message);
	const summary = compactWebFetchSummary(fetchResult);
	if (isChinese) {
		return [
			"我已在 Android 本地运行时抓取网页，并基于页面内容给出回答。",
			"",
			summary || `抓取地址：${fetchResult.final_url}`,
		].join("\n");
	}
	return [
		"I fetched the page in the Android local runtime and answered from its content.",
		"",
		summary || `Fetched URL: ${fetchResult.final_url}`,
	].join("\n");
}

export function deniesExecutedWebAccess(reply: string): boolean {
	const compact = reply.replace(/\s+/g, " ").trim();
	if (!compact) return false;
	return containsAny(compact, [
		"无法联网",
		"不能联网",
		"无法直接联网",
		"无法进行实时网络查询",
		"无法直接进行实时网络查询",
		"不能进行实时网络查询",
		"无法实时查询",
		"不能实时查询",
		"无法直接获取实时",
		"无法获取实时",
		"不能获取实时",
		"无法直接访问互联网",
		"不能直接访问互联网",
		"cannot browse",
		"can't browse",
		"cannot search the web",
		"can't search the web",
		"cannot access the internet",
		"can't access the internet",
		"unable to access the internet",
		"cannot access real-time",
		"can't access real-time",
		"unable to access real-time",
	]);
}

export function localReplyWithLocalTools(
	message: string,
	executions: LocalToolExecution[],
): string {
	const isChinese = /[\u3400-\u9fff]/.test(message);
	const summary = executions
		.map((execution) => {
			const output =
				typeof execution.output === "string"
					? execution.output
					: JSON.stringify(execution.output);
			return `- ${execution.name}: ${execution.message}\n${output.slice(0, 1000)}`;
		})
		.join("\n");
	return isChinese
		? ["我已在 Android 本地运行时执行 App 内工具。", "", summary].join("\n")
		: ["I ran the requested Android app-local tools.", "", summary].join("\n");
}
