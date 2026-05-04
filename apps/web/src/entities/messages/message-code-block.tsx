import { useState } from "react";

import { codeCopyLabel } from "./message-list-helpers";

export function CodeBlock({
	code,
	language,
	isChineseUi,
}: {
	code: string;
	language: string;
	isChineseUi: boolean;
}) {
	const [copied, setCopied] = useState(false);

	async function handleCopy() {
		await navigator.clipboard.writeText(code);
		setCopied(true);
		window.setTimeout(() => setCopied(false), 1200);
	}

	return (
		<div className="fa-message-code-block">
			<div className="fa-message-code-header">
				<span className="fa-message-code-label">{language || "text"}</span>
				<button
					className="fa-code-copy-button"
					onClick={() => void handleCopy()}
					type="button"
				>
					{codeCopyLabel(isChineseUi, copied)}
				</button>
			</div>
			<pre>
				<code>{code}</code>
			</pre>
		</div>
	);
}
