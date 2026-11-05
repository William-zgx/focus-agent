import { useShellUi } from "@/app/shell/shell-ui-context";

import { FieldList, HelpText } from "./agent-team-workbench-shared";
import {
	formatUnknown,
	uniqueCompactStrings as uniqueStrings,
} from "./agent-team-workbench-task-output-utils";
import type {
	AgentTeamArtifact,
	AgentTeamMergeBundle,
	AgentTeamPlanningMetadata,
	AgentTeamTask,
	AgentTeamTaskOutput,
} from "./types";

export function AdvancedDetailsPanel({
	artifacts = [],
	bundle,
	changedFiles = [],
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
		(artifact) => artifact.summary ?? artifact.title ?? artifact.artifact_id,
	);
	const sourceOutputItems = bundle?.source_output_ids?.length
		? bundle.source_output_ids
		: uniqueStrings(outputs.map((output) => output.output_id));
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
					<FieldList items={branchItems} />
				</section>
				<section>
					<h3>{isChineseUi ? "原始依据" : "Raw evidence"}</h3>
					<FieldList items={uniqueStrings(rawEvidenceItems)} />
				</section>
				<section>
					<h3>Source output IDs</h3>
					<FieldList items={sourceOutputItems} />
				</section>
				<section>
					<h3>Raw outputs</h3>
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
					<h3>Artifacts</h3>
					<FieldList items={artifactItems} />
				</section>
			</div>
		</section>
	);
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
