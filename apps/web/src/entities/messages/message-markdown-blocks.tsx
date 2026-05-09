import { createElement, Fragment, type ReactNode } from "react";

import { CodeBlock } from "./message-code-block";
import { inlineNodes } from "./message-markdown-inline";
import {
	isMarkdownTableDelimiter,
	normalizeMarkdownTableRow,
	parseMarkdownTableAlignments,
	parseMarkdownTableRow,
	tableCellAlignmentClass,
} from "./message-markdown-table";

function paragraphNode(text: string, key: string) {
	const lines = text.split("\n");
	return (
		<p key={key}>
			{lines.map((line, index) => (
				<Fragment key={`${key}-line-${index}`}>
					{inlineNodes(line, `${key}-inline-${index}`)}
					{index < lines.length - 1 ? <br /> : null}
				</Fragment>
			))}
		</p>
	);
}

export function renderMarkdownBlocks(text: string, isChineseUi: boolean) {
	const lines = String(text || "")
		.replace(/\r\n?/g, "\n")
		.split("\n");
	const blocks: ReactNode[] = [];
	let index = 0;

	while (index < lines.length) {
		const line = lines[index] ?? "";
		const trimmed = line.trim();

		if (!trimmed) {
			index += 1;
			continue;
		}

		if (trimmed.startsWith("```")) {
			const language = trimmed.slice(3).trim();
			const codeLines: string[] = [];
			index += 1;
			while (index < lines.length && !lines[index].trim().startsWith("```")) {
				codeLines.push(lines[index]);
				index += 1;
			}
			if (index < lines.length) {
				index += 1;
			}
			blocks.push(
				<CodeBlock
					key={`code-${blocks.length}`}
					code={codeLines.join("\n")}
					language={language}
					isChineseUi={isChineseUi}
				/>,
			);
			continue;
		}

		if (/^---+$/.test(trimmed)) {
			blocks.push(<hr key={`hr-${blocks.length}`} />);
			index += 1;
			continue;
		}

		const nextLine = lines[index + 1] ?? "";
		const tableHeader = parseMarkdownTableRow(line);
		if (tableHeader && isMarkdownTableDelimiter(nextLine)) {
			const columnCount = tableHeader.length;
			const alignments = parseMarkdownTableAlignments(nextLine, columnCount);
			const bodyRows: string[][] = [];
			index += 2;
			while (index < lines.length) {
				const rowLine = lines[index] ?? "";
				const rowTrimmed = rowLine.trim();
				const row = parseMarkdownTableRow(rowLine);
				if (!rowTrimmed || !row || isMarkdownTableDelimiter(rowTrimmed)) {
					break;
				}
				bodyRows.push(normalizeMarkdownTableRow(row, columnCount));
				index += 1;
			}
			blocks.push(
				<div key={`table-${blocks.length}`} className="fa-message-table-wrap">
					<table className="fa-message-table">
						<thead>
							<tr>
								{tableHeader.map((cell, cellIndex) => (
									<th
										key={`table-head-${blocks.length}-${cellIndex}`}
										className={tableCellAlignmentClass(
											alignments[cellIndex] ?? null,
										)}
										scope="col"
									>
										{inlineNodes(
											cell,
											`table-head-${blocks.length}-${cellIndex}`,
										)}
									</th>
								))}
							</tr>
						</thead>
						{bodyRows.length > 0 ? (
							<tbody>
								{bodyRows.map((row, rowIndex) => (
									<tr key={`table-row-${blocks.length}-${rowIndex}`}>
										{row.map((cell, cellIndex) => (
											<td
												key={`table-cell-${blocks.length}-${rowIndex}-${cellIndex}`}
												className={tableCellAlignmentClass(
													alignments[cellIndex] ?? null,
												)}
											>
												{inlineNodes(
													cell,
													`table-cell-${blocks.length}-${rowIndex}-${cellIndex}`,
												)}
											</td>
										))}
									</tr>
								))}
							</tbody>
						) : null}
					</table>
				</div>,
			);
			continue;
		}

		const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
		if (heading) {
			const level = Math.min(heading[1].length, 6);
			blocks.push(
				createElement(
					`h${level}`,
					{ key: `h-${blocks.length}` },
					inlineNodes(heading[2], `h-${blocks.length}`),
				),
			);
			index += 1;
			continue;
		}

		if (trimmed.startsWith(">")) {
			const quoteLines: string[] = [];
			while (index < lines.length && lines[index].trim().startsWith(">")) {
				quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
				index += 1;
			}
			blocks.push(
				<blockquote key={`quote-${blocks.length}`}>
					{paragraphNode(quoteLines.join("\n"), `quote-p-${blocks.length}`)}
				</blockquote>,
			);
			continue;
		}

		if (/^[-*]\s+/.test(trimmed)) {
			const items: string[] = [];
			while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
				items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
				index += 1;
			}
			blocks.push(
				<ul key={`ul-${blocks.length}`}>
					{items.map((item, itemIndex) => (
						<li key={`ul-${blocks.length}-${itemIndex}`}>
							{inlineNodes(item, `ul-${blocks.length}-${itemIndex}`)}
						</li>
					))}
				</ul>,
			);
			continue;
		}

		if (/^\d+\.\s+/.test(trimmed)) {
			const items: string[] = [];
			while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
				items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
				index += 1;
			}
			blocks.push(
				<ol key={`ol-${blocks.length}`}>
					{items.map((item, itemIndex) => (
						<li key={`ol-${blocks.length}-${itemIndex}`}>
							{inlineNodes(item, `ol-${blocks.length}-${itemIndex}`)}
						</li>
					))}
				</ol>,
			);
			continue;
		}

		const paragraphLines: string[] = [];
		while (index < lines.length) {
			const paragraphLine = lines[index];
			const paragraphTrimmed = paragraphLine.trim();
			if (
				!paragraphTrimmed ||
				paragraphTrimmed.startsWith("```") ||
				/^---+$/.test(paragraphTrimmed) ||
				/^(#{1,6})\s+/.test(paragraphTrimmed) ||
				paragraphTrimmed.startsWith(">") ||
				/^[-*]\s+/.test(paragraphTrimmed) ||
				/^\d+\.\s+/.test(paragraphTrimmed)
			) {
				break;
			}
			paragraphLines.push(paragraphLine);
			index += 1;
		}
		blocks.push(paragraphNode(paragraphLines.join("\n"), `p-${blocks.length}`));
	}

	return blocks;
}
