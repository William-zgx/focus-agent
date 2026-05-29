import { Capacitor, CapacitorHttp } from "@capacitor/core";

import { stringValue } from "./helpers";
import { abortIfRequested } from "./model-provider";
import type { LocalWebFetchResult } from "./types";

function readablePageText(value: string): { content: string; title: string } {
	const title = stringValue(
		value.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1],
	)
		.replace(/<[^>]+>/g, " ")
		.replace(/\s+/g, " ")
		.trim();
	const content = value
		.replace(/<script[\s\S]*?<\/script>/gi, " ")
		.replace(/<style[\s\S]*?<\/style>/gi, " ")
		.replace(/<noscript[\s\S]*?<\/noscript>/gi, " ")
		.replace(/<[^>]+>/g, " ")
		.replace(/&nbsp;/gi, " ")
		.replace(/&amp;/gi, "&")
		.replace(/&lt;/gi, "<")
		.replace(/&gt;/gi, ">")
		.replace(/&quot;/gi, '"')
		.replace(/&#39;/gi, "'")
		.replace(/\s+/g, " ")
		.trim();
	return { content, title };
}

export async function runLocalWebFetch(
	url: string,
	signal?: AbortSignal,
	maxChars = 5000,
): Promise<LocalWebFetchResult> {
	abortIfRequested(signal);
	const parsed = new URL(url);
	if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
		throw new Error("web_fetch only supports http and https URLs.");
	}
	let rawText = "";
	let contentType = "";
	let finalUrl = parsed.toString();
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("CapacitorHttp")
	) {
		const response = await CapacitorHttp.get({
			url: finalUrl,
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
	} else {
		const response = await fetch(finalUrl, { signal });
		abortIfRequested(signal);
		if (!response.ok) {
			throw new Error(`HTTP ${response.status}: ${response.statusText}`);
		}
		contentType = response.headers.get("content-type") ?? "";
		finalUrl = response.url || finalUrl;
		rawText = await response.text();
	}
	const isHtml =
		/html/i.test(contentType) || /<html[\s>]/i.test(rawText.slice(0, 500));
	const readable = isHtml
		? readablePageText(rawText)
		: { content: rawText, title: "" };
	const content = readable.content.slice(0, maxChars);
	return {
		content,
		content_type: contentType,
		final_url: finalUrl,
		source: "android_local_web_fetch",
		title: readable.title,
		truncated: readable.content.length > maxChars,
		url,
	};
}
