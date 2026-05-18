import type {
	FocusAgentNote,
	FocusAgentProductivitySourceKind,
	FocusAgentTask,
	FocusAgentTaskStatus,
} from "@focus-agent/web-sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

type ProductivityPageMode = "notes" | "tasks";

function statusTone(status: FocusAgentTaskStatus) {
	if (status === "completed") return "is-success";
	if (status === "archived") return "is-danger";
	if (status === "in_progress") return "is-warning";
	return "is-neutral";
}

function noteTitleFromDraft(value: string) {
	const [firstLine] = value
		.split("\n")
		.map((line) => line.trim())
		.filter(Boolean);
	return firstLine?.slice(0, 80) || "Untitled note";
}

export function ProductivityPage({ mode }: { mode: ProductivityPageMode }) {
	const { isChineseUi } = useShellUi();
	const { client, ready } = useFocusAgent();
	const queryClient = useQueryClient();
	const [selectedTaskId, setSelectedTaskId] = useState("");
	const [draftNote, setDraftNote] = useState("");
	const [noteQuery, setNoteQuery] = useState("");
	const [draftTaskTitle, setDraftTaskTitle] = useState("");
	const [draftTaskDescription, setDraftTaskDescription] = useState("");
	const [sourceKind, setSourceKind] = useState<
		FocusAgentProductivitySourceKind | ""
	>("");

	const noteRequest = useMemo(
		() => ({
			q: noteQuery || undefined,
			source_kind: sourceKind || undefined,
			limit: 50,
		}),
		[noteQuery, sourceKind],
	);
	const noteFiltersKey = JSON.stringify(noteRequest);
	const notesQuery = useQuery({
		queryKey: queryKeys.productivityNotes(noteFiltersKey),
		queryFn: () => client.listNotes(noteRequest),
		enabled: ready,
	});
	const tasksQuery = useQuery({
		queryKey: queryKeys.productivityTasks(sourceKind || "active"),
		queryFn: () =>
			client.listTasks({ limit: 80, source_kind: sourceKind || undefined }),
		enabled: ready,
	});
	const notes = notesQuery.data?.items ?? [];
	const tasks = tasksQuery.data?.items ?? [];
	const selectedTask =
		tasks.find((task) => task.task_id === selectedTaskId) ?? tasks[0] ?? null;
	const taskCounts = useMemo(
		() =>
			tasks.reduce(
				(acc, task) => {
					acc[task.status] += 1;
					return acc;
				},
				{ todo: 0, in_progress: 0, completed: 0, archived: 0 },
			),
		[tasks],
	);

	const invalidateNotes = () =>
		queryClient.invalidateQueries({
			queryKey: queryKeys.productivityNotesRoot,
		});
	const invalidateTasks = () =>
		queryClient.invalidateQueries({
			queryKey: queryKeys.productivityTasksRoot,
		});

	const createNoteMutation = useMutation({
		mutationFn: () =>
			client.createNote({
				title: noteTitleFromDraft(draftNote),
				body: draftNote,
				tags: ["web"],
			}),
		onSuccess: () => {
			setDraftNote("");
			void invalidateNotes();
		},
	});
	const archiveNoteMutation = useMutation({
		mutationFn: (note: FocusAgentNote) =>
			client.updateNote(note.note_id, {
				status: "archived",
				is_archived: true,
			}),
		onSuccess: () => void invalidateNotes(),
	});
	const createTaskMutation = useMutation({
		mutationFn: () =>
			client.createTask({
				title: draftTaskTitle,
				description: draftTaskDescription,
			}),
		onSuccess: () => {
			setDraftTaskTitle("");
			setDraftTaskDescription("");
			void invalidateTasks();
		},
	});
	const completeTaskMutation = useMutation({
		mutationFn: (task: FocusAgentTask) => client.completeTask(task.task_id),
		onSuccess: () => void invalidateTasks(),
	});

	return (
		<div className="fa-productivity-layout">
			<header className="fa-productivity-header">
				<div>
					<span>{isChineseUi ? "生产力" : "Productivity"}</span>
					<h1>{mode === "notes" ? "Notes" : "Tasks"}</h1>
					<p>
						{isChineseUi
							? "把线程、任务和验证依据压缩成可扫读的工作台。"
							: "A compact workspace for thread notes, task follow-up, and evidence."}
					</p>
				</div>
				<nav
					className="fa-productivity-tabs"
					aria-label={isChineseUi ? "生产力导航" : "Productivity navigation"}
				>
					<select
						aria-label={isChineseUi ? "来源过滤" : "Source filter"}
						className="fa-productivity-source-filter"
						value={sourceKind}
						onChange={(event) =>
							setSourceKind(
								event.target.value as FocusAgentProductivitySourceKind | "",
							)
						}
					>
						<option value="">{isChineseUi ? "全部来源" : "All sources"}</option>
						<option value="chat">{isChineseUi ? "对话" : "Chat"}</option>
						<option value="agent_team">Agent Team</option>
						<option value="merge_review">
							{isChineseUi ? "采纳单" : "Merge review"}
						</option>
						<option value="task_output">
							{isChineseUi ? "任务输出" : "Task output"}
						</option>
					</select>
					<Link
						className={`fa-productivity-tab ${mode === "tasks" ? "is-active" : ""}`.trim()}
						to="/productivity/tasks"
					>
						{isChineseUi ? "任务" : "Tasks"}
					</Link>
					<Link
						className={`fa-productivity-tab ${mode === "notes" ? "is-active" : ""}`.trim()}
						to="/productivity/notes"
					>
						{isChineseUi ? "笔记" : "Notes"}
					</Link>
				</nav>
			</header>

			{mode === "notes" ? (
				<div className="fa-productivity-grid is-notes">
					<section className="fa-productivity-panel">
						<div className="fa-productivity-panel-heading">
							<span>{isChineseUi ? "收件箱" : "Inbox"}</span>
							<strong>{isChineseUi ? "最近笔记" : "Recent notes"}</strong>
						</div>
						<input
							className="fa-productivity-note-input is-single-line"
							placeholder={isChineseUi ? "搜索笔记" : "Search notes"}
							value={noteQuery}
							onChange={(event) => setNoteQuery(event.target.value)}
						/>
						<div className="fa-productivity-note-list">
							{notes.map((note) => (
								<article className="fa-productivity-note" key={note.note_id}>
									<div className="fa-productivity-note-top">
										<strong>{note.title}</strong>
										<span>
											{new Date(note.updated_at).toLocaleDateString()}
										</span>
									</div>
									<p>{note.body || note.title}</p>
									<div className="fa-productivity-chip-row">
										<span>{note.status}</span>
										<SourceAffordance
											isChineseUi={isChineseUi}
											source={{
												source_artifact_id: note.source_artifact_id,
												source_id: note.source_id,
												source_kind: note.source_kind,
												source_thread_id: note.source_thread_id,
												source_url: note.source_url,
											}}
										/>
										{note.tags.map((tag) => (
											<span key={tag}>{tag}</span>
										))}
										<button
											type="button"
											onClick={() => archiveNoteMutation.mutate(note)}
										>
											{isChineseUi ? "归档" : "Archive"}
										</button>
									</div>
								</article>
							))}
							{!notes.length ? (
								<p className="fa-productivity-empty">
									{notesQuery.isLoading
										? isChineseUi
											? "加载中"
											: "Loading"
										: isChineseUi
											? "暂无笔记"
											: "No notes yet"}
								</p>
							) : null}
						</div>
					</section>
					<section className="fa-productivity-panel">
						<div className="fa-productivity-panel-heading">
							<span>{isChineseUi ? "草稿" : "Draft"}</span>
							<strong>{isChineseUi ? "捕获下一条" : "Capture next"}</strong>
						</div>
						<textarea
							className="fa-productivity-note-input"
							placeholder={
								isChineseUi
									? "记录一个决定、风险、验证命令或后续动作。"
									: "Capture a decision, risk, verification command, or follow-up."
							}
							value={draftNote}
							onChange={(event) => setDraftNote(event.target.value)}
						/>
						<div className="fa-productivity-draft-meta">
							<span>{draftNote.trim().length} chars</span>
							<button
								type="button"
								disabled={!draftNote.trim() || createNoteMutation.isPending}
								onClick={() => createNoteMutation.mutate()}
							>
								{isChineseUi ? "保存" : "Save"}
							</button>
						</div>
					</section>
				</div>
			) : (
				<div className="fa-productivity-grid is-tasks">
					<section className="fa-productivity-panel">
						<div className="fa-productivity-panel-heading">
							<span>{isChineseUi ? "队列" : "Queue"}</span>
							<strong>
								{isChineseUi ? "状态分布" : "Status distribution"}
							</strong>
						</div>
						<div className="fa-productivity-stat-grid">
							{Object.entries(taskCounts).map(([status, count]) => (
								<div className="fa-productivity-stat" key={status}>
									<span>{status}</span>
									<strong>{count}</strong>
								</div>
							))}
						</div>
						<div className="fa-productivity-task-list">
							{tasks.map((task) => (
								<button
									className={`fa-productivity-task ${selectedTask?.task_id === task.task_id ? "is-selected" : ""}`.trim()}
									key={task.task_id}
									type="button"
									onClick={() => setSelectedTaskId(task.task_id)}
								>
									<span
										className={`fa-productivity-pill ${statusTone(task.status)}`}
									>
										{task.status}
									</span>
									<strong>{task.title}</strong>
									<small>{task.due_at ?? task.updated_at}</small>
								</button>
							))}
							{!tasks.length ? (
								<p className="fa-productivity-empty">
									{tasksQuery.isLoading
										? isChineseUi
											? "加载中"
											: "Loading"
										: isChineseUi
											? "暂无任务"
											: "No tasks yet"}
								</p>
							) : null}
						</div>
					</section>
					<section className="fa-productivity-panel">
						<div className="fa-productivity-panel-heading">
							<span>{isChineseUi ? "详情" : "Detail"}</span>
							<strong>
								{selectedTask?.title ?? (isChineseUi ? "新任务" : "New task")}
							</strong>
						</div>
						{selectedTask ? (
							<div className="fa-productivity-detail-grid">
								<div>
									<span>{isChineseUi ? "负责人" : "Assignee"}</span>
									<strong>
										{selectedTask.assignee_user_id ?? selectedTask.user_id}
									</strong>
								</div>
								<div>
									<span>{isChineseUi ? "时间" : "Due"}</span>
									<strong>{selectedTask.due_at ?? "none"}</strong>
								</div>
								<div>
									<span>{isChineseUi ? "来源" : "Source"}</span>
									<strong>
										{selectedTask.source_kind ??
											selectedTask.source_thread_id ??
											selectedTask.source_note_id ??
											"manual"}
									</strong>
								</div>
								<div>
									<span>{isChineseUi ? "状态" : "Status"}</span>
									<strong>{selectedTask.status}</strong>
								</div>
								<button
									type="button"
									disabled={
										selectedTask.status === "completed" ||
										completeTaskMutation.isPending
									}
									onClick={() => completeTaskMutation.mutate(selectedTask)}
								>
									{isChineseUi ? "完成" : "Complete"}
								</button>
								<SourceAffordance
									isChineseUi={isChineseUi}
									source={{
										source_id: selectedTask.source_id,
										source_kind: selectedTask.source_kind,
										source_note_id: selectedTask.source_note_id,
										source_thread_id: selectedTask.source_thread_id,
										source_url: selectedTask.source_url,
									}}
								/>
							</div>
						) : null}
						<input
							className="fa-productivity-note-input is-single-line"
							placeholder={isChineseUi ? "任务标题" : "Task title"}
							value={draftTaskTitle}
							onChange={(event) => setDraftTaskTitle(event.target.value)}
						/>
						<textarea
							className="fa-productivity-note-input is-compact"
							placeholder={isChineseUi ? "描述" : "Description"}
							value={draftTaskDescription}
							onChange={(event) => setDraftTaskDescription(event.target.value)}
						/>
						<div className="fa-productivity-draft-meta">
							<span>{draftTaskTitle.trim().length} chars</span>
							<button
								type="button"
								disabled={
									!draftTaskTitle.trim() || createTaskMutation.isPending
								}
								onClick={() => createTaskMutation.mutate()}
							>
								{isChineseUi ? "创建" : "Create"}
							</button>
						</div>
					</section>
				</div>
			)}
		</div>
	);
}

type ProductivitySource = {
	source_artifact_id?: string | null;
	source_id?: string | null;
	source_kind?: string | null;
	source_note_id?: string | null;
	source_thread_id?: string | null;
	source_url?: string | null;
};

function SourceAffordance({
	isChineseUi,
	source,
}: {
	isChineseUi: boolean;
	source: ProductivitySource;
}) {
	const label =
		source.source_kind ??
		(source.source_thread_id
			? "chat"
			: source.source_note_id
				? "note"
				: "manual");
	const sourceId =
		source.source_id ??
		source.source_thread_id ??
		source.source_note_id ??
		source.source_artifact_id ??
		"";
	if (source.source_url) {
		return (
			<a
				className="fa-productivity-source-link"
				href={source.source_url}
				rel="noreferrer"
				target="_blank"
			>
				{isChineseUi ? "打开来源" : "Open source"}
			</a>
		);
	}
	if (source.source_thread_id) {
		return (
			<Link
				className="fa-productivity-source-link"
				params={{
					conversationId: source.source_thread_id,
					threadId: source.source_thread_id,
				}}
				to="/c/$conversationId/t/$threadId"
			>
				{label}
			</Link>
		);
	}
	return (
		<span className="fa-productivity-source-link">
			{sourceId ? `${label}:${sourceId.slice(0, 8)}` : label}
		</span>
	);
}
