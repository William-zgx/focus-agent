import type { ContextUsageResponse, FocusAgentModelOption } from "@focus-agent/web-sdk";
import type { KeyboardEvent } from "react";

export { mergedBranchReadOnlyLabel } from "@/entities/messages/message-list-helpers";

export function groupByProvider(models: FocusAgentModelOption[]) {
  const groups = new Map<string, FocusAgentModelOption[]>();
  for (const model of models) {
    const key = model.provider || "openai";
    groups.set(key, [...(groups.get(key) ?? []), model]);
  }
  return [...groups.entries()];
}

export function chooseModelLabel(isChineseUi: boolean) {
  return isChineseUi ? "选择模型" : "Choose a model";
}

export function providerOptionLabel(provider: string, isChineseUi: boolean) {
  if (provider === "moonshot") return "Moonshot AI";
  if (provider === "ollama") return "Ollama";
  if (provider === "anthropic") return "Anthropic";
  return isChineseUi ? "OpenAI 兼容" : "OpenAI Compatible";
}

export function providerLogoSlug(provider: string) {
  if (provider === "moonshot") return "moonshotai";
  if (provider === "ollama") return "ollama";
  if (provider === "anthropic") return "anthropic";
  return "openai";
}

export function providerLogoLetter(provider: string) {
  if (provider === "moonshot") return "K";
  if (provider === "ollama") return "O";
  if (provider === "anthropic") return "A";
  return "O";
}

export function modelDisplayName(model: FocusAgentModelOption | undefined) {
  if (!model) return "";
  return String(model.name || model.id || model.label || "").trim();
}

export function normalizeThinkingMode(value: string | undefined) {
  const normalized = String(value || "").trim().toLowerCase();
  return normalized === "enabled" || normalized === "disabled" ? normalized : "";
}

export function formatContextMarkerCount(value: number) {
  const normalized = Math.max(0, Number(value) || 0);
  if (normalized >= 1_000_000) {
    const millions = normalized / 1_000_000;
    return `${millions >= 10 ? millions.toFixed(0) : millions.toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (normalized >= 1_000) {
    const thousands = normalized / 1_000;
    return `${thousands >= 10 ? thousands.toFixed(0) : thousands.toFixed(1).replace(/\.0$/, "")}k`;
  }
  return new Intl.NumberFormat("en-US").format(Math.round(normalized));
}

export function contextUsagePercent(usage?: ContextUsageResponse | null) {
  return Math.max(0, Math.min(100, Math.round(Number(usage?.used_ratio ?? 0) * 100)));
}

export function contextUsageRemainingPercent(usage?: ContextUsageResponse | null) {
  return Math.max(0, 100 - contextUsagePercent(usage));
}

export function shouldShowContextCompactAction(usage?: ContextUsageResponse | null) {
  const ratio = Number(usage?.used_ratio ?? 0);
  return ratio >= 0.85 || usage?.status === "hot" || usage?.status === "over";
}

export function contextUsageTone(usage?: ContextUsageResponse | null) {
  if (!usage) return "is-idle";
  if (usage.status === "error") return "is-over";
  if (usage.status === "over" || Number(usage.used_ratio || 0) >= 0.92) return "is-over";
  if (usage.status === "hot" || Number(usage.used_ratio || 0) >= 0.85) return "is-hot";
  if (usage.status === "warm" || Number(usage.used_ratio || 0) >= 0.7) return "is-warm";
  return "is-ok";
}

export function effectiveThinkingModeForModel(
  model: FocusAgentModelOption | undefined,
  preferredMode: string | undefined = "",
) {
  if (!model?.supports_thinking) {
    return "";
  }
  return normalizeThinkingMode(preferredMode);
}

export function nextThinkingModeForModelSelection(
  nextModel: FocusAgentModelOption | undefined,
  nextModelId: string,
  currentModelId: string,
  currentMode: string | undefined,
) {
  if (!nextModel?.supports_thinking) {
    return "";
  }
  if (nextModelId === currentModelId) {
    return normalizeThinkingMode(currentMode);
  }
  return "";
}

export function thinkingModeRequestValueForModel(
  model: FocusAgentModelOption | undefined,
  preferredMode: string | undefined,
) {
  if (!model?.supports_thinking) {
    return undefined;
  }
  return effectiveThinkingModeForModel(model, preferredMode);
}

function thinkingEnabledLabel(isChineseUi: boolean) {
  return isChineseUi ? "开始思考" : "Start thinking";
}

function thinkingDisabledLabel(isChineseUi: boolean) {
  return isChineseUi ? "关闭思考" : "Stop thinking";
}

function thinkingAvailableLabel(isChineseUi: boolean) {
  return isChineseUi ? "支持思考，可手动切换" : "Thinking available, toggle manually";
}

export function thinkingUnavailableLabel(isChineseUi: boolean) {
  return isChineseUi ? "不支持思考切换" : "Thinking unavailable";
}

function thinkingOnStatusLabel(isChineseUi: boolean) {
  return isChineseUi ? "思考已开启" : "Thinking on";
}

function thinkingOffStatusLabel(isChineseUi: boolean) {
  return isChineseUi ? "思考已关闭" : "Thinking off";
}

function thinkingStatusText(mode: string, isChineseUi: boolean) {
  return mode === "enabled" ? thinkingOnStatusLabel(isChineseUi) : thinkingOffStatusLabel(isChineseUi);
}

export function thinkingToggleActionLabel(mode: string, isChineseUi: boolean) {
  return mode === "enabled" ? thinkingDisabledLabel(isChineseUi) : thinkingEnabledLabel(isChineseUi);
}

export function thinkingToggleTitle(mode: string, isChineseUi: boolean) {
  return mode === "enabled"
    ? isChineseUi
      ? "思考已开启，点击关闭思考"
      : "Thinking is on. Click to stop thinking"
    : isChineseUi
      ? "思考已关闭，点击开始思考"
      : "Thinking is off. Click to start thinking";
}

export function thinkingOptionMetaLabel(
  model: FocusAgentModelOption,
  thinkingMode: string,
  isChineseUi: boolean,
) {
  if (!model.supports_thinking) {
    return thinkingUnavailableLabel(isChineseUi);
  }
  return thinkingMode ? thinkingStatusText(thinkingMode, isChineseUi) : thinkingAvailableLabel(isChineseUi);
}

export function handleModelOptionKeyDown(
  event: KeyboardEvent<HTMLDivElement>,
  onSelect: () => void,
) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  event.preventDefault();
  onSelect();
}
