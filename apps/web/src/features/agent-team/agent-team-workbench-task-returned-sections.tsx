import { useShellUi } from "@/app/shell/shell-ui-context";

import { EmptyList, FieldList } from "./agent-team-workbench-shared";
import {
	artifactPayloadItems,
	outputExecutionItems,
	shortText,
} from "./agent-team-workbench-task-view-helpers";
import type { AgentTeamArtifact, AgentTeamTaskOutput } from "./types";

export function TaskReturnedSections({
	artifacts,
	outputs,
}: {
	artifacts: AgentTeamArtifact[];
	outputs: AgentTeamTaskOutput[];
}) {
	const { isChineseUi } = useShellUi();
	if (!outputs.length && !artifacts.length) {
		return (
			<section>
				<h3>{isChineseUi ? "任务回传" : "Task return"}</h3>
				<EmptyList>
					{isChineseUi
						? "还没有收到这个任务的回传内容。"
						: "No returned content for this task yet."}
				</EmptyList>
			</section>
		);
	}

	return (
		<>
			<section>
				<h3>{isChineseUi ? "任务回传" : "Task return"}</h3>
				{outputs.length ? (
					<div className="fa-agent-team-output-list">
						{outputs.map((output) => (
							<div className="fa-agent-team-output-row" key={output.output_id}>
								<div className="fa-agent-team-output-row-heading">
									<span>
										{output.kind ?? (isChineseUi ? "回传" : "output")}
									</span>
									<strong>
										{shortText(
											output.summary,
											isChineseUi
												? "已回传，但没有摘要。"
												: "Returned without a summary.",
										)}
									</strong>
								</div>
								<div className="fa-agent-team-output-columns">
									<div>
										<span>{isChineseUi ? "依据" : "Evidence"}</span>
										<FieldList items={output.test_evidence} />
									</div>
									<div>
										<span>{isChineseUi ? "运行信息" : "Run info"}</span>
										<FieldList
											items={outputExecutionItems(output, isChineseUi)}
										/>
									</div>
								</div>
								{output.risk_notes?.length ? (
									<div>
										<span>{isChineseUi ? "风险" : "Risks"}</span>
										<FieldList items={output.risk_notes} />
									</div>
								) : null}
								{output.changed_files?.length ? (
									<div>
										<span>{isChineseUi ? "改动文件" : "Changed files"}</span>
										<FieldList items={output.changed_files} />
									</div>
								) : null}
							</div>
						))}
					</div>
				) : (
					<EmptyList>
						{isChineseUi ? "还没有 output 记录。" : "No output records yet."}
					</EmptyList>
				)}
			</section>
			<section>
				<h3>{isChineseUi ? "产物内容" : "Artifact content"}</h3>
				{artifacts.length ? (
					<div className="fa-agent-team-output-list">
						{artifacts.map((artifact) => (
							<div
								className="fa-agent-team-output-row"
								key={artifact.artifact_id}
							>
								<div className="fa-agent-team-output-row-heading">
									<span>{artifact.kind ?? "artifact"}</span>
									<strong>{artifact.title ?? artifact.artifact_id}</strong>
								</div>
								{artifact.summary ? <p>{artifact.summary}</p> : null}
								<FieldList
									items={artifactPayloadItems(artifact, isChineseUi)}
								/>
							</div>
						))}
					</div>
				) : (
					<EmptyList>
						{isChineseUi
							? "还没有 artifact 记录。"
							: "No artifact records yet."}
					</EmptyList>
				)}
			</section>
		</>
	);
}
