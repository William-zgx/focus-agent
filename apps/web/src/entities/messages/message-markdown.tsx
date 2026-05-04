import { CodeBlock } from "./message-code-block";
import { renderMarkdownBlocks } from "./message-markdown-blocks";

export { CodeBlock };

export function MessageMarkdown({
	text,
	isChineseUi,
}: {
	text: string;
	isChineseUi: boolean;
}) {
	return (
		<div className="fa-message-markdown">
			{renderMarkdownBlocks(text, isChineseUi)}
		</div>
	);
}
