import type { FocusAgentAdminConfigValue } from "@focus-agent/web-sdk";

import { AdminField } from "./admin-page-sections";
import {
	localizedConfigOptionLabel,
	localizedConfigValueCopy,
	unknownToText,
} from "./admin-config-draft-utils";
import type { PolicyDraftValue } from "./admin-config-draft-utils";

export function PolicyControl({
	disabled,
	isChineseUi,
	item,
	label,
	onChange,
	value,
}: {
	disabled: boolean;
	isChineseUi: boolean;
	item: FocusAgentAdminConfigValue;
	label: string;
	onChange: (value: PolicyDraftValue) => void;
	value: PolicyDraftValue;
}) {
	if (item.value_type === "boolean") {
		return (
			<ToggleControl
				checked={Boolean(value)}
				disabled={disabled}
				label={label}
				onChange={onChange}
			/>
		);
	}

	if (item.options.length > 0) {
		return (
			<AdminField label={label}>
				<select
					disabled={disabled}
					value={String(value ?? "")}
					onChange={(event) => onChange(event.target.value)}
				>
					{item.options.map((option) => (
						<option key={option} value={option}>
							{localizedConfigOptionLabel(option, isChineseUi)}
						</option>
					))}
				</select>
			</AdminField>
		);
	}

	if (item.value_type === "integer" || item.value_type === "float") {
		return (
			<AdminField label={label}>
				<input
					disabled={disabled}
					inputMode="decimal"
					step={item.value_type === "integer" ? "1" : "any"}
					type="number"
					value={String(value ?? "")}
					onChange={(event) => onChange(event.target.value)}
				/>
			</AdminField>
		);
	}

	return (
		<AdminField label={label}>
			<input
				disabled={disabled}
				value={String(value ?? "")}
				onChange={(event) => onChange(event.target.value)}
			/>
		</AdminField>
	);
}

export function ToggleControl({
	checked,
	disabled,
	label,
	onChange,
}: {
	checked: boolean;
	disabled: boolean;
	label: string;
	onChange: (checked: boolean) => void;
}) {
	return (
		<label className="fa-admin-config-switch">
			<input
				checked={checked}
				disabled={disabled}
				type="checkbox"
				onChange={(event) => onChange(event.target.checked)}
			/>
			<span>{label}</span>
		</label>
	);
}

export function ConfigSourceMeta({
	isChineseUi,
	source,
}: {
	isChineseUi: boolean;
	source?: { exists: boolean; path: string; writable: boolean };
}) {
	if (!source) return null;
	return (
		<div className="fa-admin-config-source">
			<span>{source.path}</span>
			<strong>
				{source.exists ? (isChineseUi ? "存在" : "exists") : "new"}
			</strong>
			<strong>
				{source.writable
					? isChineseUi
						? "可写"
						: "writable"
					: isChineseUi
						? "只读"
						: "read-only"}
			</strong>
		</div>
	);
}

export function ConfigActions({
	disabled,
	isChineseUi,
	onReset,
	pending,
}: {
	disabled: boolean;
	isChineseUi: boolean;
	onReset: () => void;
	pending: boolean;
}) {
	return (
		<div className="fa-admin-action-row">
			<button
				className="fa-observability-preset is-primary"
				disabled={disabled}
				type="submit"
			>
				{pending
					? isChineseUi
						? "保存中"
						: "Saving"
					: isChineseUi
						? "保存"
						: "Save"}
			</button>
			<button
				className="fa-observability-preset"
				disabled={disabled}
				type="button"
				onClick={onReset}
			>
				{isChineseUi ? "重置" : "Reset"}
			</button>
		</div>
	);
}

export function ReadOnlyConfigValue({
	isChineseUi,
	item,
}: {
	isChineseUi: boolean;
	item: FocusAgentAdminConfigValue;
}) {
	const copy = localizedConfigValueCopy(item, isChineseUi);
	const value = item.sensitive
		? item.configured
			? isChineseUi
				? "已配置"
				: "Configured"
			: isChineseUi
				? "未配置"
				: "Not configured"
		: unknownToText(item.value) || "-";
	return (
		<div className="fa-admin-config-value-row">
			<div className="fa-admin-config-readonly-head">
				<strong>{copy.label}</strong>
				<span>{item.env_key || item.key}</span>
			</div>
			<output>{value}</output>
			{copy.description ? <p>{copy.description}</p> : null}
		</div>
	);
}
