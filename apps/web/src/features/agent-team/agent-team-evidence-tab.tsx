import { useShellUi } from "@/app/shell/shell-ui-context";

import { AgentTeamAdoptionWorkbench } from "./agent-team-workbench-adoption";
import { AdvancedDetailsPanel } from "./agent-team-workbench-merge-handoff";
import { useAgentTeamWorkbenchViewModel } from "./agent-team-workbench-view-model";
import { AgentTeamSessionState } from "./agent-team-session-state";
import {
	isRecord,
	normalizeSessionView,
	uniqueNonEmptyStrings,
} from "./agent-team-workbench-utils";
import type { AgentTeamEvidence } from "./types";
import {
	useAgentTeamEvidence,
	useAgentTeamReadiness,
	useAgentTeamSession,
} from "./use-agent-team";

export function AgentTeamEvidenceTab({
	sessionId,
}: {
	sessionId: string | null;
}) {
	const { isChineseUi } = useShellUi();
	const sessionQuery = useAgentTeamSession(sessionId);
	const view = normalizeSessionView(sessionQuery.data);
	const readinessQuery = useAgentTeamReadiness({
		enabled: Boolean(sessionId),
	});
	const evidenceQuery = useAgentTeamEvidence(sessionId, {
		enabled: Boolean(sessionId),
		poll: shouldPollEvidence(view),
	});
	const workbenchVm = useAgentTeamWorkbenchViewModel({
		isChineseUi,
		mergeProposalData: undefined,
		sessionData: sessionQuery.data,
	});
	const state = (
		<AgentTeamSessionState
			data={sessionQuery.data}
			error={sessionQuery.error}
			isChineseUi={isChineseUi}
			isLoading={sessionQuery.isLoading}
		/>
	);

	if (!sessionId || sessionQuery.isLoading || sessionQuery.error || !view) {
		return state;
	}
	const runEvidence = optionalRunEvidence(view.run);

	return (
		<div className="fa-agent-team-layout fa-agent-team-tab-content">
			<AgentTeamAdoptionWorkbench isChineseUi={isChineseUi} session={view} />
			<V2EvidencePanel
				error={evidenceQuery.error}
				evidence={evidenceQuery.data?.items ?? []}
				isChineseUi={isChineseUi}
				isLoading={evidenceQuery.isLoading}
				readiness={readinessQuery}
			/>
			<AdvancedDetailsPanel
				artifacts={workbenchVm.advancedMeta.artifacts}
				bundle={workbenchVm.activeBundle}
				changedFiles={workbenchVm.advancedMeta.changedFiles}
				dag={workbenchVm.advancedMeta.dag}
				evidenceItems={[
					...workbenchVm.advancedMeta.rawEvidence.evidenceItems,
					...runEvidence,
				]}
				openQuestions={workbenchVm.advancedMeta.openQuestions}
				outputs={view.outputs ?? []}
				planningMetadata={{
					source: workbenchVm.planningMetadata.source,
					planner_model_id: workbenchVm.planningMetadata.model,
					generated_at: workbenchVm.planningMetadata.generatedAt,
					task_count: workbenchVm.planningMetadata.taskCount,
					rationale: workbenchVm.advancedMeta.planning.rationale,
					plan_hash: workbenchVm.advancedMeta.planning.planHash,
					error: workbenchVm.advancedMeta.planning.error,
				}}
				riskItems={workbenchVm.riskItems}
				tasks={workbenchVm.tasks}
			/>
		</div>
	);
}

function V2EvidencePanel({
	error,
	evidence,
	isChineseUi,
	isLoading,
	readiness,
}: {
	error: Error | null;
	evidence: AgentTeamEvidence[];
	isChineseUi: boolean;
	isLoading: boolean;
	readiness: ReturnType<typeof useAgentTeamReadiness>;
}) {
	const v2Unavailable =
		!readiness.isLoading &&
		(!readiness.data ||
			!readiness.data.enabled ||
			!readiness.data.service_available ||
			!readiness.data.capabilities.evidence_queries);

	return (
		<section className="fa-agent-team-panel">
			<div className="fa-agent-team-panel-header">
				<div>
					<span>{isChineseUi ? "SDK v2" : "SDK v2"}</span>
					<strong>{isChineseUi ? "执行证据" : "Execution evidence"}</strong>
				</div>
			</div>
			{isLoading ? (
				<p className="fa-agent-team-empty">
					{isChineseUi ? "正在读取执行证据…" : "Loading execution evidence…"}
				</p>
			) : null}
			{v2Unavailable ? (
				<p className="fa-agent-team-empty">
					{isChineseUi
						? "当前 SDK 或服务尚未提供 v2 证据查询；旧版依据仍可在下方查看。"
						: "The current SDK or service does not provide v2 evidence queries; legacy evidence remains available below."}
				</p>
			) : null}
			{error ? (
				<div className="fa-inline-notice is-warning">
					{isChineseUi
						? "v2 证据暂时不可用，不影响 Mission 或聊天。"
						: "V2 evidence is temporarily unavailable and does not affect Mission or chat."}
				</div>
			) : null}
			{evidence.length ? (
				<div className="fa-agent-team-detail">
					{evidence.map((item) => (
						<section key={item.evidence_id}>
							<h3>{item.summary || item.evidence_id}</h3>
							<p>
								{[
									item.source_type,
									item.evidence_level,
									item.evidence_verdict,
									item.deliverable
										? isChineseUi
											? "可交付"
											: "Deliverable"
										: isChineseUi
											? "待确认"
											: "Pending",
								]
									.filter(Boolean)
									.join(" · ")}
							</p>
							{item.evidence_summary ? <p>{item.evidence_summary}</p> : null}
						</section>
					))}
				</div>
			) : !isLoading && !v2Unavailable && !error ? (
				<p className="fa-agent-team-empty">
					{isChineseUi ? "暂未返回执行证据。" : "No execution evidence yet."}
				</p>
			) : null}
		</section>
	);
}

function shouldPollEvidence(view: ReturnType<typeof normalizeSessionView>) {
	if (!view) return false;
	return (
		view.session.status === "planning" ||
		view.session.status === "running" ||
		view.tasks.some((task) =>
			["pending", "queued", "ready", "running"].includes(task.status),
		)
	);
}

function optionalRunEvidence(run: unknown): string[] {
	if (!isRecord(run)) return [];
	return uniqueNonEmptyStrings(
		[
			run.readiness,
			run.readiness_evidence,
			run.run_evidence,
			run.evidence,
			run.message,
			run.error,
		].flatMap(optionalEvidenceValues),
	);
}

function optionalEvidenceValues(value: unknown): string[] {
	if (typeof value === "string") return [value];
	if (Array.isArray(value)) {
		return value.flatMap((item) =>
			typeof item === "string" ? [item] : [safeEvidenceText(item)],
		);
	}
	if (value && typeof value === "object") return [safeEvidenceText(value)];
	return [];
}

function safeEvidenceText(value: unknown) {
	try {
		return JSON.stringify(value);
	} catch {
		return "";
	}
}
