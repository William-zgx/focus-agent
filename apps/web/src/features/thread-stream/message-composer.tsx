import type { FocusAgentModelOption } from "@focus-agent/web-sdk";
import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

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
  ) => Promise<void>;
  onStopStreaming: () => void;
  selectedModel?: string;
  selectedThinkingMode?: string;
  editDraft?: { id: string; content: string } | null;
  onClearEditDraft?: () => void;
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

function effectiveThinkingModeForModel(
  model: FocusAgentModelOption | undefined,
  preferredMode: string | undefined = "",
) {
  if (!model?.supports_thinking) {
    return "";
  }
  return normalizeThinkingMode(preferredMode) || "disabled";
}

function thinkingEnabledLabel(isChineseUi: boolean) {
  return isChineseUi ? "开启" : "On";
}

function thinkingDisabledLabel(isChineseUi: boolean) {
  return isChineseUi ? "关闭" : "Off";
}

function thinkingAvailableLabel(isChineseUi: boolean) {
  return isChineseUi ? "支持思考" : "Thinking available";
}

function thinkingDefaultOnLabel(isChineseUi: boolean) {
  return isChineseUi ? "支持思考，默认开启" : "Thinking available, default on";
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

function thinkingOptionMetaLabel(model: FocusAgentModelOption, isChineseUi: boolean) {
  if (!model.supports_thinking) {
    return thinkingUnavailableLabel(isChineseUi);
  }
  return model.default_thinking_enabled
    ? thinkingDefaultOnLabel(isChineseUi)
    : thinkingAvailableLabel(isChineseUi);
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

export function MessageComposer({
  isReadOnly = false,
  isStreaming,
  onSendMessage,
  onStopStreaming,
  selectedModel,
  selectedThinkingMode,
  editDraft,
  onClearEditDraft,
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
          ? thinkingStatusText(activeThinkingMode, isChineseUi)
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
    setMessage("");
    editSignatureRef.current = "";
    onClearEditDraft?.();
    await onSendMessage(trimmed, {
      model: modelId || undefined,
      thinkingMode: thinkingMode || undefined,
    });
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
    setThinkingMode((current) => effectiveThinkingModeForModel(nextModel, current));
    setModelPanelOpen(false);
  }

  function selectModelThinkingMode(nextModelId: string, nextThinkingMode: "enabled" | "disabled") {
    setModelId(nextModelId);
    setThinkingMode(nextThinkingMode);
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
                                          isChineseUi,
                                        )}`}
                                      </div>
                                    </div>
                                  </div>
                                  <div className="fa-composer-model-option-trailing">
                                    {model.supports_thinking ? (
                                      <span
                                        className="fa-composer-model-thinking-toggle"
                                        role="group"
                                        aria-label={`${modelDisplayName(model)} ${
                                          isChineseUi ? "思考模式" : "Thinking mode"
                                        }`}
                                      >
                                        <button
                                          className={`fa-thinking-toggle ${
                                            optionThinkingMode === "enabled" ? "is-active" : ""
                                          }`}
                                          aria-pressed={optionThinkingMode === "enabled"}
                                          onClick={(event) => {
                                            event.preventDefault();
                                            event.stopPropagation();
                                            selectModelThinkingMode(model.id, "enabled");
                                          }}
                                          type="button"
                                        >
                                          {thinkingEnabledLabel(isChineseUi)}
                                        </button>
                                        <button
                                          className={`fa-thinking-toggle ${
                                            optionThinkingMode === "disabled" ? "is-active" : ""
                                          }`}
                                          aria-pressed={optionThinkingMode === "disabled"}
                                          onClick={(event) => {
                                            event.preventDefault();
                                            event.stopPropagation();
                                            selectModelThinkingMode(model.id, "disabled");
                                          }}
                                          type="button"
                                        >
                                          {thinkingDisabledLabel(isChineseUi)}
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
