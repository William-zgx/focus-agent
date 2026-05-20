import type { FormEvent } from "react";

import { AdminField, AdminPanelHeader } from "./admin-page-sections";
import {
	ConfigActions,
	ConfigSourceMeta,
	ToggleControl,
} from "./admin-config-controls";
import { EMPTY_SELECT_VALUE, uniqueList } from "./admin-config-draft-utils";
import type {
	ModelDraft,
	ModelEntryDraft,
	ModelProviderDraft,
} from "./admin-config-draft-utils";

export function ModelConfigPanel({
	choiceOptions,
	disabled,
	draft,
	isChineseUi,
	onAddProvider,
	onChange,
	onChoiceChange,
	onEntryChange,
	onProviderChange,
	onProviderRemove,
	onReset,
	onSubmit,
	pending,
	source,
}: {
	choiceOptions: string[];
	disabled: boolean;
	draft: ModelDraft;
	isChineseUi: boolean;
	onAddProvider: () => void;
	onChange: (draft: ModelDraft) => void;
	onChoiceChange: (modelId: string, checked: boolean) => void;
	onEntryChange: (index: number, patch: Partial<ModelEntryDraft>) => void;
	onProviderChange: (index: number, patch: Partial<ModelProviderDraft>) => void;
	onProviderRemove: (index: number) => void;
	onReset: () => void;
	onSubmit: (event: FormEvent<HTMLFormElement>) => void;
	pending: boolean;
	source?: { exists: boolean; path: string; writable: boolean };
}) {
	return (
		<form
			className="fa-admin-panel fa-admin-config-panel is-wide"
			onSubmit={onSubmit}
		>
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Models" : "Models"}
				status={pending ? (isChineseUi ? "保存中" : "saving") : null}
				title={isChineseUi ? "模型配置" : "Model Config"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "选择默认模型、助手模型、可用模型池，并维护多个 Provider。"
					: "Choose default/helper models, selectable model choices, and multiple providers."}
			</p>
			<ConfigSourceMeta isChineseUi={isChineseUi} source={source} />
			<div className="fa-admin-form-grid is-two">
				<AdminField label={isChineseUi ? "默认模型" : "Default model"}>
					<select
						disabled={disabled}
						value={draft.defaultModel || EMPTY_SELECT_VALUE}
						onChange={(event) => {
							const value =
								event.target.value === EMPTY_SELECT_VALUE
									? ""
									: event.target.value;
							onChange({
								...draft,
								defaultModel: value,
								modelChoices: value
									? uniqueList([...draft.modelChoices, value])
									: draft.modelChoices,
							});
						}}
					>
						<option value={EMPTY_SELECT_VALUE}>
							{isChineseUi ? "未设置" : "Not set"}
						</option>
						{choiceOptions.map((modelId) => (
							<option key={modelId} value={modelId}>
								{modelId}
							</option>
						))}
					</select>
				</AdminField>
				<AdminField label={isChineseUi ? "助手模型" : "Helper model"}>
					<select
						disabled={disabled}
						value={draft.helperModel || EMPTY_SELECT_VALUE}
						onChange={(event) => {
							const value =
								event.target.value === EMPTY_SELECT_VALUE
									? ""
									: event.target.value;
							onChange({
								...draft,
								helperModel: value,
								modelChoices: value
									? uniqueList([...draft.modelChoices, value])
									: draft.modelChoices,
							});
						}}
					>
						<option value={EMPTY_SELECT_VALUE}>
							{isChineseUi ? "未设置" : "Not set"}
						</option>
						{choiceOptions.map((modelId) => (
							<option key={modelId} value={modelId}>
								{modelId}
							</option>
						))}
					</select>
				</AdminField>
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "可选模型池" : "Model choices"}</strong>
				</div>
				<div className="fa-admin-picker-list">
					{choiceOptions.map((modelId) => (
						<label className="fa-admin-config-choice" key={modelId}>
							<input
								checked={draft.modelChoices.includes(modelId)}
								disabled={disabled}
								type="checkbox"
								onChange={(event) =>
									onChoiceChange(modelId, event.target.checked)
								}
							/>
							<span>{modelId}</span>
						</label>
					))}
				</div>
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "模型 Provider" : "Model providers"}</strong>
					<button
						className="fa-observability-preset"
						disabled={disabled}
						type="button"
						onClick={onAddProvider}
					>
						{isChineseUi ? "添加 Provider" : "Add provider"}
					</button>
				</div>
				<div className="fa-admin-config-card-list">
					{draft.providers.map((provider, index) => (
						<div
							className="fa-admin-config-card"
							key={`${provider.id}-${index}`}
						>
							<div className="fa-admin-config-card-head">
								<strong>
									{provider.id ||
										(isChineseUi ? "新 Provider" : "New provider")}
								</strong>
								<div className="fa-admin-chip-row">
									<span>
										{provider.baseUrlConfigured
											? isChineseUi
												? "Base URL 已配置"
												: "Base URL configured"
											: isChineseUi
												? "Base URL 未配置"
												: "Base URL missing"}
									</span>
									<span>
										{provider.apiKeyConfigured
											? isChineseUi
												? "Key 已配置"
												: "Key configured"
											: isChineseUi
												? "Key 未配置"
												: "Key missing"}
									</span>
								</div>
							</div>
							<div className="fa-admin-form-grid is-three">
								<AdminField label="Provider ID">
									<input
										disabled={disabled}
										value={provider.id}
										onChange={(event) =>
											onProviderChange(index, { id: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label={isChineseUi ? "显示名称" : "Label"}>
									<input
										disabled={disabled}
										value={provider.label}
										onChange={(event) =>
											onProviderChange(index, { label: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Backend">
									<input
										disabled={disabled}
										value={provider.backendProvider}
										onChange={(event) =>
											onProviderChange(index, {
												backendProvider: event.target.value,
											})
										}
									/>
								</AdminField>
								<AdminField label="Aliases">
									<input
										disabled={disabled}
										placeholder="openai, azure"
										value={provider.aliases}
										onChange={(event) =>
											onProviderChange(index, { aliases: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Base URL env">
									<input
										disabled={disabled}
										value={provider.baseUrlEnv}
										onChange={(event) =>
											onProviderChange(index, {
												baseUrlEnv: event.target.value,
											})
										}
									/>
								</AdminField>
								<AdminField label="API key env">
									<input
										disabled={disabled}
										value={provider.apiKeyEnv}
										onChange={(event) =>
											onProviderChange(index, { apiKeyEnv: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Base URL default">
									<input
										disabled={disabled}
										value={provider.baseUrlDefault}
										onChange={(event) =>
											onProviderChange(index, {
												baseUrlDefault: event.target.value,
											})
										}
									/>
								</AdminField>
								<AdminField label="Logo slug">
									<input
										disabled={disabled}
										value={provider.logoSlug}
										onChange={(event) =>
											onProviderChange(index, { logoSlug: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Logo letter">
									<input
										disabled={disabled}
										value={provider.logoLetter}
										onChange={(event) =>
											onProviderChange(index, {
												logoLetter: event.target.value,
											})
										}
									/>
								</AdminField>
							</div>
							<button
								className="fa-observability-preset"
								disabled={disabled}
								type="button"
								onClick={() => onProviderRemove(index)}
							>
								{isChineseUi ? "移除 Provider" : "Remove provider"}
							</button>
						</div>
					))}
				</div>
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "模型条目" : "Model entries"}</strong>
				</div>
				<div className="fa-admin-config-card-list">
					{draft.models.map((model, index) => (
						<div className="fa-admin-config-card" key={`${model.id}-${index}`}>
							<div className="fa-admin-form-grid is-three">
								<AdminField label="Model ID">
									<input
										disabled={disabled}
										value={model.id}
										onChange={(event) =>
											onEntryChange(index, { id: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label={isChineseUi ? "显示名称" : "Label"}>
									<input
										disabled={disabled}
										value={model.label}
										onChange={(event) =>
											onEntryChange(index, { label: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Reasoning effort">
									<input
										disabled={disabled}
										value={model.reasoningEffort}
										onChange={(event) =>
											onEntryChange(index, {
												reasoningEffort: event.target.value,
											})
										}
									/>
								</AdminField>
							</div>
							<div className="fa-admin-picker-list">
								<ToggleControl
									checked={model.supportsThinking}
									disabled={disabled}
									label={isChineseUi ? "支持 Thinking" : "Supports thinking"}
									onChange={(checked) =>
										onEntryChange(index, { supportsThinking: checked })
									}
								/>
								<ToggleControl
									checked={model.defaultThinkingEnabled}
									disabled={disabled || !model.supportsThinking}
									label={
										isChineseUi ? "默认开启 Thinking" : "Thinking on by default"
									}
									onChange={(checked) =>
										onEntryChange(index, {
											defaultThinkingEnabled: checked,
										})
									}
								/>
								<ToggleControl
									checked={model.noTemperature}
									disabled={disabled}
									label={isChineseUi ? "不发送 temperature" : "No temperature"}
									onChange={(checked) =>
										onEntryChange(index, { noTemperature: checked })
									}
								/>
							</div>
						</div>
					))}
				</div>
			</div>
			<AdminField label={isChineseUi ? "变更原因" : "Change reason"}>
				<input
					disabled={disabled}
					value={draft.reason}
					onChange={(event) =>
						onChange({ ...draft, reason: event.target.value })
					}
				/>
			</AdminField>
			<ConfigActions
				disabled={disabled}
				isChineseUi={isChineseUi}
				onReset={onReset}
				pending={pending}
			/>
		</form>
	);
}
