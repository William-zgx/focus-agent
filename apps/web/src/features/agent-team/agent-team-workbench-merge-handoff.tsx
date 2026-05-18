import { useShellUi } from "@/app/shell/shell-ui-context";

import { EmptyList, FieldList, HelpText } from "./agent-team-workbench-shared";
import {
	formatUnknown,
	isRawRunText,
	uniqueCompactStrings as uniqueStrings,
} from "./agent-team-workbench-task-output-utils";
import type {
	AgentTeamArtifact,
	AgentTeamMergeBundle,
	AgentTeamPlanningMetadata,
	AgentTeamTask,
	AgentTeamTaskOutput,
} from "./types";

export function PreMergeCheckPanel({
	bundle,
	canGenerate,
	error,
	evidenceItems,
	isGenerating,
	nextStepHint,
	onGenerate,
	riskItems,
}: {
	bundle: AgentTeamMergeBundle | null;
	canGenerate: boolean;
	changedFiles: string[];
	error: Error | null;
	evidenceItems: string[];
	isGenerating: boolean;
	nextStepHint?: { label: string; help?: string } | null;
	onGenerate: () => void;
	riskItems: string[];
}) {
	const { isChineseUi } = useShellUi();

	return (
		<section className="fa-agent-team-panel">
			<div className="fa-agent-team-panel-header">
				<div>
					<span>
						{isChineseUi
							? "结论、依据、需要注意"
							: "Conclusion, evidence, and risks"}
					</span>
					<strong>{isChineseUi ? "最终结果" : "Final result"}</strong>
					<HelpText>
						{isChineseUi
							? "用用户可读的方式收束任务结论、依据和需要注意的事项。"
							: "Summarizes the conclusion, evidence, and risks in user-facing language."}
					</HelpText>
				</div>
				{bundle ? (
					<FinalAnswerStatusPill bundle={bundle} isChineseUi={isChineseUi} />
				) : null}
			</div>
			{bundle ? (
				<div className="fa-agent-team-detail">
					<section>
						<h3>
							{isChineseUi ? "Agent Team 最终答案" : "Agent Team final answer"}
						</h3>
						<p className="fa-agent-team-final-answer-text">
							{finalAnswerText(bundle, isChineseUi)}
						</p>
					</section>
					{finalAnswerWarnings(bundle, isChineseUi).length ? (
						<section>
							<h3>{isChineseUi ? "提示" : "Warnings"}</h3>
							<FieldList items={finalAnswerWarnings(bundle, isChineseUi)} />
						</section>
					) : null}
					<section>
						<h3>{isChineseUi ? "依据" : "Evidence"}</h3>
						<FieldList
							items={resultEvidenceItems(bundle, evidenceItems, isChineseUi)}
						/>
					</section>
					<section>
						<h3>{isChineseUi ? "需要注意" : "Needs attention"}</h3>
						<FieldList
							items={resultRiskItems(bundle, riskItems, isChineseUi)}
						/>
					</section>
				</div>
			) : (
				<div className="fa-agent-team-detail fa-agent-team-result-placeholder">
					<section>
						<h3>{isChineseUi ? "还没有最终结果" : "No final result yet"}</h3>
						<p>
							{nextStepHint?.label ||
								(isChineseUi
									? "任务完成后，可以把产出、依据和风险整理成最终答案。"
									: "After tasks complete, Agent Team can package outputs, evidence, and risks into the final answer.")}
						</p>
						{nextStepHint?.help ? (
							<HelpText>{nextStepHint.help}</HelpText>
						) : null}
					</section>
				</div>
			)}
			{error ? (
				<div className="fa-inline-notice is-danger">{error.message}</div>
			) : null}
			<button
				className="fa-observability-preset is-primary"
				disabled={!canGenerate || isGenerating}
				onClick={onGenerate}
				type="button"
			>
				{finalResultActionLabel({
					isChineseUi,
					isGenerating,
					canGenerate,
					hasBundle: Boolean(bundle),
				})}
			</button>
		</section>
	);
}

export function AdvancedDetailsPanel({
	artifacts = [],
	bundle,
	changedFiles = [],
	dag,
	evidenceItems = [],
	openQuestions,
	outputs = [],
	planningMetadata,
	riskItems = [],
	tasks = [],
}: {
	artifacts?: AgentTeamArtifact[];
	bundle?: AgentTeamMergeBundle | null;
	changedFiles?: string[];
	dag?: Record<string, unknown> | null;
	evidenceItems?: string[];
	openQuestions?: string[];
	outputs?: AgentTeamTaskOutput[];
	planningMetadata?: AgentTeamPlanningMetadata | Record<string, unknown> | null;
	riskItems?: string[];
	tasks?: AgentTeamTask[];
}) {
	const { isChineseUi } = useShellUi();
	const planningItems = planningMetadataItems(planningMetadata);
	const branchItems = branchCluesFromTasks(tasks);
	const rawEvidenceItems = [
		...evidenceItems,
		...(bundle?.test_evidence ?? []),
		...(bundle?.execution_evidence ?? []).map(formatUnknown),
	];
	const advancedOpenQuestions = openQuestions ?? bundle?.open_questions;
	const advancedChangedFiles = bundle?.changed_files?.length
		? bundle.changed_files
		: changedFiles;
	const artifactItems = artifacts.map(
		(artifact) =>
			artifact.summary ??
			artifact.title ??
			artifact.uri ??
			artifact.artifact_id,
	);
	const sourceOutputItems = bundle?.source_output_ids?.length
		? bundle.source_output_ids
		: outputs.map((output) => output.output_id);
	const rawOutputItems = outputs.map((output) => formatUnknown(output));

	return (
		<section className="fa-agent-team-panel">
			<div className="fa-agent-team-panel-header">
				<div>
					<span>
						{isChineseUi
							? "Planning metadata、DAG、raw evidence"
							: "Planning metadata, DAG, raw evidence"}
					</span>
					<strong>{isChineseUi ? "高级详情" : "Advanced details"}</strong>
					<HelpText>
						{isChineseUi
							? "面向 Lead 审查的规划、分支、原始依据、改动文件和未决问题。"
							: "Planning, branch, raw evidence, changed files, and open question details for Lead review."}
					</HelpText>
				</div>
			</div>
			<div className="fa-agent-team-detail">
				<section>
					<h3>Planning metadata</h3>
					<FieldList items={planningItems} />
				</section>
				<section>
					<h3>{isChineseUi ? "DAG / 分支线索" : "DAG / branch clues"}</h3>
					<FieldList items={[...dagItems(dag), ...branchItems]} />
				</section>
				<section>
					<h3>{isChineseUi ? "原始依据" : "Raw evidence"}</h3>
					<FieldList items={uniqueStrings(rawEvidenceItems)} />
				</section>
				<section>
					<h3>{isChineseUi ? "Source output IDs" : "Source output IDs"}</h3>
					<FieldList items={sourceOutputItems} />
				</section>
				<section>
					<h3>{isChineseUi ? "Raw outputs" : "Raw outputs"}</h3>
					<FieldList items={rawOutputItems} />
				</section>
				<section>
					<h3>{isChineseUi ? "改动文件" : "Changed files"}</h3>
					<FieldList items={advancedChangedFiles} />
				</section>
				<section>
					<h3>{isChineseUi ? "未决问题" : "Open questions"}</h3>
					<FieldList items={advancedOpenQuestions} />
				</section>
				<section>
					<h3>{isChineseUi ? "风险原文" : "Raw risks"}</h3>
					<FieldList
						items={bundle?.risk_items?.length ? bundle.risk_items : riskItems}
					/>
				</section>
				<section>
					<h3>{isChineseUi ? "Artifacts" : "Artifacts"}</h3>
					<FieldList items={artifactItems} />
				</section>
			</div>
		</section>
	);
}

export function MergeBundleCard({
	bundle,
	pendingBundle,
	onGenerate,
	isGenerating,
	error,
	canGenerate,
	hideAction = false,
}: {
	bundle: AgentTeamMergeBundle | null;
	pendingBundle: AgentTeamMergeBundle | null;
	onGenerate: () => void;
	isGenerating: boolean;
	error: Error | null;
	canGenerate: boolean;
	hideAction?: boolean;
}) {
	const { isChineseUi } = useShellUi();
	const activeBundle = pendingBundle ?? bundle;

	return (
		<section className="fa-agent-team-panel fa-agent-team-merge-card">
			<div className="fa-agent-team-panel-header">
				<div>
					<span>{isChineseUi ? "交付结果" : "Deliverable result"}</span>
					<strong>
						{isChineseUi
							? "结果、依据、风险一次看清"
							: "Result, evidence, and risks"}
					</strong>
					<HelpText>
						{isChineseUi
							? "把任务 DAG 的产出、依据、风险和未决问题收束成可交付的最终回答。"
							: "Synthesize the task DAG outputs, evidence, risks, and open questions into a deliverable final answer."}
					</HelpText>
				</div>
				{activeBundle ? (
					<FinalAnswerStatusPill
						bundle={activeBundle}
						isChineseUi={isChineseUi}
					/>
				) : null}
			</div>
			{activeBundle ? (
				<div className="fa-agent-team-merge-grid">
					<p className="fa-agent-team-final-answer-text">
						{finalAnswerText(activeBundle, isChineseUi)}
					</p>
					<div>
						<h3>{isChineseUi ? "关键发现" : "Key findings"}</h3>
						<FieldList items={activeBundle.key_findings} />
					</div>
					<div>
						<h3>{isChineseUi ? "改动文件" : "Changed files"}</h3>
						<FieldList items={activeBundle.changed_files} />
					</div>
					<div>
						<h3>{isChineseUi ? "验证依据" : "Test evidence"}</h3>
						<FieldList items={activeBundle.test_evidence} />
					</div>
					<div>
						<h3>{isChineseUi ? "未决问题" : "Open questions"}</h3>
						<FieldList items={activeBundle.open_questions} />
					</div>
					<div>
						<h3>{isChineseUi ? "风险" : "Risks"}</h3>
						<FieldList items={activeBundle.risk_items} />
					</div>
				</div>
			) : (
				<EmptyList>
					{isChineseUi
						? "还没有生成最终结果。"
						: "No final result generated yet."}
				</EmptyList>
			)}
			{error ? (
				<div className="fa-inline-notice is-danger">{error.message}</div>
			) : null}
			{!hideAction ? (
				<button
					className="fa-observability-preset is-primary"
					disabled={!canGenerate || isGenerating}
					onClick={onGenerate}
					type="button"
				>
					{finalResultActionLabel({
						isChineseUi,
						isGenerating,
						canGenerate,
						hasBundle: Boolean(activeBundle),
					})}
				</button>
			) : null}
		</section>
	);
}

export function riskItemsFromTasks(tasks: AgentTeamTask[]) {
	return tasks.flatMap((task) => task.risk_notes ?? []);
}

function FinalAnswerStatusPill({
	bundle,
	isChineseUi,
}: {
	bundle: AgentTeamMergeBundle;
	isChineseUi: boolean;
}) {
	const status = normalizedFinalAnswerStatus(bundle);
	if (status) {
		const labels: Record<string, string> = isChineseUi
			? {
					ready: "可交付答案",
					placeholder: "模拟执行",
					blocked: "无法生成",
					error: "生成失败",
					legacy: "旧格式结果",
				}
			: {
					ready: "Deliverable answer",
					placeholder: "Simulated run",
					blocked: "Blocked",
					error: "Failed",
					legacy: "Legacy result",
				};
		const tone =
			status === "ready"
				? "success"
				: status === "placeholder" || status === "blocked"
					? "warning"
					: status === "error"
						? "danger"
						: "neutral";
		return (
			<span className={`fa-agent-team-pill is-${tone}`}>
				{labels[status] ?? status}
			</span>
		);
	}
	return (
		<RecommendedActionPill
			action={bundle.recommended_next_action ?? ""}
			isChineseUi={isChineseUi}
		/>
	);
}

function RecommendedActionPill({
	action,
	isChineseUi,
}: {
	action: string;
	isChineseUi: boolean;
}) {
	const labels: Record<string, string> = isChineseUi
		? {
				merge: "可交付",
				request_changes: "需要修改",
			}
		: {
				merge: "Deliverable",
				request_changes: "Needs changes",
			};
	const tone =
		action === "merge"
			? "success"
			: action === "request_changes"
				? "warning"
				: "neutral";

	return (
		<span className={`fa-agent-team-pill is-${tone}`}>
			{labels[action] ?? action.replaceAll("_", " ")}
		</span>
	);
}

function finalResultActionLabel({
	isChineseUi,
	isGenerating,
	canGenerate,
	hasBundle,
}: {
	isChineseUi: boolean;
	isGenerating: boolean;
	canGenerate: boolean;
	hasBundle: boolean;
}) {
	if (isGenerating)
		return isChineseUi ? "正在生成最终结果..." : "Generating final result...";
	if (!canGenerate)
		return isChineseUi ? "等待任务产出" : "Waiting for task outputs";
	if (hasBundle)
		return isChineseUi ? "重新生成最终结果" : "Regenerate final result";
	return isChineseUi ? "生成最终结果" : "Generate final result";
}

function resultEvidenceItems(
	bundle: AgentTeamMergeBundle,
	evidenceItems: string[],
	isChineseUi: boolean,
) {
	if (isPlaceholderBundle(bundle)) {
		return [
			isChineseUi
				? "模拟任务已回传；真实执行后会显示可验证依据。"
				: "The simulated tasks returned; verifiable evidence will appear after a real run.",
		];
	}
	if (bundle.final_answer && bundle.source_output_ids?.length) {
		return limitUserFacingItems(
			uniqueStrings([
				...(bundle.key_findings ?? []),
				...(bundle.test_evidence ?? []),
				isChineseUi
					? "已汇总任务回传内容作为最终答案依据。"
					: "Task returns were synthesized as final-answer evidence.",
			]).filter((item) => !isRawRunText(item, "bundle")),
			isChineseUi,
		);
	}
	return limitUserFacingItems(
		uniqueStrings(
			uniqueStrings([
				...(bundle.key_findings ?? []),
				...(bundle.test_evidence ?? []),
				...evidenceItems,
			]).map((item) =>
				isRawRunText(item, "bundle")
					? isChineseUi
						? "任务产出已回传。"
						: "Task output returned."
					: item,
			),
		),
		isChineseUi,
	);
}

function finalResultSummary(
	bundle: AgentTeamMergeBundle | null,
	isChineseUi: boolean,
) {
	if (!bundle?.summary) return isChineseUi ? "暂无摘要。" : "No summary yet.";
	if (isBundleSimulated(bundle)) {
		return isChineseUi
			? "当前是模拟执行，只验证了 Agent Team 的拆解、运行和回传流程，没有生成可交付的真实答案。"
			: "This is a simulated run. It only validates the Agent Team planning, run, and return flow; it did not generate a deliverable final answer.";
	}
	if (!isRawRunText(bundle.summary, "bundle")) return bundle.summary;

	const completedMatch = bundle.summary.match(/\b(\d+)\s*\/\s*(\d+)\b/);
	if (completedMatch) {
		const [, done, total] = completedMatch;
		return isChineseUi
			? `${done}/${total} 个任务已完成，最终结果已生成。`
			: `${done}/${total} tasks completed; final result is ready.`;
	}

	return isChineseUi
		? "任务已完成，最终结果已生成。"
		: "Tasks completed; final result is ready.";
}

function finalAnswerText(
	bundle: AgentTeamMergeBundle | null,
	isChineseUi: boolean,
) {
	if (!bundle) return isChineseUi ? "暂无最终答案。" : "No final answer yet.";
	const finalAnswer = bundle.final_answer?.trim();
	if (finalAnswer && !isRawRunText(finalAnswer, "bundle")) return finalAnswer;
	if (bundle.final_answer_status === "placeholder") {
		return isChineseUi
			? "当前是模拟执行，只验证了 Agent Team 的拆解、运行和回传流程，没有生成可交付的真实答案。"
			: "This is a simulated run. It only validates the Agent Team planning, run, and return flow; it did not generate a deliverable final answer.";
	}
	return finalResultSummary(bundle, isChineseUi);
}

function finalAnswerWarnings(
	bundle: AgentTeamMergeBundle,
	isChineseUi: boolean,
) {
	if (isPlaceholderBundle(bundle)) {
		return [
			isChineseUi
				? "模拟执行提示：模拟执行只验证流程，不会作为用户态可交付最终答案展示。"
				: "Simulated execution validates the workflow only; it is not a deliverable final answer.",
			isChineseUi
				? "请切换到真实模型执行后，再生成 Agent Team 最终答案。"
				: "Switch to real model execution, then generate the Agent Team final answer again.",
		];
	}
	const warnings = uniqueStrings(bundle.final_answer_warnings ?? []).filter(
		(item) => !isRawRunText(item, "bundle"),
	);
	return warnings;
}

function resultRiskItems(
	bundle: AgentTeamMergeBundle,
	riskItems: string[],
	isChineseUi: boolean,
) {
	if (isPlaceholderBundle(bundle)) {
		return [
			isChineseUi
				? "当前结果不可直接交付；需要真实执行后再检查依据、风险和完整性。"
				: "This result is not deliverable yet; run it for real before checking evidence, risks, and completeness.",
		];
	}
	const items = limitUserFacingItems(
		uniqueStrings([
			...(bundle.final_answer_warnings ?? []),
			...(bundle.risk_items ?? []),
			...(bundle.open_questions ?? []),
			...riskItems,
		]).filter((item) => !isRawRunText(item, "bundle")),
		isChineseUi,
	);
	return items.length
		? items
		: [isChineseUi ? "暂无需要处理的事项。" : "No items need attention."];
}

function branchCluesFromTasks(tasks: AgentTeamTask[]) {
	return uniqueStrings(
		tasks.flatMap((task) => {
			const clues = [];
			if (task.branch_id)
				clues.push(`${task.title ?? task.task_id}: branch ${task.branch_id}`);
			if (task.child_thread_id)
				clues.push(
					`${task.title ?? task.task_id}: thread ${task.child_thread_id}`,
				);
			if (task.dependencies?.length)
				clues.push(
					`${task.title ?? task.task_id}: depends on ${task.dependencies.join(", ")}`,
				);
			return clues;
		}),
	);
}

function dagItems(dag: Record<string, unknown> | null | undefined) {
	if (!dag) return [];
	return Object.entries(dag).map(
		([key, value]) => `${key}: ${formatUnknown(value)}`,
	);
}

function planningMetadataItems(
	metadata:
		| AgentTeamPlanningMetadata
		| Record<string, unknown>
		| null
		| undefined,
) {
	if (!metadata) return [];
	return Object.entries(metadata)
		.filter(
			([, value]) => value !== null && value !== undefined && value !== "",
		)
		.map(([key, value]) => `${key}: ${formatUnknown(value)}`);
}

function normalizedFinalAnswerStatus(bundle: AgentTeamMergeBundle) {
	const status = bundle.final_answer_status?.trim();
	if (status) return status;
	if (isBundleSimulated(bundle)) return "placeholder";
	if (bundle.summary && !bundle.final_answer) return "legacy";
	return null;
}

function isPlaceholderBundle(bundle: AgentTeamMergeBundle) {
	return normalizedFinalAnswerStatus(bundle) === "placeholder";
}

function isBundleSimulated(bundle: AgentTeamMergeBundle) {
	return [
		bundle.summary,
		bundle.final_answer,
		...(bundle.key_findings ?? []),
		...(bundle.test_evidence ?? []),
		...(bundle.risk_items ?? []),
		...(bundle.open_questions ?? []),
	].some((item) => Boolean(item && isRawRunText(item, "bundle")));
}

function limitUserFacingItems(
	items: string[],
	isChineseUi: boolean,
	limit = 6,
) {
	if (items.length <= limit) return items;
	return [
		...items.slice(0, limit),
		isChineseUi
			? `另有 ${items.length - limit} 条可在高级详情查看。`
			: `${items.length - limit} more in advanced details.`,
	];
}
