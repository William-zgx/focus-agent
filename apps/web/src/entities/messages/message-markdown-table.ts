export type MarkdownTableAlignment = "left" | "center" | "right" | null;

export function parseMarkdownTableRow(line: string): string[] | null {
	const trimmed = line.trim();
	if (!trimmed.includes("|")) {
		return null;
	}

	const normalized = trimmed.replace(/^\|/, "").replace(/\|$/, "");
	const cells = normalized.split("|").map((cell) => cell.trim());
	if (cells.length < 2 || cells.every((cell) => !cell)) {
		return null;
	}
	return cells;
}

export function isMarkdownTableDelimiter(line: string) {
	const cells = parseMarkdownTableRow(line);
	return !!cells && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

export function parseMarkdownTableAlignments(
	line: string,
	columnCount: number,
): MarkdownTableAlignment[] {
	const cells = parseMarkdownTableRow(line) ?? [];
	return Array.from({ length: columnCount }, (_, index) => {
		const cell = cells[index] ?? "";
		if (cell.startsWith(":") && cell.endsWith(":")) {
			return "center";
		}
		if (cell.endsWith(":")) {
			return "right";
		}
		if (cell.startsWith(":")) {
			return "left";
		}
		return null;
	});
}

export function normalizeMarkdownTableRow(row: string[], columnCount: number) {
	return Array.from({ length: columnCount }, (_, index) => row[index] ?? "");
}

export function tableCellAlignmentClass(alignment: MarkdownTableAlignment) {
	if (alignment === "center") {
		return "is-align-center";
	}
	if (alignment === "right") {
		return "is-align-right";
	}
	return "";
}
