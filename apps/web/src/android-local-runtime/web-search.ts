import { Capacitor, CapacitorHttp, type HttpHeaders } from "@capacitor/core";

import { LOCAL_WEB_SEARCH_USER_AGENT } from "./constants";
import { isRecord, stringValue } from "./helpers";
import { abortIfRequested } from "./model-provider";
import type {
	LocalWebSearchResult,
	LocalWebSearchResultItem,
	LocalWebSearchTimeRange,
} from "./types";
import { webSearchTimeRange } from "./web-planning";

export { webSearchTimeRange } from "./web-planning";

const SEARCH_TIME_RANGES: Record<string, LocalWebSearchTimeRange> = {
	d: "day",
	day: "day",
	"24h": "day",
	"1d": "day",
	w: "week",
	week: "week",
	"7d": "week",
	m: "month",
	month: "month",
	"30d": "month",
	y: "year",
	year: "year",
	"365d": "year",
};

const DDG_TIME_RANGES: Record<LocalWebSearchTimeRange, string> = {
	day: "d",
	week: "w",
	month: "m",
	year: "y",
};

function normalizedSearchTimeRange(
	value: string | LocalWebSearchTimeRange | null | undefined,
): LocalWebSearchTimeRange | null {
	if (!value?.trim()) return null;
	const normalized = SEARCH_TIME_RANGES[value.trim().toLowerCase()];
	if (!normalized) {
		throw new Error("time_range must be one of: day, week, month, year.");
	}
	return normalized;
}

function normalizedSearchDomains(
	value: string[] | string | null | undefined,
	fieldName: string,
): string[] {
	if (value == null) return [];
	const values = Array.isArray(value) ? value : value.split(",");
	const domains: string[] = [];
	for (const rawValue of values) {
		const raw = String(rawValue ?? "")
			.trim()
			.toLowerCase();
		if (!raw) throw new Error(`${fieldName} contains an empty domain.`);
		const wildcard = raw.startsWith("*.");
		const candidate = wildcard ? raw.slice(2) : raw;
		let host = candidate;
		try {
			host = new URL(
				candidate.includes("://") ? candidate : `https://${candidate}`,
			).hostname
				.toLowerCase()
				.replace(/\.$/, "");
		} catch {
			throw new Error(`${fieldName} contains an invalid domain: ${rawValue}.`);
		}
		if (
			!host ||
			/[^a-z0-9.-]/i.test(host) ||
			host.startsWith(".") ||
			host.endsWith(".")
		) {
			throw new Error(`${fieldName} contains an invalid domain: ${rawValue}.`);
		}
		const normalized = wildcard ? `*.${host}` : host;
		if (!domains.includes(normalized)) domains.push(normalized);
	}
	return domains;
}

export interface LocalWebSearchOptions {
	time_range?: LocalWebSearchTimeRange | string | null;
	include_domains?: string[] | string | null;
	exclude_domains?: string[] | string | null;
	max_results?: number | null;
	observed_at?: string;
}

function resultItem({
	title,
	url,
	snippet,
	publishedAt = null,
	observedAt,
}: {
	title: string;
	url: string;
	snippet: string;
	publishedAt?: string | null;
	observedAt: string;
}): LocalWebSearchResultItem {
	const content = snippet.slice(0, 600);
	return {
		title: title.slice(0, 180),
		url,
		snippet: content,
		published_at: publishedAt,
		observed_at: observedAt,
	};
}

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
	observedAt: string,
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
		results.push(
			resultItem({
				title,
				url,
				snippet: snippet || title,
				observedAt,
			}),
		);
		if (results.length >= maxResults) break;
	}
	return results;
}

function parseDuckDuckGoHtmlResults(
	html: string,
	maxResults: number,
	observedAt: string,
): LocalWebSearchResult["results"] {
	const desktopResults = collectDuckDuckGoHtmlResults(
		html,
		/(<a\b[^>]*class=["'][^"']*\bresult__a\b[^"']*["'][^>]*>[\s\S]*?<\/a>)[\s\S]*?(<a\b[^>]*class=["'][^"']*\bresult__snippet\b[^"']*["'][^>]*>[\s\S]*?<\/a>)/gi,
		maxResults,
		observedAt,
	);
	if (desktopResults.length) return desktopResults;
	return collectDuckDuckGoHtmlResults(
		html,
		/(<a\b[^>]*class=["'][^"']*\bresult-link\b[^"']*["'][^>]*>[\s\S]*?<\/a>)[\s\S]*?(<td\b[^>]*class=["'][^"']*\bresult-snippet\b[^"']*["'][^>]*>[\s\S]*?<\/td>)/gi,
		maxResults,
		observedAt,
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
	observedAt,
	timeRange,
	includeDomains,
	excludeDomains,
	maxResults,
}: {
	endpoint: "html" | "lite";
	query: string;
	signal?: AbortSignal;
	source: string;
	observedAt: string;
	timeRange: LocalWebSearchTimeRange | null;
	includeDomains: string[];
	excludeDomains: string[];
	maxResults: number;
}): Promise<LocalWebSearchResult> {
	let providerQuery = query;
	if (includeDomains.length) {
		providerQuery += ` (${includeDomains
			.map((domain) => `site:${domain.replace(/^\*\./, "")}`)
			.join(" OR ")})`;
	}
	if (excludeDomains.length) {
		providerQuery += ` ${excludeDomains
			.map((domain) => `-site:${domain.replace(/^\*\./, "")}`)
			.join(" ")}`;
	}
	const params = new URLSearchParams({ q: providerQuery });
	if (timeRange) params.set("df", DDG_TIME_RANGES[timeRange]);
	const url = `https://duckduckgo.com/${endpoint}/?${params.toString()}`;
	const html = await localWebTextRequest(url, signal);
	const results = parseDuckDuckGoHtmlResults(html, maxResults, observedAt);
	if (!results.length) {
		throw new Error(`${source} returned no results.`);
	}
	return {
		answer: null,
		query,
		results,
		observed_at: observedAt,
		provider: source,
		search_filters: {
			time_range: timeRange,
			include_domains: includeDomains,
			exclude_domains: excludeDomains,
			provider_time_range: timeRange ? DDG_TIME_RANGES[timeRange] : null,
			provider_query: providerQuery,
			domain_filter_mode:
				includeDomains.length || excludeDomains.length
					? "query_operators"
					: "unsupported",
		},
		source,
	};
}

function publishedAtFromRecord(record: Record<string, unknown>): string | null {
	for (const key of [
		"published_at",
		"published_date",
		"published",
		"publishedDate",
		"publication_date",
		"date",
	]) {
		const value = stringValue(record[key]).trim();
		if (value) return value;
	}
	return null;
}

function duckDuckGoInstantAnswerItems(
	items: unknown[],
	observedAt: string,
): LocalWebSearchResult["results"] {
	return items.flatMap((item): LocalWebSearchResult["results"] => {
		if (!isRecord(item)) return [];
		const nestedTopics = Array.isArray(item.Topics) ? item.Topics : null;
		if (nestedTopics)
			return duckDuckGoInstantAnswerItems(nestedTopics, observedAt);
		const text = stringValue(item.Text);
		const title = stringValue(item.Title) || text.split(" - ")[0] || "";
		const url = stringValue(item.FirstURL) || stringValue(item.URL);
		if (!text && !title) return [];
		return [
			resultItem({
				title: title || "Related result",
				url,
				snippet: text || title,
				observedAt,
				publishedAt: publishedAtFromRecord(item),
			}),
		];
	});
}

async function runDuckDuckGoInstantAnswerSearch(
	query: string,
	signal: AbortSignal | undefined,
	options: {
		observedAt: string;
		timeRange: LocalWebSearchTimeRange | null;
		includeDomains: string[];
		excludeDomains: string[];
		maxResults: number;
	},
): Promise<LocalWebSearchResult> {
	if (
		options.timeRange ||
		options.includeDomains.length ||
		options.excludeDomains.length
	) {
		throw new Error(
			"Instant answers cannot honor the requested time or domain filters.",
		);
	}
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
					resultItem({
						title: heading || query,
						url: abstractUrl,
						snippet: abstractText || answerText || heading,
						observedAt: options.observedAt,
						publishedAt: publishedAtFromRecord(record),
					}),
				]
			: []),
		...duckDuckGoInstantAnswerItems(directResults, options.observedAt),
		...duckDuckGoInstantAnswerItems(relatedTopics, options.observedAt),
	].slice(0, options.maxResults);
	if (!normalizedResults.length) {
		throw new Error("duckduckgo_instant_answer returned no results.");
	}
	return {
		answer: null,
		query,
		results: normalizedResults,
		observed_at: options.observedAt,
		provider: "duckduckgo_instant_answer",
		search_filters: {
			time_range: options.timeRange,
			include_domains: options.includeDomains,
			exclude_domains: options.excludeDomains,
			provider_time_range: null,
			domain_filter_mode: "unsupported",
		},
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
	options: LocalWebSearchOptions = {},
): Promise<LocalWebSearchResult> {
	abortIfRequested(signal);
	const normalizedQuery = query.replace(/\s+/g, " ").trim();
	if (!normalizedQuery) throw new Error("Query must not be empty.");
	const timeRange = normalizedSearchTimeRange(
		options.time_range === undefined
			? webSearchTimeRange(normalizedQuery)
			: options.time_range,
	);
	const includeDomains = normalizedSearchDomains(
		options.include_domains,
		"include_domains",
	);
	const excludeDomains = normalizedSearchDomains(
		options.exclude_domains,
		"exclude_domains",
	);
	const maxResults = Math.max(
		1,
		Math.min(10, Math.trunc(Number(options.max_results ?? 5)) || 5),
	);
	const observedAt = options.observed_at || new Date().toISOString();
	const providers = [
		{
			name: "duckduckgo_html",
			run: () =>
				runDuckDuckGoHtmlSearch({
					endpoint: "html",
					query: normalizedQuery,
					signal,
					source: "duckduckgo_html",
					observedAt,
					timeRange,
					includeDomains,
					excludeDomains,
					maxResults,
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
					observedAt,
					timeRange,
					includeDomains,
					excludeDomains,
					maxResults,
				}),
		},
		{
			name: "duckduckgo_instant_answer",
			run: () =>
				runDuckDuckGoInstantAnswerSearch(normalizedQuery, signal, {
					observedAt,
					timeRange,
					includeDomains,
					excludeDomains,
					maxResults,
				}),
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
