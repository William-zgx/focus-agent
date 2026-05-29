import { Capacitor, CapacitorHttp, type HttpHeaders } from "@capacitor/core";

import { LOCAL_WEB_SEARCH_USER_AGENT } from "./constants";
import { isRecord, stringValue } from "./helpers";
import { abortIfRequested } from "./model-provider";
import type { LocalWebSearchResult } from "./types";

function htmlEntityDecoded(value: string): string {
	const namedEntities: Record<string, string> = {
		amp: "&",
		gt: ">",
		lt: "<",
		nbsp: " ",
		quot: '"',
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

function readableHtmlFragment(value: string): string {
	return htmlEntityDecoded(value.replace(/<[^>]+>/g, " "))
		.replace(/\s+/g, " ")
		.trim();
}

function htmlAttributeValue(tag: string, attributeName: string): string {
	const match = tag.match(
		new RegExp(`${attributeName}\\s*=\\s*(['"])(.*?)\\1`, "i"),
	);
	return htmlEntityDecoded(match?.[2] ?? "").trim();
}

function normalizedDuckDuckGoHref(rawHref: string): string {
	const href = htmlEntityDecoded(rawHref).trim();
	if (!href) return "";
	const absoluteHref = href.startsWith("//") ? `https:${href}` : href;
	try {
		const url = new URL(absoluteHref, "https://duckduckgo.com");
		return url.searchParams.get("uddg") ?? url.toString();
	} catch {
		return href;
	}
}

function collectDuckDuckGoHtmlResults(
	html: string,
	pattern: RegExp,
	maxResults: number,
): LocalWebSearchResult["results"] {
	const results: LocalWebSearchResult["results"] = [];
	const seen = new Set<string>();
	for (const match of html.matchAll(pattern)) {
		const linkTag = match[1] ?? "";
		const snippetTag = match[2] ?? "";
		const title = readableHtmlFragment(linkTag);
		const url = normalizedDuckDuckGoHref(htmlAttributeValue(linkTag, "href"));
		const snippet = readableHtmlFragment(snippetTag);
		const key = url || `${title}:${snippet}`;
		if (!title || !key || seen.has(key)) continue;
		seen.add(key);
		results.push({
			title: title.slice(0, 180),
			url,
			snippet: (snippet || title).slice(0, 600),
		});
		if (results.length >= maxResults) break;
	}
	return results;
}

function parseDuckDuckGoHtmlResults(
	html: string,
	maxResults: number,
): LocalWebSearchResult["results"] {
	const desktopResults = collectDuckDuckGoHtmlResults(
		html,
		/(<a\b[^>]*class=["'][^"']*\bresult__a\b[^"']*["'][^>]*>[\s\S]*?<\/a>)[\s\S]*?(<a\b[^>]*class=["'][^"']*\bresult__snippet\b[^"']*["'][^>]*>[\s\S]*?<\/a>)/gi,
		maxResults,
	);
	if (desktopResults.length) return desktopResults;
	return collectDuckDuckGoHtmlResults(
		html,
		/(<a\b[^>]*class=["'][^"']*\bresult-link\b[^"']*["'][^>]*>[\s\S]*?<\/a>)[\s\S]*?(<td\b[^>]*class=["'][^"']*\bresult-snippet\b[^"']*["'][^>]*>[\s\S]*?<\/td>)/gi,
		maxResults,
	);
}

async function localWebTextRequest(
	url: string,
	signal?: AbortSignal,
): Promise<string> {
	abortIfRequested(signal);
	const headers: HttpHeaders = {
		Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
		"User-Agent": LOCAL_WEB_SEARCH_USER_AGENT,
	};
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
		return typeof response.data === "string"
			? response.data
			: JSON.stringify(response.data ?? "");
	}
	const webHeaders = new Headers(headers);
	webHeaders.delete("User-Agent");
	const response = await fetch(url, { headers: webHeaders, signal });
	abortIfRequested(signal);
	const text = await response.text();
	if (!response.ok) {
		throw new Error(`HTTP ${response.status}: ${response.statusText}`);
	}
	return text;
}

async function localWebJsonRequest(
	url: string,
	signal?: AbortSignal,
): Promise<unknown> {
	abortIfRequested(signal);
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("CapacitorHttp")
	) {
		const response = await CapacitorHttp.get({
			url,
			responseType: "json",
			connectTimeout: 15000,
			readTimeout: 30000,
		});
		abortIfRequested(signal);
		if (response.status < 200 || response.status >= 300) {
			throw new Error(`HTTP ${response.status}`);
		}
		if (typeof response.data === "string") {
			return JSON.parse(response.data) as unknown;
		}
		return response.data;
	}
	const response = await fetch(url, { signal });
	abortIfRequested(signal);
	const payload = await response.json().catch(() => ({}));
	if (!response.ok) {
		throw new Error(`HTTP ${response.status}: ${response.statusText}`);
	}
	return payload;
}

async function runDuckDuckGoHtmlSearch({
	endpoint,
	query,
	signal,
	source,
}: {
	endpoint: "html" | "lite";
	query: string;
	signal?: AbortSignal;
	source: string;
}): Promise<LocalWebSearchResult> {
	const url = `https://duckduckgo.com/${endpoint}/?${new URLSearchParams({
		q: query,
	}).toString()}`;
	const html = await localWebTextRequest(url, signal);
	const results = parseDuckDuckGoHtmlResults(html, 5);
	if (!results.length) {
		throw new Error(`${source} returned no results.`);
	}
	return {
		answer: results[0]?.snippet || results[0]?.title || "",
		query,
		results,
		source,
	};
}

function duckDuckGoInstantAnswerItems(
	items: unknown[],
): LocalWebSearchResult["results"] {
	return items.flatMap((item): LocalWebSearchResult["results"] => {
		if (!isRecord(item)) return [];
		const nestedTopics = Array.isArray(item.Topics) ? item.Topics : null;
		if (nestedTopics) return duckDuckGoInstantAnswerItems(nestedTopics);
		const text = stringValue(item.Text);
		const title = stringValue(item.Title) || text.split(" - ")[0] || "";
		const url = stringValue(item.FirstURL) || stringValue(item.URL);
		if (!text && !title) return [];
		return [
			{
				title: (title || "Related result").slice(0, 180),
				url,
				snippet: (text || title).slice(0, 600),
			},
		];
	});
}

async function runDuckDuckGoInstantAnswerSearch(
	query: string,
	signal?: AbortSignal,
): Promise<LocalWebSearchResult> {
	const url = `https://api.duckduckgo.com/?${new URLSearchParams({
		format: "json",
		no_html: "1",
		no_redirect: "1",
		q: query,
		skip_disambig: "1",
	}).toString()}`;
	const payload = await localWebJsonRequest(url, signal);
	const record = isRecord(payload) ? payload : {};
	const heading = stringValue(record.Heading);
	const answerText = stringValue(record.Answer);
	const abstractText = stringValue(record.AbstractText);
	const abstractUrl = stringValue(record.AbstractURL);
	const relatedTopics = Array.isArray(record.RelatedTopics)
		? record.RelatedTopics
		: [];
	const directResults = Array.isArray(record.Results) ? record.Results : [];
	const normalizedResults = [
		...(abstractText || answerText || heading
			? [
					{
						title: heading || query,
						url: abstractUrl,
						snippet: abstractText || answerText || heading,
					},
				]
			: []),
		...duckDuckGoInstantAnswerItems(directResults),
		...duckDuckGoInstantAnswerItems(relatedTopics),
	].slice(0, 5);
	if (!normalizedResults.length) {
		throw new Error("duckduckgo_instant_answer returned no results.");
	}
	return {
		answer: abstractText || answerText || normalizedResults[0]?.snippet || "",
		query,
		results: normalizedResults,
		source: "duckduckgo_instant_answer",
	};
}

function localWebSearchError(
	provider: string,
	error: unknown,
): { category: string; message: string; provider: string } {
	const message = error instanceof Error ? error.message : String(error);
	return {
		category: message.includes("returned no results")
			? "empty_results"
			: "provider_error",
		message,
		provider,
	};
}

export async function runLocalWebSearch(
	query: string,
	signal?: AbortSignal,
): Promise<LocalWebSearchResult> {
	abortIfRequested(signal);
	const normalizedQuery = query.replace(/\s+/g, " ").trim();
	if (!normalizedQuery) throw new Error("Query must not be empty.");
	const providers = [
		{
			name: "duckduckgo_html",
			run: () =>
				runDuckDuckGoHtmlSearch({
					endpoint: "html",
					query: normalizedQuery,
					signal,
					source: "duckduckgo_html",
				}),
		},
		{
			name: "duckduckgo_lite",
			run: () =>
				runDuckDuckGoHtmlSearch({
					endpoint: "lite",
					query: normalizedQuery,
					signal,
					source: "duckduckgo_lite",
				}),
		},
		{
			name: "duckduckgo_instant_answer",
			run: () => runDuckDuckGoInstantAnswerSearch(normalizedQuery, signal),
		},
	];
	const attemptedProviders: string[] = [];
	const errors: LocalWebSearchResult["errors"] = [];
	for (const provider of providers) {
		attemptedProviders.push(provider.name);
		try {
			const result = await provider.run();
			return {
				...result,
				attempted_providers: attemptedProviders,
				errors,
				fallback_used: provider.name !== providers[0]?.name,
			};
		} catch (error) {
			abortIfRequested(signal);
			errors.push(localWebSearchError(provider.name, error));
		}
	}
	throw new Error(
		`No web search provider succeeded: ${errors
			.map((error) => `${error.provider} (${error.category}): ${error.message}`)
			.join("; ")}`,
	);
}
