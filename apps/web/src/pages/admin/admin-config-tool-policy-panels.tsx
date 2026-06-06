import type { FocusAgentAdminConfigValue } from "@focus-agent/web-sdk";
import type { FormEvent } from "react";

import { AdminField, AdminPanelHeader } from "./admin-page-sections";
import {
	ConfigActions,
	ConfigSourceMeta,
	PolicyControl,
	ReadOnlyConfigValue,
	ToggleControl,
} from "./admin-config-controls";
import {
	localizedConfigValueCopy,
	localizedToolCopy,
	policyDraftValue,
} from "./admin-config-draft-utils";
import type {
	PolicyDraft,
	PolicyDraftValue,
	ToolDraft,
	ToolEntryDraft,
	ToolProviderDraft,
} from "./admin-config-draft-utils";

export function ToolConfigPanel({
	disabled,
	draft,
	isChineseUi,
	onAddProvider,
	onChange,
	onProviderChange,
	onProviderRemove,
	onReset,
	onSubmit,
	onToolChange,
	pending,
	source,
}: {
	disabled: boolean;
	draft: ToolDraft;
	isChineseUi: boolean;
	onAddProvider: () => void;
	onChange: (draft: ToolDraft) => void;
	onProviderChange: (index: number, patch: Partial<ToolProviderDraft>) => void;
	onProviderRemove: (index: number) => void;
	onReset: () => void;
	onSubmit: (event: FormEvent<HTMLFormElement>) => void;
	onToolChange: (index: number, patch: Partial<ToolEntryDraft>) => void;
	pending: boolean;
	source?: { exists: boolean; path: string; writable: boolean };
}) {
	return (
		<form className="fa-admin-panel fa-admin-config-panel" onSubmit={onSubmit}>
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Tools" : "Tools"}
				status={pending ? (isChineseUi ? "保存中" : "saving") : null}
				title={isChineseUi ? "工具配置" : "Tool Config"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "开启或关闭工具，调整工具 Provider 的启用状态、顺序和覆盖项。"
					: "Enable tools and tune tool provider state, order, and overrides."}
			</p>
			<ConfigSourceMeta isChineseUi={isChineseUi} source={source} />
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "工具开关" : "Tool switches"}</strong>
				</div>
				<div className="fa-admin-config-list">
					{draft.tools.map((tool, index) => {
						const copy = localizedToolCopy(tool, isChineseUi);
						return (
							<div className="fa-admin-config-value-row" key={tool.name}>
								<ToggleControl
									checked={tool.enabled}
									disabled={disabled}
									label={copy.label}
									onChange={(checked) =>
										onToolChange(index, { enabled: checked })
									}
								/>
								{copy.description ? <p>{copy.description}</p> : null}
								<div className="fa-admin-form-grid is-two">
									<AdminField label={isChineseUi ? "显示名称" : "Label"}>
										<input
											disabled={disabled}
											value={tool.label}
											onChange={(event) =>
												onToolChange(index, { label: event.target.value })
											}
										/>
									</AdminField>
									<AdminField label={isChineseUi ? "说明" : "Description"}>
										<input
											disabled={disabled}
											value={tool.description}
											onChange={(event) =>
												onToolChange(index, {
													description: event.target.value,
												})
											}
										/>
									</AdminField>
								</div>
							</div>
						);
					})}
				</div>
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "工具 Provider" : "Tool providers"}</strong>
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
								<ToggleControl
									checked={provider.enabled}
									disabled={disabled}
									label={
										provider.id ||
										(isChineseUi ? "新 Provider" : "New provider")
									}
									onChange={(checked) =>
										onProviderChange(index, { enabled: checked })
									}
								/>
								<button
									className="fa-observability-preset"
									disabled={disabled}
									type="button"
									onClick={() => onProviderRemove(index)}
								>
									{isChineseUi ? "移除" : "Remove"}
								</button>
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
								<AdminField label={isChineseUi ? "顺序" : "Order"}>
									<input
										disabled={disabled}
										inputMode="numeric"
										value={provider.order}
										onChange={(event) =>
											onProviderChange(index, { order: event.target.value })
										}
									/>
								</AdminField>
								<AdminField label="Overrides">
									<input
										disabled={disabled}
										value={provider.overrides}
										onChange={(event) =>
											onProviderChange(index, { overrides: event.target.value })
										}
									/>
								</AdminField>
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

export function PolicyConfigPanel({
	disabled,
	draft,
	eyebrow,
	help,
	isChineseUi,
	items,
	onChange,
	onReset,
	onSubmit,
	onValueChange,
	pending,
	source,
	title,
}: {
	disabled: boolean;
	draft: PolicyDraft;
	eyebrow?: string;
	help?: string;
	isChineseUi: boolean;
	items: FocusAgentAdminConfigValue[];
	onChange: (draft: PolicyDraft) => void;
	onReset: () => void;
	onSubmit: (event: FormEvent<HTMLFormElement>) => void;
	onValueChange: (key: string, value: PolicyDraftValue) => void;
	pending: boolean;
	source?: { exists: boolean; path: string; writable: boolean };
	title?: string;
}) {
	return (
		<form className="fa-admin-panel fa-admin-config-panel" onSubmit={onSubmit}>
			<AdminPanelHeader
				eyebrow={eyebrow ?? (isChineseUi ? "Policies" : "Policies")}
				status={pending ? (isChineseUi ? "保存中" : "saving") : null}
				title={title ?? (isChineseUi ? "策略配置" : "Policy Config")}
			/>
			<p className="fa-admin-config-help">
				{help ??
					(isChineseUi
						? "布尔项用开关，枚举项用下拉，数值项直接填写。"
						: "Use switches for booleans, selects for enums, and inputs for numbers.")}
			</p>
			<ConfigSourceMeta isChineseUi={isChineseUi} source={source} />
			<div className="fa-admin-config-list">
				{items.map((item) => {
					const copy = localizedConfigValueCopy(item, isChineseUi);
					return (
						<div className="fa-admin-config-value-row" key={item.key}>
							<PolicyControl
								disabled={disabled}
								isChineseUi={isChineseUi}
								item={item}
								label={copy.label}
								onChange={(value) => onValueChange(item.key, value)}
								value={draft.values[item.key] ?? policyDraftValue(item)}
							/>
							{copy.description ? <p>{copy.description}</p> : null}
						</div>
					);
				})}
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

export function SystemConfigPanel({
	isChineseUi,
	items,
	source,
}: {
	isChineseUi: boolean;
	items: FocusAgentAdminConfigValue[];
	source?: { exists: boolean; path: string; writable: boolean };
}) {
	return (
		<section className="fa-admin-panel fa-admin-config-panel">
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Readonly" : "Readonly"}
				status={null}
				title={isChineseUi ? "基础配置" : "System Config"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "运行环境与敏感项只读展示；敏感值只显示是否已配置。"
					: "Runtime and secret settings are read-only; secret values show configured state only."}
			</p>
			<ConfigSourceMeta isChineseUi={isChineseUi} source={source} />
			<div className="fa-admin-config-list">
				{items.map((item) => (
					<ReadOnlyConfigValue
						isChineseUi={isChineseUi}
						item={item}
						key={item.key}
					/>
				))}
			</div>
		</section>
	);
}
