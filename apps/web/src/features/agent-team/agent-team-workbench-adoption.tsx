import { useEffect, useMemo, useState } from "react";

import type {
	AgentTeamMergeReview,
	AgentTeamMergeReviewTask,
	AgentTeamSessionView,
	AgentTeamTask,
	AgentTeamTaskOutput,
} from "./types";
import {
	useAgentTeamMergeReviews,
	useApplyAgentTeamMergeReview,
	useCaptureAgentTeamMergeReview,
	useCreateAgentTeamMergeReview,
	usePreviewAgentTeamMergeReview,
	useRejectAgentTeamMergeReview,
	useUpdateAgentTeamMergeReview,
} from "./use-agent-team";
import { errorMessage } from "./agent-team-workbench-utils";

export function AgentTeamAdoptionWorkbench({
	isChineseUi,
	session,
}: {
	isChineseUi: boolean;
	session: AgentTeamSessionView;
}) {
	const sessionId = session.session.session_id;
	const reviewsQuery = useAgentTeamMergeReviews(sessionId);
	const createReview = useCreateAgentTeamMergeReview(sessionId);
	const updateReview = useUpdateAgentTeamMergeReview(sessionId);
	const previewReview = usePreviewAgentTeamMergeReview(sessionId);
	const applyReview = useApplyAgentTeamMergeReview(sessionId);
	const rejectReview = useRejectAgentTeamMergeReview(sessionId);
	const captureReview = useCaptureAgentTeamMergeReview(sessionId);
	const latestReview = reviewsQuery.data?.items[0] ?? null;
	const rows = useMemo(
		() => mergeReviewRows(session.tasks, session.outputs ?? [], latestReview),
		[latestReview, session.outputs, session.tasks],
	);
	const initialSelected = useMemo(
		() =>
			(latestReview?.selected_task_ids?.length
				? latestReview.selected_task_ids
				: rows.filter((row) => row.selected).map((row) => row.task_id)
			).filter(Boolean),
		[latestReview, rows],
	);
	const [selectedTaskIds, setSelectedTaskIds] =
		useState<string[]>(initialSelected);

	useEffect(() => {
		setSelectedTaskIds(initialSelected);
	}, [initialSelected]);

	const selectedSet = useMemo(
		() => new Set(selectedTaskIds),
		[selectedTaskIds],
	);
	const rejectedTaskIds = rows
		.map((row) => row.task_id)
		.filter((taskId) => !selectedSet.has(taskId));
	const selectedRows = rows.filter((row) => selectedSet.has(row.task_id));
	const changedFileCount = new Set(
		selectedRows.flatMap((row) => row.changed_files ?? []),
	).size;
	const testEvidenceCount = selectedRows.flatMap(
		(row) => row.test_evidence ?? [],
	).length;
	const blockedSelectionCount = selectedRows.filter(
		(row) => row.fake || row.placeholder || row.adoptable === false,
	).length;
	const previewData = previewReview.data;
	const activeReview = previewData?.review ?? latestReview;
	const busy =
		createReview.isPending ||
		updateReview.isPending ||
		previewReview.isPending ||
		applyReview.isPending ||
		rejectReview.isPending ||
		captureReview.isPending;
	const canOperate = Boolean(latestReview) && selectedTaskIds.length > 0;

	const toggleTask = (row: AgentTeamMergeReviewTask) => {
		if (row.fake || row.placeholder || row.adoptable === false) return;
		setSelectedTaskIds((current) =>
			current.includes(row.task_id)
				? current.filter((taskId) => taskId !== row.task_id)
				: [...current, row.task_id],
		);
	};
	const createOrRefreshReview = () => {
		const request = {
			selected_task_ids: selectedTaskIds,
			rejected_task_ids: rejectedTaskIds,
		};
		if (latestReview) {
			updateReview.mutate({ reviewId: latestReview.review_id, ...request });
			return;
		}
		createReview.mutate(request);
	};
	const previewSelected = () => {
		if (!latestReview) return;
		previewReview.mutate({
			reviewId: latestReview.review_id,
			selected_task_ids: selectedTaskIds,
			rejected_task_ids: rejectedTaskIds,
		});
	};
	const applySelected = () => {
		if (!latestReview) return;
		applyReview.mutate({
			reviewId: latestReview.review_id,
			selected_task_ids: selectedTaskIds,
			rejected_task_ids: rejectedTaskIds,
		});
	};
	const rejectSelected = () => {
		if (!latestReview) return;
		rejectReview.mutate({ reviewId: latestReview.review_id });
	};
	const captureSelected = () => {
		if (!latestReview) return;
		captureReview.mutate({ reviewId: latestReview.review_id });
	};

	return (
		<section
			className="fa-agent-team-adoption"
			data-smoke="agent-team-adoption"
		>
			<div className="fa-agent-team-adoption-heading">
				<div>
					<span>{isChineseUi ? "采纳工作台" : "Adoption Workbench"}</span>
					<strong>
						{isChineseUi ? "审查并选择性应用结果" : "Review and adopt results"}
					</strong>
				</div>
				<div className="fa-agent-team-adoption-actions">
					<button disabled={busy} onClick={createOrRefreshReview} type="button">
						{latestReview
							? isChineseUi
								? "同步选择"
								: "Sync selection"
							: isChineseUi
								? "创建采纳单"
								: "Create review"}
					</button>
					<button
						disabled={!canOperate || busy}
						onClick={previewSelected}
						type="button"
					>
						{isChineseUi ? "冲突预检" : "Preview"}
					</button>
					<button
						disabled={
							!canOperate ||
							busy ||
							blockedSelectionCount > 0 ||
							previewData?.applicable === false
						}
						onClick={applySelected}
						type="button"
					>
						{isChineseUi ? "应用 Diff" : "Apply diff"}
					</button>
					<button
						disabled={!canOperate || busy}
						onClick={captureSelected}
						type="button"
					>
						{isChineseUi ? "沉淀 Note/Task" : "Capture"}
					</button>
					<button
						disabled={!latestReview || busy}
						onClick={rejectSelected}
						type="button"
					>
						{isChineseUi ? "拒绝" : "Reject"}
					</button>
				</div>
			</div>

			<AdoptionError
				error={
					reviewsQuery.error ??
					createReview.error ??
					updateReview.error ??
					previewReview.error ??
					applyReview.error ??
					rejectReview.error ??
					captureReview.error
				}
				isChineseUi={isChineseUi}
			/>

			<div className="fa-agent-team-adoption-stats">
				<div>
					<span>{isChineseUi ? "状态" : "Status"}</span>
					<strong>
						{activeReview?.status ?? (isChineseUi ? "未创建" : "not created")}
					</strong>
				</div>
				<div>
					<span>{isChineseUi ? "选中任务" : "Selected tasks"}</span>
					<strong>{selectedTaskIds.length}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "文件" : "Files"}</span>
					<strong>{changedFileCount}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "测试证据" : "Test evidence"}</span>
					<strong>{testEvidenceCount}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "冲突" : "Conflicts"}</span>
					<strong>
						{activeReview?.conflict_files?.length ??
							previewData?.conflict_files?.length ??
							0}
					</strong>
				</div>
			</div>

			<div className="fa-agent-team-adoption-grid">
				<div className="fa-agent-team-adoption-task-list">
					{rows.map((row) => {
						const disabled =
							row.fake || row.placeholder || row.adoptable === false;
						return (
							<button
								className={`fa-agent-team-adoption-task ${selectedSet.has(row.task_id) ? "is-selected" : ""} ${
									disabled ? "is-disabled" : ""
								}`.trim()}
								disabled={disabled}
								key={row.task_id}
								onClick={() => toggleTask(row)}
								type="button"
							>
								<span>{row.role ?? "task"}</span>
								<strong>{row.title || row.task_id}</strong>
								<small>
									{row.changed_files?.length ?? 0} files ·{" "}
									{row.workspace_status ?? "workspace pending"}
								</small>
								<div className="fa-agent-team-adoption-tags">
									{row.fake ? <em>fake</em> : null}
									{row.placeholder ? <em>placeholder</em> : null}
									{row.risk_items?.slice(0, 2).map((risk) => (
										<em key={risk}>{risk}</em>
									))}
								</div>
							</button>
						);
					})}
					{!rows.length ? (
						<p className="fa-agent-team-empty">
							{isChineseUi
								? "还没有可审查的任务输出。"
								: "No task outputs are ready for adoption yet."}
						</p>
					) : null}
				</div>

				<div className="fa-agent-team-adoption-detail">
					<div className="fa-agent-team-adoption-block">
						<span>
							{isChineseUi ? "Diff / 冲突预览" : "Diff / conflict preview"}
						</span>
						<pre>
							{previewData?.diffstat ||
								activeReview?.diffstat ||
								activeReview?.diff_summary ||
								(isChineseUi
									? "运行冲突预检后会显示 diffstat。"
									: "Run preview to display the diffstat.")}
						</pre>
					</div>
					<div className="fa-agent-team-adoption-block">
						<span>{isChineseUi ? "测试证据" : "Test evidence"}</span>
						<ul>
							{selectedRows
								.flatMap((row) => row.test_evidence ?? [])
								.slice(0, 8)
								.map((item) => (
									<li key={item}>{item}</li>
								))}
							{!testEvidenceCount ? (
								<li>
									{isChineseUi
										? "暂无测试证据，应用前建议先补预检。"
										: "No test evidence yet; preview before applying."}
								</li>
							) : null}
						</ul>
					</div>
					<div className="fa-agent-team-adoption-block">
						<span>{isChineseUi ? "冲突文件" : "Conflict files"}</span>
						<ul>
							{(
								activeReview?.conflict_files ??
								previewData?.conflict_files ??
								[]
							).map((file) => (
								<li key={file}>{file}</li>
							))}
							{!(
								activeReview?.conflict_files?.length ??
								previewData?.conflict_files?.length
							) ? (
								<li>
									{isChineseUi ? "暂无冲突记录。" : "No conflict records."}
								</li>
							) : null}
						</ul>
					</div>
				</div>
			</div>
		</section>
	);
}

function mergeReviewRows(
	tasks: AgentTeamTask[],
	outputs: AgentTeamTaskOutput[],
	review: AgentTeamMergeReview | null,
): AgentTeamMergeReviewTask[] {
	if (review?.task_reviews?.length) return review.task_reviews;
	const outputByTask = new Map(
		outputs.map((output) => [output.task_id, output]),
	);
	return tasks.map((task) => {
		const output = outputByTask.get(task.task_id);
		const changedFiles = task.changed_files ?? output?.changed_files ?? [];
		const executionMode = String(
			task.execution_mode ??
				output?.metadata?.execution_mode ??
				output?.metadata?.execution ??
				"",
		).toLowerCase();
		const workspaceStatus =
			task.workspace_status ?? output?.workspace_status ?? null;
		const fake = executionMode.includes("fake");
		const placeholder = workspaceStatus === "placeholder";
		return {
			task_id: task.task_id,
			title: task.title ?? task.goal,
			role: String(task.role),
			selected: changedFiles.length > 0 && !fake && !placeholder,
			adoptable: changedFiles.length > 0 && !fake && !placeholder,
			changed_files: changedFiles,
			diff_summary: task.diff_summary ?? output?.diff_summary ?? null,
			test_evidence: task.test_evidence ?? output?.test_evidence ?? [],
			risk_items: task.risk_notes ?? output?.risk_notes ?? [],
			workspace_status: workspaceStatus,
			workspace_branch:
				task.workspace_branch ?? output?.workspace_branch ?? null,
			workspace_path: task.workspace_path ?? output?.workspace_path ?? null,
			placeholder,
			fake,
		};
	});
}

function AdoptionError({
	error,
	isChineseUi,
}: {
	error: Error | null;
	isChineseUi: boolean;
}) {
	if (!error) return null;
	return (
		<div className="fa-inline-notice is-warning">
			{errorMessage(
				error,
				isChineseUi
					? "采纳 API 尚未返回。"
					: "Adoption API did not return yet.",
			)}
		</div>
	);
}
