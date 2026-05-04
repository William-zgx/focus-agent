import type { FocusAgentModelOption } from "@focus-agent/web-sdk";
import { useEffect, useMemo, useRef } from "react";

import { ProviderLogo } from "./message-composer-components";
import {
  chooseModelLabel,
  effectiveThinkingModeForModel,
  groupByProvider,
  handleModelOptionKeyDown,
  modelDisplayName,
  providerOptionLabel,
  thinkingOptionMetaLabel,
  thinkingToggleActionLabel,
  thinkingToggleTitle,
  thinkingUnavailableLabel,
} from "./message-composer-helpers";

export function MessageComposerModelSelector({
  activeModel,
  activeThinkingMode,
  allModels,
  isChineseUi,
  isStreaming,
  modelId,
  modelPanelOpen,
  onModelPanelOpenChange,
  onSelectModel,
  onToggleModelThinkingMode,
  thinkingMode,
}: {
  activeModel?: FocusAgentModelOption;
  activeThinkingMode: string;
  allModels: FocusAgentModelOption[];
  isChineseUi: boolean;
  isStreaming: boolean;
  modelId: string;
  modelPanelOpen: boolean;
  onModelPanelOpenChange: (isOpen: boolean | ((value: boolean) => boolean)) => void;
  onSelectModel: (modelId: string) => void;
  onToggleModelThinkingMode: (modelId: string, currentThinkingMode: string) => void;
  thinkingMode: string;
}) {
  const modelPanelRef = useRef<HTMLDivElement | null>(null);
  const modelTriggerRef = useRef<HTMLButtonElement | null>(null);
  const groupedModels = useMemo(() => groupByProvider(allModels), [allModels]);
  const activeProviderLabel = activeModel
    ? providerOptionLabel(activeModel.provider, isChineseUi)
    : chooseModelLabel(isChineseUi);
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
      onModelPanelOpenChange(false);
    }

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        onModelPanelOpenChange(false);
      }
    }

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [modelPanelOpen, onModelPanelOpenChange]);

  return (
    <div className="fa-composer-model-anchor fa-composer-model-shell">
      <button
        ref={modelTriggerRef}
        aria-expanded={modelPanelOpen}
        className="fa-composer-model-trigger"
        disabled={isStreaming || allModels.length === 0}
        onClick={() => onModelPanelOpenChange((value) => !value)}
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
                        onKeyDown={(event) => handleModelOptionKeyDown(event, () => onSelectModel(model.id))}
                        onClick={() => onSelectModel(model.id)}
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
                                  onToggleModelThinkingMode(model.id, optionThinkingMode);
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
  );
}
