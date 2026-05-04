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
				nodes.push(
					<a
						key={`${keyPrefix}-link-${nodeIndex}`}
						href={href}
						rel="noreferrer"
						target="_blank"
					>
						{inlineNodes(label, `${keyPrefix}-link-label-${nodeIndex}`)}
					</a>,
				);
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
