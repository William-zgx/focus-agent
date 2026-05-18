import type { ContextUsageResponse } from "@focus-agent/web-sdk";
import type { CSSProperties } from "react";

import {
	contextUsagePercent,
	contextUsageRemainingPercent,
	contextUsageTone,
	formatContextMarkerCount,
	providerLogoLetter,
	providerLogoSlug,
	providerOptionLabel,
	shouldShowContextCompactAction,
} from "./message-composer-helpers";

export function ProviderLogo({
	provider,
	providerLabel,
	providerLogoSlug: configuredLogoSlug,
	providerLogoLetter: configuredLogoLetter,
	isChineseUi,
}: {
	provider: string;
	providerLabel?: string;
	providerLogoSlug?: string | null;
	providerLogoLetter?: string | null;
	isChineseUi: boolean;
}) {
	const label = providerOptionLabel(provider, isChineseUi, providerLabel);
	const logoSlug = providerLogoSlug(configuredLogoSlug);
	const logoLetter = providerLogoLetter(provider, configuredLogoLetter);
	return (
		<span className="fa-composer-model-logo-shell" aria-hidden="true">
			{logoSlug ? (
				<img
					className="fa-composer-model-logo"
					alt={`${label} logo`}
					loading="lazy"
					referrerPolicy="no-referrer"
					src={`https://models.dev/logos/${logoSlug}.svg`}
					onError={(event) => {
						event.currentTarget.style.display = "none";
					}}
				/>
			) : null}
			<span className="fa-composer-model-logo-fallback">{logoLetter}</span>
		</span>
	);
}

export function ContextUsageMeter({
	usage,
	error,
	isChineseUi,
	isLoading = false,
	isCompacting = false,
	isDisabled = false,
	onCompact,
}: {
	usage?: ContextUsageResponse | null;
	error?: string;
	isChineseUi: boolean;
	isLoading?: boolean;
	isCompacting?: boolean;
	isDisabled?: boolean;
	onCompact?: () => Promise<void> | void;
}) {
	const percent = contextUsagePercent(usage);
	const remainingPercent = contextUsageRemainingPercent(usage);
	const tone = contextUsageTone(usage);
	const used = formatContextMarkerCount(Number(usage?.used_tokens ?? 0));
	const limit = formatContextMarkerCount(Number(usage?.token_limit ?? 0));
	const showCompact = shouldShowContextCompactAction(usage);
	const showManualHint = !showCompact && Number(usage?.used_ratio ?? 0) >= 0.7;
	const progressDegrees = Math.max(0, Math.min(360, percent * 3.6));
	const title = isChineseUi
		? `背景信息窗口：${percent}% 已用`
		: `Background context window: ${percent}% used`;
	const statusText = error
		? error
		: !usage
			? isChineseUi
				? "正在估算当前背景信息窗口"
				: "Estimating the current background context window"
			: usage.status === "error"
				? isChineseUi
					? "背景信息窗口估算失败"
					: "Background context estimate failed"
				: isCompacting
					? isChineseUi
						? "Focus Agent 正在压缩背景信息"
						: "Focus Agent is compacting background context"
					: showManualHint
						? isChineseUi
							? "可手动压缩；接近上限时会自动压缩背景信息"
							: "Manual compaction is available; Focus Agent also auto-compacts near the limit"
						: showCompact
							? isChineseUi
								? "Focus Agent 会在接近上限时自动压缩背景信息"
								: "Focus Agent auto-compacts background context near the limit"
							: isChineseUi
								? "Focus Agent 会在接近上限时自动压缩背景信息"
								: "Focus Agent auto-compacts background context near the limit";

	return (
		<span
			className={`fa-context-meter ${tone} ${isLoading ? "is-loading" : ""} ${
				isCompacting ? "is-compacting" : ""
			}`.trim()}
		>
			<button
				className="fa-context-meter-trigger"
				style={
					{ "--fa-context-progress": `${progressDegrees}deg` } as CSSProperties
				}
				type="button"
				aria-label={title}
				aria-busy={isLoading || isCompacting}
				title={title}
			>
				<span className="fa-context-meter-ring" aria-hidden="true" />
				<span className="sr-only">{title}</span>
			</button>
			<output className="fa-context-meter-popover">
				<span className="fa-context-meter-title">
					{isChineseUi ? "背景信息窗口:" : "Background context window:"}
				</span>
				<span className="fa-context-meter-usage">
					{isChineseUi
						? `${percent}% 已用（剩余 ${remainingPercent}%）`
						: `${percent}% used (${remainingPercent}% remaining)`}
				</span>
				<span className="fa-context-meter-window">
					{isChineseUi
						? `已用 ${used} 标记，共 ${limit}`
						: `${used} context tokens used of ${limit}`}
				</span>
				<span className="fa-context-meter-status">{statusText}</span>
				{showCompact || isCompacting ? (
					<button
						className="fa-context-meter-compact"
						disabled={isDisabled || isCompacting || !onCompact}
						onClick={() => void onCompact?.()}
						type="button"
					>
						{isCompacting
							? isChineseUi
								? "压缩中"
								: "Compacting"
							: isChineseUi
								? "压缩背景信息"
								: "Compact context"}
					</button>
				) : null}
			</output>
		</span>
	);
}
