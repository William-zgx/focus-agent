import { Capacitor, CapacitorHttp, type HttpHeaders } from "@capacitor/core";

import { LOCAL_WEB_SEARCH_USER_AGENT } from "./constants";
import { stringValue } from "./helpers";
import { abortIfRequested } from "./model-provider";
import type { LocalWebFetchResult } from "./types";

const DEFAULT_MAX_CHARS = 12000;
const MAX_DISPLAY_CHARS = 50000;
const MAX_FETCH_CHARS = 8 * 1024 * 1024;
const TRUNCATION_MARKER = "\n\n[... middle omitted ...]\n\n";

function htmlEntityDecoded(value: string): string {
	const namedEntities: Record<string, string> = {
		amp: "&",
		gt: ">",
		lt: "<",
		nbsp: " ",
		quot: '"',
		apos: "'",
	};
	return value
		.replace(/&#(x[0-9a-f]+|\d+);/gi, (match, rawCode: string) => {
			const codePoint = rawCode.toLowerCase().startsWith("x")
				? Number.parseInt(rawCode.slice(1), 16)
				: Number.parseInt(rawCode, 10);
			return Number.isInteger(codePoint) &&
				codePoint >= 0 &&
				codePoint <= 0x10ffff
				? String.fromCodePoint(codePoint)
				: match;
		})
		.replace(/&([a-z]+);/gi, (match, entity: string) => {
			return namedEntities[entity.toLowerCase()] ?? match;
		});
}

function htmlAttributeValue(tag: string, attributeName: string): string {
	const match = tag.match(
		new RegExp(`${attributeName}\\s*=\\s*(['"])(.*?)\\1`, "i"),
	);
	return htmlEntityDecoded(match?.[2] ?? "").trim();
}

function pagePublishedAt(value: string): string | null {
	for (const tag of value.matchAll(/<meta\b[^>]*>/gi)) {
		const rawTag = tag[0] ?? "";
		const name = (
			htmlAttributeValue(rawTag, "property") ||
			htmlAttributeValue(rawTag, "name")
		).toLowerCase();
		if (
			![
				"article:published_time",
				"datepublished",
				"published",
				"published_at",
				"publication_date",
				"date",
			].includes(name)
		)
			continue;
		const content = htmlAttributeValue(rawTag, "content");
		if (content) return content;
	}
	return null;
}

interface HtmlRootCandidate {
	start: number;
	end: number;
	priority: number;
}

interface OpenHtmlTag {
	name: string;
	candidate?: HtmlRootCandidate;
}

const VOID_HTML_TAGS = new Set([
	"area",
	"base",
	"br",
	"col",
	"embed",
	"hr",
	"img",
	"input",
	"link",
	"meta",
	"param",
	"source",
	"track",
	"wbr",
]);

const SKIPPED_HTML_TAGS = new Set(["script", "style", "noscript", "svg"]);

function readableHtmlFragment(value: string): string {
	const candidates: HtmlRootCandidate[] = [];
	const openTags: OpenHtmlTag[] = [];
	const tagPattern = /<!--[\s\S]*?-->|<\/?[a-z][^>]*>/gi;

	for (const match of value.matchAll(tagPattern)) {
		const rawTag = match[0] ?? "";
		const nameMatch = rawTag.match(/^<\s*(\/?)\s*([a-z][\w:-]*)/i);
		if (!nameMatch) continue;
		const name = nameMatch[2].toLowerCase();
		const skipIndex = openTags.findIndex((tag) =>
			SKIPPED_HTML_TAGS.has(tag.name),
		);
		const closing = Boolean(nameMatch[1]);
		if (skipIndex >= 0 && !(closing && SKIPPED_HTML_TAGS.has(name))) continue;

		if (closing) {
			let openIndex = openTags.length - 1;
			while (openIndex >= 0 && openTags[openIndex]?.name !== name)
				openIndex -= 1;
			if (openIndex < 0) continue;
			const end = match.index ?? value.length;
			for (let index = openTags.length - 1; index >= openIndex; index -= 1) {
				const candidate = openTags[index]?.candidate;
				if (candidate && candidate.end === value.length) candidate.end = end;
			}
			openTags.splice(openIndex);
			continue;
		}

		const role = htmlAttributeValue(rawTag, "role")
			.toLowerCase()
			.split(/\s+/u)
			.filter(Boolean);
		const isContentRoot =
			name === "main" || name === "article" || role.includes("main");
		const candidate = isContentRoot
			? {
					start: (match.index ?? 0) + rawTag.length,
					end: value.length,
					priority: name === "main" ? 0 : name === "article" ? 1 : 2,
				}
			: undefined;
		if (candidate) candidates.push(candidate);
		if (!VOID_HTML_TAGS.has(name) && !/\/\s*>$/u.test(rawTag)) {
			openTags.push({ name, candidate });
		}
	}

	if (!candidates.length) return value;
	candidates.sort(
		(left, right) => left.priority - right.priority || left.start - right.start,
	);
	const selected = candidates[0];
	return value.slice(selected.start, selected.end);
}

function readablePageText(value: string): {
	content: string;
	title: string;
	published_at: string | null;
} {
	const title = htmlEntityDecoded(
		stringValue(value.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1])
			.replace(/<[^>]+>/g, " ")
			.replace(/\s+/g, " ")
			.trim(),
	);
	const content = htmlEntityDecoded(
		readableHtmlFragment(value)
			.replace(/<script[\s\S]*?<\/script>/gi, " ")
			.replace(/<style[\s\S]*?<\/style>/gi, " ")
			.replace(/<noscript[\s\S]*?<\/noscript>/gi, " ")
			.replace(/<svg[\s\S]*?<\/svg>/gi, " ")
			.replace(/<[^>]+>/g, " "),
	)
		.replace(/\s+/g, " ")
		.trim();
	return {
		content,
		title,
		published_at: pagePublishedAt(value),
	};
}

function headTailTextWindow(
	content: string,
	maxChars: number,
): { head: string; tail: string; truncated: boolean } {
	if (content.length <= maxChars) {
		return { head: content, tail: "", truncated: false };
	}
	const headBudget = Math.max(1, Math.floor(maxChars * 0.75));
	const tailBudget = Math.max(0, maxChars - headBudget);
	let head = content.slice(0, headBudget);
	let tail = tailBudget ? content.slice(-tailBudget) : "";
	const headBreak = head.lastIndexOf("\n");
	if (headBreak > headBudget / 2) head = head.slice(0, headBreak);
	const tailBreak = tail.indexOf("\n");
	if (tailBreak >= 0 && tailBreak < tailBudget / 2)
		tail = tail.slice(tailBreak + 1);
	return { head, tail, truncated: true };
}

function boundedMaxChars(value: number | undefined): number {
	if (value === undefined) return DEFAULT_MAX_CHARS;
	if (!Number.isFinite(value) || value <= 0) {
		throw new Error("web_fetch max_chars must be a positive number.");
	}
	return Math.max(1, Math.min(Math.trunc(value), MAX_DISPLAY_CHARS));
}

function boundedOffset(value: number | undefined): number {
	if (value === undefined) return 0;
	if (!Number.isFinite(value) || value < 0) {
		throw new Error("web_fetch offset must be a non-negative number.");
	}
	return Math.trunc(value);
}

async function localWebPageRequest(
	url: string,
	signal?: AbortSignal,
): Promise<{
	text: string;
	contentType: string;
	finalUrl: string;
	fetchLimited: boolean;
}> {
	abortIfRequested(signal);
	const headers: HttpHeaders = {
		Accept:
			"text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
		"User-Agent": LOCAL_WEB_SEARCH_USER_AGENT,
	};
	let rawText = "";
	let contentType = "";
	let finalUrl = url;
	let fetchLimited = false;
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("CapacitorHttp")
	) {
		const response = await CapacitorHttp.get({
			url,
			headers,
			responseType: "text",
			connectTimeout: 15000,
			readTimeout: 30000,
		});
		abortIfRequested(signal);
		if (response.status < 200 || response.status >= 300) {
			throw new Error(`HTTP ${response.status}`);
		}
		rawText =
			typeof response.data === "string"
				? response.data
				: JSON.stringify(response.data ?? "");
		contentType = stringValue(
			(response.headers as Record<string, unknown> | undefined)?.[
				"content-type"
			] ??
				(response.headers as Record<string, unknown> | undefined)?.[
					"Content-Type"
				],
		);
		finalUrl = stringValue((response as { url?: unknown }).url) || finalUrl;
		const contentLength = Number(
			(response.headers as Record<string, unknown> | undefined)?.[
				"content-length"
			] ??
				(response.headers as Record<string, unknown> | undefined)?.[
					"Content-Length"
				],
		);
		fetchLimited =
			Number.isFinite(contentLength) && contentLength > MAX_FETCH_CHARS;
	} else {
		const webHeaders = new Headers(headers);
		webHeaders.delete("User-Agent");
		const response = await fetch(url, { headers: webHeaders, signal });
		abortIfRequested(signal);
		if (!response.ok) {
			throw new Error(`HTTP ${response.status}: ${response.statusText}`);
		}
		contentType = response.headers.get("content-type") ?? "";
		finalUrl = response.url || finalUrl;
		const contentLength = Number(response.headers.get("content-length") ?? "");
		fetchLimited =
			Number.isFinite(contentLength) && contentLength > MAX_FETCH_CHARS;
		rawText = await response.text();
	}
	if (rawText.length > MAX_FETCH_CHARS) {
		rawText = rawText.slice(0, MAX_FETCH_CHARS);
		fetchLimited = true;
	}
	return { text: rawText, contentType, finalUrl, fetchLimited };
}

export async function runLocalWebFetch(
	url: string,
	signal?: AbortSignal,
	maxChars = DEFAULT_MAX_CHARS,
	offset = 0,
): Promise<LocalWebFetchResult> {
	abortIfRequested(signal);
	const parsed = new URL(url);
	if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
		throw new Error("web_fetch only supports http and https URLs.");
	}
	const displayLimit = boundedMaxChars(maxChars);
	const requestedOffset = boundedOffset(offset);
	const response = await localWebPageRequest(parsed.toString(), signal);
	const observedAt = new Date().toISOString();
	if (
		/^(?:application\/(?:pdf|zip|octet-stream)|image\/|audio\/|video\/)/i.test(
			response.contentType,
		) ||
		response.text.startsWith("%PDF-") ||
		response.text.startsWith("PK\u0003\u0004") ||
		response.text.includes("\u0000")
	) {
		throw new Error("The URL returned binary content, not a readable page.");
	}
	const isHtml =
		/html/i.test(response.contentType) ||
		/<html[\s>]/i.test(response.text.slice(0, 500));
	const readable = isHtml
		? readablePageText(response.text)
		: {
				content: response.text.trim(),
				title: "",
				published_at: null,
			};
	const totalChars = readable.content.length;
	if (
		!totalChars ||
		/^(?:just a moment|access denied|attention required(?: \| cloudflare)?|verify you are human)[.!…]*$/i.test(
			readable.title.trim(),
		)
	) {
		throw new Error("The page is empty or blocked by an access challenge.");
	}
	const safeOffset = Math.min(requestedOffset, totalChars);
	let content = "";
	let nextOffset: number | null = null;
	let truncated = false;
	if (safeOffset === 0) {
		const window = headTailTextWindow(
			readable.content,
			totalChars <= displayLimit
				? displayLimit
				: Math.max(1, displayLimit - TRUNCATION_MARKER.length),
		);
		truncated = window.truncated;
		content = window.truncated
			? `${window.head}${TRUNCATION_MARKER}${window.tail}`
			: window.head;
		if (window.truncated) nextOffset = window.head.length;
		if (window.truncated && displayLimit <= TRUNCATION_MARKER.length) {
			content = readable.content.slice(0, displayLimit);
			nextOffset = content.length;
		}
	} else {
		const end = Math.min(totalChars, safeOffset + displayLimit);
		content = readable.content.slice(safeOffset, end);
		truncated = end < totalChars;
		if (truncated) nextOffset = end;
	}
	const hasMore = nextOffset !== null && nextOffset < totalChars;
	if (!hasMore) nextOffset = null;
	const result: LocalWebFetchResult = {
		content,
		content_chars: totalChars,
		content_type: response.contentType,
		fetch_limited: response.fetchLimited,
		final_url: response.finalUrl,
		offset: safeOffset,
		next_offset: nextOffset,
		observed_at: observedAt,
		published_at: readable.published_at,
		shown_chars: content.length,
		source: "android_local_web_fetch",
		title: readable.title,
		total_chars: totalChars,
		truncated,
		url,
	};
	if (hasMore) {
		result.continuation = {
			available: true,
			offset: nextOffset ?? undefined,
			limit: displayLimit,
			total_chars: totalChars,
			hint: `Re-fetch the same URL with offset ${nextOffset} and max_chars ${displayLimit} to continue. The page may change between requests.`,
		};
	}
	return result;
}
