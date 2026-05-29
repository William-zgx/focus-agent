import { containsAny } from "./local-text";

export function shouldUseWebSearch(message: string): boolean {
	const compact = message.replace(/\s+/g, " ").trim();
	if (!compact) return false;
	if (
		containsAny(compact, [
			"不要联网",
			"不用联网",
			"不要搜索",
			"无需搜索",
			"不用搜",
			"别联网",
			"别搜",
			"no web",
			"no search",
			"without searching",
		])
	) {
		return false;
	}
	return containsAny(compact, [
		"web search",
		"search the web",
		"search online",
		"look up",
		"latest",
		"recent",
		"today",
		"current",
		"news",
		"weather",
		"stock",
		"price",
		"网页搜索",
		"联网搜索",
		"联网查",
		"网上查",
		"网上搜",
		"全网查",
		"全网搜",
		"搜索一下",
		"搜一下",
		"搜搜",
		"帮我搜",
		"查一下",
		"查查",
		"最新",
		"最近",
		"今天",
		"今日",
		"现在",
		"实时",
		"新闻",
		"天气",
		"股价",
		"价格",
	]);
}

export function shouldUseCurrentTimeTool(message: string): boolean {
	return containsAny(message, [
		"latest",
		"recent",
		"today",
		"current",
		"now",
		"this week",
		"this month",
		"最新",
		"最近",
		"今天",
		"当前",
		"现在",
		"本周",
		"本月",
	]);
}

export function searchQueryCore(message: string): string {
	let query = message.replace(/\s+/g, " ").trim();
	query = query
		.replace(
			/^(?:请|帮我|帮忙|麻烦你|麻烦|可以|能不能|please)?\s*(?:联网|上网|网上|全网|web)?\s*(?:搜索|搜|查|查询|检索|search(?: the web)?(?: for)?|look up)\s*(?:一下|下)?[：:,，]?\s*/iu,
			"",
		)
		.replace(
			/\s*(?:，|,)?\s*(?:请)?(?:联网|上网|网上|全网)?\s*(?:搜索|搜|查|查询|检索)(?:一下|下|查)?[。.!！?？]*$/u,
			"",
		)
		.replace(
			/\s*(?:please\s+)?(?:search|look up|search the web)(?:\s+it)?[.!?]*$/iu,
			"",
		)
		.replace(
			/\s*(?:请)?(?:给出?|附上|提供)?(?:来源|出处|source|sources|citation|citations)[。.!！?？]*$/iu,
			"",
		)
		.replace(/\s*(?:怎么样|如何|是什么|是多少|是啥)[。.!！?？]*$/u, "")
		.replace(/[。.!！?？]+$/u, "")
		.trim();
	return query || message.replace(/\s+/g, " ").trim();
}

export function requiresTemporalAnchor(message: string): boolean {
	return containsAny(message, [
		"今天",
		"今日",
		"明天",
		"昨天",
		"本周",
		"这周",
		"近一周",
		"最近",
		"近期",
		"过去一周",
		"现在",
		"当前",
		"实时",
		"today",
		"tomorrow",
		"yesterday",
		"this week",
		"recent",
		"recently",
		"last 7 days",
		"past week",
		"now",
		"current",
	]);
}

export function relativeDateParts(
	query: string,
	currentUtcTime: string,
): string[] {
	const anchor = new Date(currentUtcTime);
	if (Number.isNaN(anchor.getTime())) return [];
	const anchorDate = anchor.toISOString().slice(0, 10);
	const anchorMs = Date.UTC(
		anchor.getUTCFullYear(),
		anchor.getUTCMonth(),
		anchor.getUTCDate(),
	);
	const dateAfterDays = (days: number) =>
		new Date(anchorMs + days * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
	const parts: string[] = [];
	if (
		containsAny(query, [
			"今天",
			"今日",
			"today",
			"现在",
			"当前",
			"current",
			"now",
		])
	) {
		parts.push(`绝对日期(今天/UTC)：${anchorDate}`);
	}
	if (containsAny(query, ["明天", "tomorrow"])) {
		parts.push(`绝对日期(明天/UTC)：${dateAfterDays(1)}`);
	}
	if (containsAny(query, ["昨天", "yesterday"])) {
		parts.push(`绝对日期(昨天/UTC)：${dateAfterDays(-1)}`);
	}
	if (
		containsAny(query, [
			"近一周",
			"最近一周",
			"过去一周",
			"last 7 days",
			"past week",
			"recent",
		])
	) {
		parts.push(
			`绝对时间范围(近一周/UTC)：${dateAfterDays(-6)} 至 ${anchorDate}`,
		);
	}
	return [...new Set(parts)];
}

export function searchLocationScope(query: string): string {
	const patterns = [
		/(?:今天|今日|明天|昨天|本周|这周|近一周|最近|近期)\s*([\u4e00-\u9fffA-Za-z][\w\u4e00-\u9fff\s·.-]{1,24}?)(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)/u,
		/([\u4e00-\u9fff]{2,12})(?:今天|今日|明天|昨天|本周|这周|近一周|最近|近期).{0,12}(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)/u,
		/(?:访问|到访|访华)([\u4e00-\u9fff]{2,12})/u,
		/\b(?:in|for|at)\s+([a-z][a-z .'-]{1,40}?)(?:\s+(?:today|tomorrow|this week|weather|news|stock|price)|[?.!,]|$)/i,
	];
	for (const pattern of patterns) {
		const match = query.match(pattern);
		const value = match?.[1]
			?.replace(
				/^(?:帮我|请|查一下|查下|搜一下|搜索|看一下|看看|一下|有哪个|哪个|哪些|the)\s*/iu,
				"",
			)
			.replace(/\s+/g, " ")
			.trim()
			.replace(/[，。,.?!？]+$/u, "");
		if (value) return value.slice(0, 40);
	}
	return "";
}

export function webSearchQuery(
	message: string,
	currentUtcTime?: string | null,
): string {
	const query = searchQueryCore(message).slice(0, 180);
	if (!currentUtcTime || !requiresTemporalAnchor(query))
		return query.slice(0, 240);
	const dateParts = relativeDateParts(query, currentUtcTime);
	if (!dateParts.length) return query.slice(0, 240);
	const normalizedUtcTime = new Date(currentUtcTime).toISOString();
	const locationScope = searchLocationScope(query);
	const metadata = [
		`原始查询：${query}`,
		`当前UTC时间：${normalizedUtcTime}`,
		...dateParts,
		locationScope ? `地点/范围：${locationScope}` : "地点/范围：见原始查询",
	];
	return `${query}（${metadata.join("; ")}）`.slice(0, 360);
}

export function webFetchUrl(message: string): string {
	return (
		message.match(/https?:\/\/[^\s<>"'，。；;、)）\]]+/i)?.[0] ?? ""
	).replace(/[.,，。;；:：!?！？]+$/u, "");
}

export function shouldUseWebFetch(message: string): boolean {
	if (!webFetchUrl(message)) return false;
	const normalized = message.toLowerCase();
	return containsAny(normalized, [
		"web_fetch",
		"fetch",
		"open",
		"read this url",
		"read the url",
		"page content",
		"抓取",
		"读取",
		"打开",
		"访问",
		"网页",
		"页面",
		"链接",
	]);
}
