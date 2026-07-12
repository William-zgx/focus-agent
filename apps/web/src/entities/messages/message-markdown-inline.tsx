import { Fragment, type ReactNode } from "react";

function pushTextNode(nodes: ReactNode[], value: string, key: string) {
	if (!value) {
		return;
	}
	nodes.push(<Fragment key={key}>{value}</Fragment>);
}

function findClosingToken(value: string, token: string, startIndex: number) {
	let searchIndex = startIndex;
	while (searchIndex < value.length) {
		const matchIndex = value.indexOf(token, searchIndex);
		if (matchIndex === -1) {
			return -1;
		}
		if (matchIndex > startIndex) {
			return matchIndex;
		}
		searchIndex = matchIndex + token.length;
	}
	return -1;
}

export function isSafeMarkdownHref(href: string): boolean {
	const value = href.trim();
	const hasUnsafeCharacter = [...value].some((character) => {
		const codePoint = character.codePointAt(0) ?? 0;
		return codePoint === 92 || codePoint <= 31 || codePoint === 127;
	});
	if (!value || hasUnsafeCharacter || value.startsWith("//")) {
		return false;
	}
	if (
		value.startsWith("/") ||
		value.startsWith("./") ||
		value.startsWith("../") ||
		value.startsWith("#") ||
		value.startsWith("?")
	) {
		return true;
	}
	const schemeSeparator = value.indexOf(":");
	if (schemeSeparator === -1) {
		return true;
	}
	const scheme = value.slice(0, schemeSeparator).toLowerCase();
	return scheme === "http" || scheme === "https" || scheme === "mailto";
}

export function inlineNodes(text: string, keyPrefix: string): ReactNode[] {
	const nodes: ReactNode[] = [];
	let buffer = "";
	let index = 0;
	let nodeIndex = 0;

	while (index < text.length) {
		if (text.startsWith("`", index)) {
			const closeIndex = text.indexOf("`", index + 1);
			if (closeIndex !== -1) {
				pushTextNode(nodes, buffer, `${keyPrefix}-text-${nodeIndex}`);
				buffer = "";
				nodes.push(
					<code
						key={`${keyPrefix}-code-${nodeIndex}`}
						className="fa-message-inline-code"
					>
						{text.slice(index + 1, closeIndex)}
					</code>,
				);
				nodeIndex += 1;
				index = closeIndex + 1;
				continue;
			}
		}

		if (text.startsWith("[", index)) {
			const labelEnd = text.indexOf("]", index + 1);
			const urlStart = labelEnd === -1 ? -1 : text.indexOf("(", labelEnd);
			const urlEnd = urlStart === -1 ? -1 : text.indexOf(")", urlStart + 1);
			if (labelEnd !== -1 && urlStart === labelEnd + 1 && urlEnd !== -1) {
				pushTextNode(nodes, buffer, `${keyPrefix}-text-${nodeIndex}`);
				buffer = "";
				const label = text.slice(index + 1, labelEnd);
				const href = text.slice(urlStart + 1, urlEnd);
				const labelNodes = inlineNodes(
					label,
					`${keyPrefix}-link-label-${nodeIndex}`,
				);
				if (isSafeMarkdownHref(href)) {
					nodes.push(
						<a
							key={`${keyPrefix}-link-${nodeIndex}`}
							href={href.trim()}
							rel="noreferrer"
							target="_blank"
						>
							{labelNodes}
						</a>,
					);
				} else {
					nodes.push(
						<Fragment key={`${keyPrefix}-link-text-${nodeIndex}`}>
							{labelNodes}
						</Fragment>,
					);
				}
				nodeIndex += 1;
				index = urlEnd + 1;
				continue;
			}
		}

		const strongToken = text.startsWith("**", index)
			? "**"
			: text.startsWith("__", index)
				? "__"
				: "";
		if (strongToken) {
			const closeIndex = findClosingToken(
				text,
				strongToken,
				index + strongToken.length,
			);
			if (closeIndex !== -1) {
				pushTextNode(nodes, buffer, `${keyPrefix}-text-${nodeIndex}`);
				buffer = "";
				const content = text.slice(index + strongToken.length, closeIndex);
				nodes.push(
					<strong key={`${keyPrefix}-strong-${nodeIndex}`}>
						{inlineNodes(content, `${keyPrefix}-strong-content-${nodeIndex}`)}
					</strong>,
				);
				nodeIndex += 1;
				index = closeIndex + strongToken.length;
				continue;
			}
		}

		const emphasisToken =
			text[index] === "*" || text[index] === "_" ? text[index] : "";
		if (emphasisToken) {
			const doubleToken = emphasisToken.repeat(2);
			if (!text.startsWith(doubleToken, index)) {
				const closeIndex = findClosingToken(text, emphasisToken, index + 1);
				if (closeIndex !== -1) {
					pushTextNode(nodes, buffer, `${keyPrefix}-text-${nodeIndex}`);
					buffer = "";
					const content = text.slice(index + 1, closeIndex);
					nodes.push(
						<em key={`${keyPrefix}-em-${nodeIndex}`}>
							{inlineNodes(content, `${keyPrefix}-em-content-${nodeIndex}`)}
						</em>,
					);
					nodeIndex += 1;
					index = closeIndex + 1;
					continue;
				}
			}
		}

		buffer += text[index];
		index += 1;
	}

	if (buffer) {
		pushTextNode(nodes, buffer, `${keyPrefix}-tail-${nodeIndex}`);
	}

	return nodes;
}
