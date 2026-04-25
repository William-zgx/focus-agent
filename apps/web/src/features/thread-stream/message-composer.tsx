import type { ContextUsageResponse, FocusAgentModelOption } from "@focus-agent/web-sdk";
import { type CSSProperties, FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useModels } from "@/features/models/use-models";
import { tooltipProps } from "@/shared/ui/tooltip";

interface MessageComposerProps {
  isReadOnly?: boolean;
  isStreaming: boolean;
  onSendMessage: (
    message: string,
    overrides?: {
      model?: string;
      thinkingMode?: string;
    },
  ) => Promise<{ ok: boolean }>;
  onStopStreaming: () => void;
  selectedModel?: string;
  selectedThinkingMode?: string;
  editDraft?: { id: string; content: string } | null;
  onClearEditDraft?: () => void;
  contextUsage?: ContextUsageResponse | null;
  contextUsageError?: string;
  isContextUsageLoading?: boolean;
  isCompactingContext?: boolean;
  onCompactContext?: () => Promise<void> | void;
  onPreviewContextUsage?: (draftMessage: string) => void;
}

function mergedBranchReadOnlyLabel(isChineseUi: boolean) {
  return isChineseUi ? "已合并分支不允许继续对话" : "Merged branches are read-only";
}

function groupByProvider(models: FocusAgentModelOption[]) {
  const groups = new Map<string, FocusAgentModelOption[]>();
  for (const model of models) {
    const key = model.provider || "openai";
    groups.set(key, [...(groups.get(key) ?? []), model]);
  }
  return [...groups.entries()];
}

function chooseModelLabel(isChineseUi: boolean) {
  return isChineseUi ? "选择模型" : "Choose a model";
}

function providerOptionLabel(provider: string, isChineseUi: boolean) {
  if (provider === "moonshot") return "Moonshot AI";
  if (provider === "ollama") return "Ollama";
  if (provider === "anthropic") return "Anthropic";
  return isChineseUi ? "OpenAI 兼容" : "OpenAI Compatible";
}

function providerLogoSlug(provider: string) {
  if (provider === "moonshot") return "moonshotai";
  if (provider === "ollama") return "ollama";
  if (provider === "anthropic") return "anthropic";
  return "openai";
}

function providerLogoLetter(provider: string) {
  if (provider === "moonshot") return "K";
  if (provider === "ollama") return "O";
  if (provider === "anthropic") return "A";
  return "O";
}

function modelDisplayName(model: FocusAgentModelOption | undefined) {
  if (!model) return "";
  return String(model.name || model.id || model.label || "").trim();
}

function normalizeThinkingMode(value: string | undefined) {
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

function thinkingUnavailableLabel(isChineseUi: boolean) {
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

function thinkingToggleActionLabel(mode: string, isChineseUi: boolean) {
  return mode === "enabled" ? thinkingDisabledLabel(isChineseUi) : thinkingEnabledLabel(isChineseUi);
}

function thinkingToggleTitle(mode: string, isChineseUi: boolean) {
  return mode === "enabled"
    ? isChineseUi
      ? "思考已开启，点击关闭思考"
      : "Thinking is on. Click to stop thinking"
    : isChineseUi
      ? "思考已关闭，点击开始思考"
      : "Thinking is off. Click to start thinking";
}

function thinkingOptionMetaLabel(
  model: FocusAgentModelOption,
  thinkingMode: string,
  isChineseUi: boolean,
) {
  if (!model.supports_thinking) {
    return thinkingUnavailableLabel(isChineseUi);
  }
  return thinkingMode ? thinkingStatusText(thinkingMode, isChineseUi) : thinkingAvailableLabel(isChineseUi);
}

function handleModelOptionKeyDown(
  event: KeyboardEvent<HTMLDivElement>,
  onSelect: () => void,
) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  event.preventDefault();
  onSelect();
}

function ProviderLogo({
  provider,
  isChineseUi,
}: {
  provider: string;
  isChineseUi: boolean;
}) {
  const providerLabel = providerOptionLabel(provider, isChineseUi);
  return (
    <span className="fa-composer-model-logo-shell" aria-hidden="true">
      <img
        className="fa-composer-model-logo"
        alt={`${providerLabel} logo`}
        loading="lazy"
        referrerPolicy="no-referrer"
        src={`https://models.dev/logos/${providerLogoSlug(provider)}.svg`}
        onError={(event) => {
          event.currentTarget.style.display = "none";
        }}
      />
      <span className="fa-composer-model-logo-fallback">{providerLogoLetter(provider)}</span>
    </span>
  );
}

function ContextUsageMeter({
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
        style={{ "--fa-context-progress": `${progressDegrees}deg` } as CSSProperties}
        type="button"
        aria-label={title}
        aria-busy={isLoading || isCompacting}
        title={title}
      >
        <span className="fa-context-meter-ring" aria-hidden="true" />
        <span className="sr-only">{title}</span>
      </button>
      <span className="fa-context-meter-popover" role="status">
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
      </span>
    </span>
  );
}

export function MessageComposer({
  isReadOnly = false,
  isStreaming,
  onSendMessage,
  onStopStreaming,
  selectedModel,
  selectedThinkingMode,
  editDraft,
  onClearEditDraft,
  contextUsage,
  contextUsageError = "",
  isContextUsageLoading = false,
  isCompactingContext = false,
  onCompactContext,
  onPreviewContextUsage,
}: MessageComposerProps) {
  const { data } = useModels();
  const { isChineseUi } = useShellUi();
  const [message, setMessage] = useState("");
  const [modelId, setModelId] = useState(selectedModel ?? "");
  const [thinkingMode, setThinkingMode] = useState(selectedThinkingMode ?? "");
  const [modelPanelOpen, setModelPanelOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const modelPanelRef = useRef<HTMLDivElement | null>(null);
  const modelTriggerRef = useRef<HTMLButtonElement | null>(null);
  const editSignatureRef = useRef<string>("");
  const contextPreviewTimerRef = useRef<number | null>(null);

  const allModels = data?.models ?? [];
  const activeModel =
    allModels.find((item: FocusAgentModelOption) => item.id === modelId) ?? allModels[0];
  const activeProviderLabel = activeModel
    ? providerOptionLabel(activeModel.provider, isChineseUi)
    : chooseModelLabel(isChineseUi);
  const activeThinkingMode = effectiveThinkingModeForModel(activeModel, thinkingMode);
  const activeModelLabel = activeModel
    ? modelDisplayName(activeModel)
    : isChineseUi
      ? "加载模型中..."
      : "Loading models...";
  const activeModelTitle = activeModel
    ? `${modelDisplayName(activeModel)} · ${activeProviderLabel}`
    : isChineseUi
      ? "选择模型"
      : "Choose a model";
  const activeModelProvider = activeModel
    ? `${activeProviderLabel} · ${
        activeModel.supports_thinking
          ? thinkingOptionMetaLabel(activeModel, activeThinkingMode, isChineseUi)
          : thinkingUnavailableLabel(isChineseUi)
      }`
    : chooseModelLabel(isChineseUi);
  const readOnlyReason = mergedBranchReadOnlyLabel(isChineseUi);
  const groupedModels = useMemo(() => groupByProvider(allModels), [allModels]);

  function autoResizeComposer() {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "34px";
    const nextHeight = Math.max(34, Math.min(textarea.scrollHeight, 136));
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 136 ? "auto" : "hidden";
  }

  useEffect(() => {
    setModelId(selectedModel ?? "");
  }, [selectedModel]);

  useEffect(() => {
    setThinkingMode(normalizeThinkingMode(selectedThinkingMode));
  }, [selectedThinkingMode]);

  useEffect(() => {
    setThinkingMode((current) => effectiveThinkingModeForModel(activeModel, current));
  }, [activeModel]);

  useEffect(() => {
    autoResizeComposer();
  }, [message]);

  useEffect(() => {
    if (!onPreviewContextUsage || isReadOnly) return;
    if (contextPreviewTimerRef.current !== null) {
      window.clearTimeout(contextPreviewTimerRef.current);
    }
    contextPreviewTimerRef.current = window.setTimeout(() => {
      onPreviewContextUsage(message);
      contextPreviewTimerRef.current = null;
    }, 500);
    return () => {
      if (contextPreviewTimerRef.current !== null) {
        window.clearTimeout(contextPreviewTimerRef.current);
        contextPreviewTimerRef.current = null;
      }
    };
  }, [isReadOnly, message, onPreviewContextUsage]);

  useEffect(() => {
    if (!editDraft) return;
    const signature = `${editDraft.id}:${editDraft.content}`;
    if (editSignatureRef.current === signature) return;
    editSignatureRef.current = signature;
    setMessage(editDraft.content);
    setModelPanelOpen(false);
    window.requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(editDraft.content.length, editDraft.content.length);
    });
  }, [editDraft]);

  useEffect(() => {
    if (!modelPanelOpen) return;

    function handlePointerDown(event: MouseEvent) {
      const target = event.target;
      if (
        modelPanelRef.current?.contains(target as Node) ||
        modelTriggerRef.current?.contains(target as Node)
      ) {
        return;
      }
      setModelPanelOpen(false);
    }

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setModelPanelOpen(false);
      }
    }

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [modelPanelOpen]);

  async function submitMessage() {
    const trimmed = message.trim();
    if (!trimmed || isStreaming || isReadOnly) return;
    const wasEditing = Boolean(editDraft);
    if (wasEditing) {
      editSignatureRef.current = "";
      onClearEditDraft?.();
    }
    const result = await onSendMessage(trimmed, {
      model: modelId || undefined,
      ...(activeModel?.supports_thinking
        ? {
            thinkingMode: thinkingModeRequestValueForModel(activeModel, activeThinkingMode),
          }
        : {}),
    });
    if (result.ok) {
      setMessage("");
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submitMessage();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    void submitMessage();
  }

  function selectModel(nextModelId: string) {
    const nextModel = allModels.find((item: FocusAgentModelOption) => item.id === nextModelId);
    setModelId(nextModelId);
    setThinkingMode((current) =>
      nextThinkingModeForModelSelection(nextModel, nextModelId, modelId, current),
    );
    setModelPanelOpen(false);
  }

  function toggleModelThinkingMode(nextModelId: string, currentThinkingMode: string) {
    setModelId(nextModelId);
    setThinkingMode(currentThinkingMode === "enabled" ? "disabled" : "enabled");
    setModelPanelOpen(false);
  }

  return (
    <form className="fa-composer-card fa-composer" onSubmit={handleSubmit}>
      {editDraft ? (
        <div className="fa-composer-edit-banner">
          <div className="fa-composer-edit-copy">
            <div className="fa-composer-edit-title">
              {isChineseUi ? "正在编辑上一条用户消息" : "Editing previous user prompt"}
            </div>
            <div className="fa-composer-edit-note">
              {isChineseUi
                ? "重新发送后会以新的消息继续当前线程。"
                : "Sending again will continue this thread with a revised prompt."}
            </div>
          </div>
          <button className="fa-composer-edit-cancel" onClick={onClearEditDraft} type="button">
            {isChineseUi ? "取消" : "Cancel"}
          </button>
        </div>
      ) : null}

      <label
        className={`fa-composer-shell fa-composer-input-shell ${isStreaming ? "is-streaming" : ""} ${
          isReadOnly ? "is-readonly" : ""
        }`}
      >
        <span className="sr-only">
          {isReadOnly
            ? `${isChineseUi ? "消息" : "Message"} - ${readOnlyReason}`
            : isChineseUi
              ? "消息"
              : "Message"}
        </span>
        <div className="fa-composer-textarea-row fa-composer-input-row">
          <textarea
            className="fa-composer-textarea"
            placeholder={
              isReadOnly
                ? isChineseUi
                  ? "这个分支已经合并，不能继续发送消息。"
                  : "This branch has already been merged. You can no longer send messages here."
                : isChineseUi
                  ? "先在主线程里展开对话，只有在需要单独探索一个方向时再创建分支。"
                  : "Start on the main thread, then branch only when you want to explore a separate direction."
            }
            aria-label={
              isReadOnly
                ? `${isChineseUi ? "消息" : "Message"} - ${readOnlyReason}`
                : isChineseUi
                  ? "消息"
                  : "Message"
            }
            readOnly={isReadOnly}
            ref={textareaRef}
            title={isReadOnly ? readOnlyReason : undefined}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={handleComposerKeyDown}
          />
        </div>

        <div className="fa-composer-footer-row">
          <div className="fa-composer-model-row">
            <div className="fa-composer-model-controls">
              <div className="fa-composer-model-anchor fa-composer-model-shell">
                <button
                  ref={modelTriggerRef}
                  aria-expanded={modelPanelOpen}
                  className="fa-composer-model-trigger"
                  disabled={isStreaming || allModels.length === 0}
                  onClick={() => setModelPanelOpen((value) => !value)}
                  title={activeModelTitle}
                  type="button"
                >
                  <span className="fa-composer-model-trigger-copy">
                    <ProviderLogo provider={activeModel?.provider || "openai"} isChineseUi={isChineseUi} />
                    <span className="fa-composer-model-trigger-label">{activeModelLabel}</span>
                    <span className="fa-composer-model-trigger-provider">{activeModelProvider}</span>
                  </span>
                  <span className="fa-composer-model-trigger-icon" aria-hidden="true">
                    <svg viewBox="0 0 20 20">
                      <path
                        d="m6 8 4 4 4-4"
                        fill="none"
                        stroke="currentColor"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="1.8"
                      />
                    </svg>
                  </span>
                </button>

                {modelPanelOpen ? (
                  <div ref={modelPanelRef} className="fa-composer-model-panel">
                    <div className="fa-composer-model-panel-head">
                      <div className="fa-composer-model-panel-title">
                        <span>{isChineseUi ? "模型选择器" : "Model selector"}</span>
                        <small>{isChineseUi ? "命令面板" : "command palette"}</small>
                      </div>
                    </div>
                    <div className="fa-composer-model-list">
                      {groupedModels.length ? (
                        groupedModels.map(([provider, models]) => (
                          <div key={provider} className="fa-composer-model-group">
                            <div className="fa-composer-model-group-label">
                              {providerOptionLabel(provider, isChineseUi)}
                            </div>
                            {models.map((model) => {
                              const optionThinkingMode = effectiveThinkingModeForModel(
                                model,
                                model.id === modelId ? thinkingMode : "",
                              );
                              return (
                                <div
                                  key={model.id}
                                  className={`fa-composer-model-option ${
                                    model.id === modelId ? "is-selected" : ""
                                  }`}
                                  onKeyDown={(event) =>
                                    handleModelOptionKeyDown(event, () => selectModel(model.id))
                                  }
                                  onClick={() => selectModel(model.id)}
                                  role="button"
                                  tabIndex={0}
                                >
                                  <div className="fa-composer-model-option-leading">
                                    <ProviderLogo provider={model.provider} isChineseUi={isChineseUi} />
                                    <div className="fa-composer-model-option-copy">
                                      <div className="fa-composer-model-option-label">
                                        {modelDisplayName(model)}
                                      </div>
                                      <div className="fa-composer-model-option-meta">
                                        {`${providerOptionLabel(model.provider, isChineseUi)} · ${thinkingOptionMetaLabel(
                                          model,
                                          optionThinkingMode,
                                          isChineseUi,
                                        )}`}
                                      </div>
                                    </div>
                                  </div>
                                  <div className="fa-composer-model-option-trailing">
                                    {model.supports_thinking ? (
                                      <span className="fa-composer-model-thinking-toggle">
                                        <button
                                          className={`fa-thinking-toggle ${
                                            optionThinkingMode === "enabled" ? "is-active" : ""
                                          }`}
                                          aria-pressed={optionThinkingMode === "enabled"}
                                          aria-label={thinkingToggleTitle(optionThinkingMode, isChineseUi)}
                                          onClick={(event) => {
                                            event.preventDefault();
                                            event.stopPropagation();
                                            toggleModelThinkingMode(model.id, optionThinkingMode);
                                          }}
                                          title={thinkingToggleTitle(optionThinkingMode, isChineseUi)}
                                          type="button"
                                        >
                                          {thinkingToggleActionLabel(optionThinkingMode, isChineseUi)}
                                        </button>
                                      </span>
                                    ) : null}
                                    <span className="fa-composer-model-check" aria-hidden="true">
                                      ✓
                                    </span>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ))
                      ) : (
                        <div className="fa-composer-model-empty">
                          {isChineseUi ? "没有匹配的模型。" : "No matching models."}
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          <div className="fa-composer-actions-row">
            <ContextUsageMeter
              usage={contextUsage}
              error={contextUsageError}
              isChineseUi={isChineseUi}
              isLoading={isContextUsageLoading}
              isCompacting={isCompactingContext}
              isDisabled={isStreaming || isReadOnly}
              onCompact={onCompactContext}
            />
            <div className="fa-composer-inline-actions">
              <button
                className="fa-composer-icon-button is-clear"
                {...tooltipProps(isChineseUi ? "清空输入" : "Clear input")}
                disabled={isStreaming || !message}
                onClick={() => setMessage("")}
                type="button"
              >
                <span className="fa-composer-icon" aria-hidden="true">
                  <svg viewBox="0 0 20 20">
                    <path
                      d="M7.65 3.25c-.83 0-1.5.67-1.5 1.5v.4H4.5a.85.85 0 0 0 0 1.7h.58l.63 8.02a2.05 2.05 0 0 0 2.05 1.88h4.48a2.05 2.05 0 0 0 2.05-1.88l.63-8.02h.58a.85.85 0 1 0 0-1.7h-1.65v-.4c0-.83-.67-1.5-1.5-1.5h-4.7Z"
                      fill="currentColor"
                      opacity="0.9"
                    />
                    <path d="M8.5 9.1v4.2M11.5 9.1v4.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                </span>
                <span className="sr-only">{isChineseUi ? "清空输入" : "Clear input"}</span>
              </button>

              {isStreaming ? (
                <button
                  className="fa-composer-icon-button is-stop"
                  {...tooltipProps(isChineseUi ? "停止生成" : "Stop generation")}
                  type="button"
                  onClick={onStopStreaming}
                >
                  <span className="fa-composer-icon" aria-hidden="true">
                    <svg viewBox="0 0 20 20">
                      <rect x="5.2" y="5.2" width="9.6" height="9.6" rx="2.2" fill="currentColor" />
                    </svg>
                  </span>
                  <span className="sr-only">{isChineseUi ? "停止生成" : "Stop generation"}</span>
                </button>
              ) : (
                <button
                  className="fa-composer-icon-button is-send"
                  {...tooltipProps(isReadOnly ? readOnlyReason : isChineseUi ? "发送消息" : "Send message")}
                  disabled={isStreaming || isReadOnly || !message.trim()}
                  type="submit"
                >
                  <span className="fa-composer-icon" aria-hidden="true">
                    <svg viewBox="0 0 20 20">
                      <path
                        d="M16.99 3.01a.9.9 0 0 0-.94-.16L3.58 8.38a.9.9 0 0 0 .07 1.68l5 1.88 1.88 5a.9.9 0 0 0 1.68.07l5.53-12.47a.9.9 0 0 0-.75-1.53Z"
                        fill="currentColor"
                      />
                      <path
                        d="m8.14 10.12 4.25-4.25"
                        stroke="rgba(255,255,255,0.92)"
                        strokeWidth="1.4"
                        strokeLinecap="round"
                      />
                    </svg>
                  </span>
                  <span className="sr-only">{isChineseUi ? "发送消息" : "Send message"}</span>
                </button>
              )}
            </div>
          </div>
        </div>

        <span className="sr-only">
          {isChineseUi
            ? "这里先保持当前线程聚焦。只有当你想把问题拆到独立方向时，再创建分支。"
            : "Keep the current thread focused here. Create a branch only when you want to split into a separate direction."}
        </span>
      </label>
    </form>
  );
}
