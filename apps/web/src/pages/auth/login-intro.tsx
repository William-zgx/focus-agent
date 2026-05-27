import { type CSSProperties, useId } from "react";

import { appEnv } from "@/shared/config/env";
import { FocusAgentBrand } from "@/shared/ui/focus-agent-brand";

function TaskCard({
	accent,
	cardShadowId,
	className,
	width = 132,
	x,
	y,
}: {
	accent: "blue" | "teal" | "warm";
	cardShadowId: string;
	className?: string;
	width?: number;
	x: number;
	y: number;
}) {
	return (
		<g
			className={`fa-auth-login-card ${className ?? ""}`}
			filter={`url(#${cardShadowId})`}
		>
			<rect height="58" rx="13" width={width} x={x} y={y} />
			<rect
				className={`fa-auth-login-chip is-${accent}`}
				height="18"
				rx="5"
				width="18"
				x={x + 18}
				y={y + 20}
			/>
			<rect
				className="fa-auth-login-line is-strong"
				height="5"
				rx="2.5"
				width="58"
				x={x + 50}
				y={y + 18}
			/>
			<rect
				className="fa-auth-login-line"
				height="5"
				rx="2.5"
				width={Math.min(76, width - 62)}
				x={x + 50}
				y={y + 34}
			/>
			<circle cx={x + width - 20} cy={y + 42} r="2.5" />
			<circle cx={x + width - 10} cy={y + 42} r="2.5" />
		</g>
	);
}

export function LoginIntro() {
	const generatedId = useId().replaceAll(":", "");
	const lineCoolId = `${generatedId}-fa-login-line-cool`;
	const lineWarmId = `${generatedId}-fa-login-line-warm`;
	const cardId = `${generatedId}-fa-login-card`;
	const blueChipId = `${generatedId}-fa-login-blue-chip`;
	const tealChipId = `${generatedId}-fa-login-teal-chip`;
	const orangeChipId = `${generatedId}-fa-login-orange-chip`;
	const cardShadowId = `${generatedId}-fa-login-card-shadow`;
	const warmShadowId = `${generatedId}-fa-login-warm-shadow`;
	const paintUrls = {
		"--fa-login-blue-chip": `url(#${blueChipId})`,
		"--fa-login-card": `url(#${cardId})`,
		"--fa-login-line-cool": `url(#${lineCoolId})`,
		"--fa-login-line-warm": `url(#${lineWarmId})`,
		"--fa-login-orange-chip": `url(#${orangeChipId})`,
		"--fa-login-teal-chip": `url(#${tealChipId})`,
	} as CSSProperties;
	const hasWorkspace =
		appEnv.features.agentTeam ||
		appEnv.features.agentGovernance ||
		appEnv.features.agentMemory ||
		appEnv.features.observability;
	const introTitle = hasWorkspace
		? "分支优先的 Agent 工作台"
		: "对话与管理优先的 Focus Agent";
	const introDescription = hasWorkspace
		? "让长任务在对话、任务分工和证据复盘之间保持清晰推进。"
		: "在手机端继续长上下文对话、分支探索与系统管理。";

	return (
		<section className="fa-auth-login-intro">
			<div className="fa-auth-login-brand">
				<FocusAgentBrand />
			</div>
			<h1>{introTitle}</h1>
			<p className="fa-auth-description">{introDescription}</p>
			<div className="fa-auth-login-visual" aria-hidden="true">
				<svg
					className="fa-auth-login-illustration"
					role="presentation"
					style={paintUrls}
					viewBox="0 10 760 250"
				>
					<defs>
						<linearGradient id={lineCoolId} x1="0" x2="1" y1="0" y2="0">
							<stop offset="0" stopColor="#2f80ed" />
							<stop offset="0.55" stopColor="#38bdf8" />
							<stop offset="1" stopColor="#35d0bd" />
						</linearGradient>
						<linearGradient id={lineWarmId} x1="0" x2="1" y1="0" y2="0">
							<stop offset="0" stopColor="#2f80ed" />
							<stop offset="1" stopColor="#fb923c" />
						</linearGradient>
						<linearGradient id={cardId} x1="0" x2="0" y1="0" y2="1">
							<stop offset="0" stopColor="#ffffff" />
							<stop offset="1" stopColor="#f8fbff" />
						</linearGradient>
						<linearGradient id={blueChipId} x1="0" x2="1" y1="0" y2="1">
							<stop offset="0" stopColor="#67e8f9" />
							<stop offset="1" stopColor="#2563eb" />
						</linearGradient>
						<linearGradient id={tealChipId} x1="0" x2="1" y1="0" y2="1">
							<stop offset="0" stopColor="#5eead4" />
							<stop offset="1" stopColor="#14b8a6" />
						</linearGradient>
						<linearGradient id={orangeChipId} x1="0" x2="1" y1="0" y2="1">
							<stop offset="0" stopColor="#fdba74" />
							<stop offset="1" stopColor="#f97316" />
						</linearGradient>
						<filter id={cardShadowId} colorInterpolationFilters="sRGB">
							<feDropShadow
								dx="0"
								dy="9"
								floodColor="#1d4ed8"
								floodOpacity="0.12"
								stdDeviation="8"
							/>
							<feDropShadow
								dx="0"
								dy="2"
								floodColor="#0f172a"
								floodOpacity="0.07"
								stdDeviation="2"
							/>
						</filter>
						<filter id={warmShadowId} colorInterpolationFilters="sRGB">
							<feDropShadow
								dx="0"
								dy="12"
								floodColor="#fb923c"
								floodOpacity="0.22"
								stdDeviation="11"
							/>
							<feDropShadow
								dx="0"
								dy="2"
								floodColor="#0f172a"
								floodOpacity="0.07"
								stdDeviation="2"
							/>
						</filter>
					</defs>

					<g className="fa-auth-login-illustration-lines">
						<path d="M 28 134 H 102" />
						<path d="M 232 134 C 270 134 270 64 306 64" />
						<path d="M 232 134 C 270 134 270 204 306 204" />
						<path d="M 448 64 H 482" />
						<path d="M 448 204 H 482" />
						<path d="M 604 64 C 638 64 632 134 622 134" />
						<path d="M 604 204 C 638 204 632 134 622 134" />
						<path d="M 665 134 H 672" />
					</g>
					<g className="fa-auth-login-illustration-dashes">
						<path d="M 246 102 C 270 80 284 70 304 64" />
						<path d="M 246 166 C 270 188 284 198 304 204" />
						<path d="M 608 92 C 624 108 632 124 634 134" />
					</g>

					<circle className="fa-auth-login-orbit" cx="28" cy="134" r="29" />
					<circle
						className="fa-auth-login-orbit is-inner"
						cx="28"
						cy="134"
						r="16"
					/>
					<circle
						className="fa-auth-login-node is-start"
						cx="28"
						cy="134"
						r="9"
					/>
					<circle className="fa-auth-login-node" cx="232" cy="134" r="18" />
					<circle className="fa-auth-login-node-dot" cx="232" cy="134" r="6" />
					<circle className="fa-auth-login-node" cx="644" cy="134" r="18" />
					<circle
						className="fa-auth-login-node-dot is-warm"
						cx="644"
						cy="134"
						r="6"
					/>

					<TaskCard
						accent="blue"
						cardShadowId={cardShadowId}
						className="is-left"
						width={118}
						x={84}
						y={105}
					/>
					<TaskCard
						accent="teal"
						cardShadowId={cardShadowId}
						className="is-top"
						width={128}
						x={314}
						y={35}
					/>
					<TaskCard
						accent="blue"
						cardShadowId={cardShadowId}
						className="is-bottom"
						width={128}
						x={314}
						y={175}
					/>
					<TaskCard
						accent="teal"
						cardShadowId={cardShadowId}
						className="is-media"
						width={112}
						x={488}
						y={35}
					/>
					<TaskCard
						accent="blue"
						cardShadowId={cardShadowId}
						className="is-chart"
						width={112}
						x={488}
						y={175}
					/>

					<g className="fa-auth-login-status" filter={`url(#${cardShadowId})`}>
						<circle cx="464" cy="64" r="19" />
						<path d="M 456 64 L 463 71 L 474 57" />
						<circle cx="464" cy="204" r="19" />
						<path d="M 456 204 L 463 211 L 474 197" />
					</g>

					<g
						className="fa-auth-login-card is-final"
						filter={`url(#${warmShadowId})`}
					>
						<rect height="58" rx="13" width="78" x="676" y="105" />
						<rect
							className="fa-auth-login-chip is-warm"
							height="18"
							rx="5"
							width="18"
							x="692"
							y="125"
						/>
						<rect
							className="fa-auth-login-line is-strong"
							height="5"
							rx="2.5"
							width="24"
							x="722"
							y="124"
						/>
						<rect
							className="fa-auth-login-line"
							height="5"
							rx="2.5"
							width="28"
							x="722"
							y="141"
						/>
					</g>
					<g className="fa-auth-login-sparkles">
						<path d="M 730 74 L 734 84 L 744 88 L 734 92 L 730 102 L 726 92 L 716 88 L 726 84 Z" />
						<path d="M 710 66 L 713 73 L 720 76 L 713 79 L 710 86 L 707 79 L 700 76 L 707 73 Z" />
					</g>
				</svg>
			</div>
		</section>
	);
}
