import { useId } from "react";

export function AgentTeamCreateDagPreview() {
	const dagIdBase = useId().replace(/:/g, "");
	const dagEdgeGradientId = `${dagIdBase}-edge`;
	const dagShellGradientId = `${dagIdBase}-shell`;
	const dagNodeGradientId = `${dagIdBase}-node`;
	const dagResultGradientId = `${dagIdBase}-result`;
	const dagGridPatternId = `${dagIdBase}-grid`;

	return (
		<svg
			className="fa-agent-team-studio-dag"
			viewBox="0 0 304 124"
			aria-hidden="true"
		>
			<defs>
				<linearGradient id={dagShellGradientId} x1="0" x2="1" y1="0" y2="1">
					<stop offset="0" stopColor="currentColor" stopOpacity="0.12" />
					<stop offset="0.5" stopColor="currentColor" stopOpacity="0.03" />
					<stop offset="1" stopColor="var(--fa-success)" stopOpacity="0.1" />
				</linearGradient>
				<linearGradient id={dagEdgeGradientId} x1="0" x2="1" y1="0" y2="0">
					<stop offset="0" stopColor="currentColor" stopOpacity="0.18" />
					<stop offset="0.42" stopColor="currentColor" stopOpacity="0.85" />
					<stop offset="1" stopColor="var(--fa-success)" stopOpacity="0.7" />
				</linearGradient>
				<linearGradient id={dagNodeGradientId} x1="0" x2="0" y1="0" y2="1">
					<stop offset="0" stopColor="var(--fa-panel-1)" stopOpacity="0.96" />
					<stop offset="1" stopColor="var(--fa-panel-2)" stopOpacity="0.88" />
				</linearGradient>
				<linearGradient id={dagResultGradientId} x1="0" x2="1" y1="0" y2="1">
					<stop offset="0" stopColor="var(--fa-success)" stopOpacity="0.34" />
					<stop offset="1" stopColor="currentColor" stopOpacity="0.16" />
				</linearGradient>
				<pattern
					id={dagGridPatternId}
					width="18"
					height="18"
					patternUnits="userSpaceOnUse"
				>
					<path
						d="M18 0H0V18"
						fill="none"
						stroke="color-mix(in srgb, currentColor 16%, transparent)"
						strokeWidth="0.6"
					/>
				</pattern>
			</defs>
			<rect
				className="dag-shell"
				x="4"
				y="4"
				width="296"
				height="116"
				rx="26"
				fill={`url(#${dagShellGradientId})`}
				stroke="color-mix(in srgb, currentColor 24%, var(--fa-border-subtle))"
				strokeWidth="1"
			/>
			<rect
				className="dag-grid"
				x="16"
				y="14"
				width="272"
				height="96"
				rx="20"
				fill={`url(#${dagGridPatternId})`}
				opacity="0.52"
			/>
			<path
				className="dag-thread is-shadow"
				d="M66 62 C82 62 78 32 94 32 H169"
			/>
			<path
				className="dag-thread is-shadow"
				d="M66 62 C82 62 78 92 94 92 H169"
			/>
			<path
				className="dag-thread is-shadow"
				d="M225 32 C242 32 240 62 252 62"
			/>
			<path
				className="dag-thread is-shadow"
				d="M225 92 C242 92 240 62 252 62"
			/>
			<path
				className="dag-thread is-active"
				d="M66 62 C82 62 78 32 94 32 H169"
				stroke={`url(#${dagEdgeGradientId})`}
				strokeWidth="2.7"
			/>
			<path
				className="dag-thread is-active"
				d="M66 62 C82 62 78 92 94 92 H169"
				stroke={`url(#${dagEdgeGradientId})`}
				strokeWidth="2.7"
			/>
			<path
				className="dag-thread"
				d="M225 32 C242 32 240 62 252 62"
				stroke={`url(#${dagEdgeGradientId})`}
			/>
			<path
				className="dag-thread"
				d="M225 92 C242 92 240 62 252 62"
				stroke={`url(#${dagEdgeGradientId})`}
			/>
			<path
				className="dag-signal"
				d="M66 62 C82 62 78 32 94 32 H169 H225 C242 32 240 62 252 62"
				stroke={`url(#${dagEdgeGradientId})`}
			/>
			<circle
				className="dag-junction"
				cx="82"
				cy="62"
				r="3.5"
				fill="var(--fa-panel-1)"
				stroke="color-mix(in srgb, currentColor 54%, var(--fa-border-subtle))"
				strokeWidth="1.2"
			/>
			<circle
				className="dag-junction"
				cx="240"
				cy="62"
				r="3.5"
				fill="var(--fa-panel-1)"
				stroke="color-mix(in srgb, currentColor 54%, var(--fa-border-subtle))"
				strokeWidth="1.2"
			/>
			<g className="dag-node is-goal" transform="translate(16 47)">
				<rect
					width="52"
					height="30"
					rx="15"
					fill={`url(#${dagNodeGradientId})`}
				/>
				<circle
					cx="12"
					cy="15"
					r="3.2"
					fill="color-mix(in srgb, currentColor 78%, white 22%)"
				/>
				<text x="30" y="19">
					Goal
				</text>
			</g>
			<g className="dag-node" transform="translate(94 17)">
				<rect
					width="58"
					height="30"
					rx="15"
					fill={`url(#${dagNodeGradientId})`}
				/>
				<text x="29" y="19">
					Plan
				</text>
			</g>
			<g className="dag-node" transform="translate(94 77)">
				<rect
					width="58"
					height="30"
					rx="15"
					fill={`url(#${dagNodeGradientId})`}
				/>
				<text x="29" y="19">
					Build
				</text>
			</g>
			<g className="dag-node" transform="translate(169 17)">
				<rect
					width="58"
					height="30"
					rx="15"
					fill={`url(#${dagNodeGradientId})`}
				/>
				<text x="29" y="19">
					Check
				</text>
			</g>
			<g className="dag-node" transform="translate(169 77)">
				<rect
					width="58"
					height="30"
					rx="15"
					fill={`url(#${dagNodeGradientId})`}
				/>
				<text x="29" y="19">
					Merge
				</text>
			</g>
			<g className="dag-node is-result" transform="translate(252 46)">
				<rect
					width="42"
					height="32"
					rx="16"
					fill={`url(#${dagResultGradientId})`}
				/>
				<path
					d="M12 17.5l4 4 9-10"
					fill="none"
					stroke="color-mix(in srgb, var(--fa-success) 78%, var(--fa-text))"
					strokeLinecap="round"
					strokeLinejoin="round"
					strokeWidth="2"
				/>
				<text x="24" y="20">
					Result
				</text>
			</g>
		</svg>
	);
}
