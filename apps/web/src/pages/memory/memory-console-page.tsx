import type {
	FocusAgentMemoryAuditEvent,
	FocusAgentMemoryCandidate,
	FocusAgentMemoryListRequest,
	FocusAgentMemoryRecord,
} from "@focus-agent/web-sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

const KIND_OPTIONS = [
	"",
	"user_preference",
	"user_profile",
	"project_fact",
	"turn_summary",
	"branch_finding",
	"imported_conclusion",
];
const STATUS_OPTIONS = [
	"",
	"active",
	"conflict",
	"needs_review",
	"forgotten",
	"discarded",
];
const VISIBILITY_OPTIONS = ["", "private", "promotable", "shared"];
const CANDIDATE_STATUS_OPTIONS = [
	"",
	"pending",
	"accepted",
	"rejected",
	"discarded",
];

const KIND_LABELS_ZH: Record<string, string> = {
	branch_finding: "分支发现",
	imported_conclusion: "导入结论",
	project_fact: "项目事实",
	turn_summary: "轮次摘要",
	user_preference: "用户偏好",
	user_profile: "用户画像",
};

const STATUS_LABELS_ZH: Record<string, string> = {
	accepted: "已接受",
	active: "生效中",
	conflict: "冲突",
	discarded: "已丢弃",
	forgotten: "已遗忘",
	needs_review: "待审查",
	pending: "待处理",
	rejected: "已拒绝",
};

const VISIBILITY_LABELS_ZH: Record<string, string> = {
	private: "私有",
	promotable: "可提升",
	shared: "共享",
};

const AUDIT_ACTION_LABELS_ZH: Record<string, string> = {
	accepted: "接受",
	conflict: "冲突",
	discarded: "丢弃",
	forgotten: "遗忘",
	merged: "合并",
	rejected: "拒绝",
	skipped: "跳过",
	write: "写入",
};

export function MemoryConsolePage() {
	const { client, ready } = useFocusAgent();
	const { isChineseUi } = useShellUi();
	const queryClient = useQueryClient();
	const [kind, setKind] = useState("");
	const [status, setStatus] = useState("active");
	const [visibility, setVisibility] = useState("");
	const [candidateStatus, setCandidateStatus] = useState("");
	const [rootThreadId, setRootThreadId] = useState("");
	const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null);

	const request = useMemo<FocusAgentMemoryListRequest>(
		() => ({
			kind: kind || undefined,
			status: status || undefined,
			visibility: visibility || undefined,
			root_thread_id: rootThreadId || undefined,
			limit: 80,
		}),
		[kind, rootThreadId, status, visibility],
	);
	const filtersKey = JSON.stringify(request);
	const auditRequest = useMemo(
		() =>
			selectedMemoryId
				? { memory_id: selectedMemoryId, limit: 30 }
				: { limit: 30 },
		[selectedMemoryId],
	);
	const auditFiltersKey = JSON.stringify(auditRequest);
	const candidateRequest = useMemo(
		() => ({
			status: candidateStatus || undefined,
			root_thread_id: rootThreadId || undefined,
			limit: 30,
		}),
		[candidateStatus, rootThreadId],
	);
	const candidateFiltersKey = JSON.stringify(candidateRequest);
	const memoryQuery = useQuery({
		queryKey: queryKeys.memoryRecords(filtersKey),
		queryFn: () => client.listMemoryRecords(request),
		enabled: ready,
	});
	const auditQuery = useQuery({
		queryKey: queryKeys.memoryAudit(auditFiltersKey),
		queryFn: () => client.listMemoryAuditEvents(auditRequest),
		enabled: ready,
	});
	const candidatesQuery = useQuery({
		queryKey: queryKeys.memoryCandidates(candidateFiltersKey),
		queryFn: () => client.listMemoryCandidates(candidateRequest),
		enabled: ready,
	});
	const forgetMutation = useMutation({
		mutationFn: (memoryId: string) =>
			client.forgetMemoryRecord(memoryId, { reason: "memory_console_forget" }),
		onSuccess: async () => {
			await queryClient.invalidateQueries({
				queryKey: queryKeys.memoryRecordsRoot,
			});
			await queryClient.invalidateQueries({
				queryKey: queryKeys.memoryAuditRoot,
			});
		},
	});

	const memories = memoryQuery.data?.items ?? [];
	const selected =
		memories.find((item) => item.memory_id === selectedMemoryId) ??
		memories[0] ??
		null;
	const auditItems = auditQuery.data?.items ?? [];
	const candidates = candidatesQuery.data?.items ?? [];

	return (
		<main className="fa-trajectory-workbench">
			<section className="fa-trajectory-workbench-header">
				<div className="fa-trajectory-workbench-header-copy">
					<p className="fa-trajectory-workbench-eyebrow">
						{isChineseUi ? "Canonical Memory" : "Canonical Memory"}
					</p>
					<div className="fa-trajectory-workbench-heading">
						<h1>
							{isChineseUi ? "Postgres 记忆控制台" : "Postgres Memory Console"}
						</h1>
					</div>
				</div>
				<div className="fa-trajectory-workbench-header-side">
					<p className="fa-trajectory-workbench-focus-note">
						{memoryQuery.data?.backend ?? "postgres"} · {memories.length}{" "}
						{isChineseUi ? "条记录" : "records"}
					</p>
				</div>
			</section>

			<section className="fa-trajectory-workbench-filters">
				<label className="fa-observability-filter">
					<span>{isChineseUi ? "类型" : "Kind"}</span>
					<select
						value={kind}
						onChange={(event) => setKind(event.target.value)}
					>
						{KIND_OPTIONS.map((option) => (
							<option key={option || "all"} value={option}>
								{memoryKindLabel(option, isChineseUi)}
							</option>
						))}
					</select>
				</label>
				<label className="fa-observability-filter">
					<span>{isChineseUi ? "状态" : "Status"}</span>
					<select
						value={status}
						onChange={(event) => setStatus(event.target.value)}
					>
						{STATUS_OPTIONS.map((option) => (
							<option key={option || "all"} value={option}>
								{memoryStatusOptionLabel(option, isChineseUi)}
							</option>
						))}
					</select>
				</label>
				<label className="fa-observability-filter">
					<span>{isChineseUi ? "可见性" : "Visibility"}</span>
					<select
						value={visibility}
						onChange={(event) => setVisibility(event.target.value)}
					>
						{VISIBILITY_OPTIONS.map((option) => (
							<option key={option || "all"} value={option}>
								{memoryVisibilityLabel(option, isChineseUi)}
							</option>
						))}
					</select>
				</label>
				<label className="fa-observability-filter">
					<span>{isChineseUi ? "候选状态" : "Candidate status"}</span>
					<select
						value={candidateStatus}
						onChange={(event) => setCandidateStatus(event.target.value)}
					>
						{CANDIDATE_STATUS_OPTIONS.map((option) => (
							<option key={option || "all"} value={option}>
								{memoryStatusOptionLabel(option, isChineseUi)}
							</option>
						))}
					</select>
				</label>
				<label className="fa-observability-filter">
					<span>{isChineseUi ? "根线程" : "Root thread"}</span>
					<input
						value={rootThreadId}
						onChange={(event) => setRootThreadId(event.target.value)}
					/>
				</label>
			</section>

			<section className="fa-trajectory-workbench-story-grid">
				<article className="fa-trajectory-workbench-story-card">
					<div className="fa-trajectory-workbench-section-head">
						<h2>{isChineseUi ? "记忆记录" : "Records"}</h2>
						<span>
							{memoryQuery.isFetching
								? isChineseUi
									? "加载中"
									: "loading"
								: `${memories.length}`}
						</span>
					</div>
					<div className="fa-trajectory-overview-list">
						{memories.map((item) => (
							<button
								key={item.memory_id}
								className={`fa-trajectory-overview-list-item is-button ${selected?.memory_id === item.memory_id ? "is-active" : ""}`.trim()}
								onClick={() => setSelectedMemoryId(item.memory_id)}
								type="button"
							>
								<div>
									<span>
										{memoryKindLabel(item.kind, isChineseUi)} ·{" "}
										{memoryStatusLabel(item.status, isChineseUi)}
									</span>
									<strong>
										{compact(memoryDisplayText(item, isChineseUi), 120)}
									</strong>
									<em>{embeddingDisplayText(item, isChineseUi)}</em>
								</div>
							</button>
						))}
						{!memories.length ? (
							<div className="fa-route-state-card">
								{isChineseUi ? "暂无记忆记录。" : "No memory records found."}
							</div>
						) : null}
					</div>
				</article>

				<article className="fa-trajectory-workbench-story-card">
					<div className="fa-trajectory-workbench-section-head">
						<h2>{isChineseUi ? "详情" : "Detail"}</h2>
						{selected ? (
							<button
								className="fa-admin-secondary-button"
								disabled={
									forgetMutation.isPending || selected.status === "forgotten"
								}
								onClick={() => forgetMutation.mutate(selected.memory_id)}
								type="button"
							>
								{forgetMutation.isPending
									? isChineseUi
										? "遗忘中"
										: "Forgetting"
									: isChineseUi
										? "遗忘"
										: "Forget"}
							</button>
						) : null}
					</div>
					{selected ? (
						<MemoryDetail isChineseUi={isChineseUi} item={selected} />
					) : (
						<div className="fa-route-state-card">
							{isChineseUi ? "请选择一条记忆记录。" : "Select a memory record."}
						</div>
					)}
				</article>

				<article className="fa-trajectory-workbench-story-card">
					<div className="fa-trajectory-workbench-section-head">
						<h2>{isChineseUi ? "审计" : "Audit"}</h2>
						<span>{auditItems.length}</span>
					</div>
					<div className="fa-trajectory-workbench-raw-stack">
						{auditItems.map((item) => (
							<AuditRow
								isChineseUi={isChineseUi}
								key={item.event_id}
								item={item}
							/>
						))}
						{!auditItems.length ? (
							<div className="fa-route-state-card">
								{isChineseUi ? "暂无审计事件。" : "No audit events."}
							</div>
						) : null}
					</div>
				</article>

				<article className="fa-trajectory-workbench-story-card">
					<div className="fa-trajectory-workbench-section-head">
						<h2>{isChineseUi ? "候选记忆" : "Candidates"}</h2>
						<span>{candidates.length}</span>
					</div>
					<div className="fa-trajectory-workbench-raw-stack">
						{candidates.map((item) => (
							<CandidateRow
								isChineseUi={isChineseUi}
								key={item.candidate_id}
								item={item}
							/>
						))}
						{!candidates.length ? (
							<div className="fa-route-state-card">
								{isChineseUi ? "暂无候选记忆。" : "No candidates."}
							</div>
						) : null}
					</div>
				</article>
			</section>
		</main>
	);
}

function MemoryDetail({
	isChineseUi,
	item,
}: {
	isChineseUi: boolean;
	item: FocusAgentMemoryRecord;
}) {
	return (
		<dl className="fa-observability-detail-grid">
			<div>
				<dt>ID</dt>
				<dd>{item.memory_id}</dd>
			</div>
			<div>
				<dt>{isChineseUi ? "命名空间" : "Namespace"}</dt>
				<dd>{(item.namespace ?? []).join("/")}</dd>
			</div>
			<div>
				<dt>{isChineseUi ? "来源" : "Source"}</dt>
				<dd>
					{item.source_branch_id ||
						item.source_thread_id ||
						item.root_thread_id ||
						(isChineseUi ? "无" : "none")}
				</dd>
			</div>
			<div>
				<dt>{isChineseUi ? "Embedding 状态" : "Embedding status"}</dt>
				<dd>{memoryStatusLabel(item.embedding_status || "", isChineseUi)}</dd>
			</div>
			<div>
				<dt>{isChineseUi ? "Embedding 模型" : "Embedding model"}</dt>
				<dd>{item.embedding_model_id || (isChineseUi ? "无" : "none")}</dd>
			</div>
			<div>
				<dt>{isChineseUi ? "Embedding 更新时间" : "Embedding updated"}</dt>
				<dd>{formatMemoryTimestamp(item.embedding_updated_at, isChineseUi)}</dd>
			</div>
			<div>
				<dt>{isChineseUi ? "摘要" : "Summary"}</dt>
				<dd>{memoryDisplayText(item, isChineseUi)}</dd>
			</div>
		</dl>
	);
}

function AuditRow({
	isChineseUi,
	item,
}: {
	isChineseUi: boolean;
	item: FocusAgentMemoryAuditEvent;
}) {
	return (
		<div className="fa-observability-detail-block">
			<strong>
				{auditActionLabel(item.action, isChineseUi)} ·{" "}
				{memoryStatusLabel(item.decision, isChineseUi)}
			</strong>
			<p>{item.reason || item.memory_id || item.event_id}</p>
		</div>
	);
}

function CandidateRow({
	isChineseUi,
	item,
}: {
	isChineseUi: boolean;
	item: FocusAgentMemoryCandidate;
}) {
	const candidateSummary =
		typeof item.record?.summary === "string"
			? item.record.summary
			: typeof item.record?.content === "string"
				? item.record.content
				: item.reason;

	return (
		<div className="fa-observability-detail-block">
			<strong>
				{memoryStatusLabel(item.status || "pending", isChineseUi)} ·{" "}
				{item.branch_id || item.task_id || item.candidate_id}
			</strong>
			<p>{compact(candidateSummary ?? "", 120)}</p>
		</div>
	);
}

function compact(value: string, limit: number) {
	return value.length > limit ? `${value.slice(0, limit - 1)}...` : value;
}

function embeddingDisplayText(
	item: FocusAgentMemoryRecord,
	isChineseUi: boolean,
) {
	return [
		memoryStatusLabel(item.embedding_status || "", isChineseUi),
		item.embedding_model_id || (isChineseUi ? "无模型" : "no model"),
		formatMemoryTimestamp(item.embedding_updated_at, isChineseUi),
	].join(" · ");
}

function formatMemoryTimestamp(value?: string | null, isChineseUi = false) {
	if (!value) {
		return isChineseUi ? "无" : "none";
	}
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) {
		return value;
	}
	return date.toLocaleString();
}

function memoryDisplayText(item: FocusAgentMemoryRecord, isChineseUi = false) {
	if (item.payload_redacted || item.status === "forgotten") {
		return isChineseUi ? "[已遗忘]" : "[forgotten]";
	}
	return item.summary || item.content || item.memory_id;
}

function memoryKindLabel(
	value: string | null | undefined,
	isChineseUi: boolean,
) {
	const normalized = value || "";
	if (!normalized) return isChineseUi ? "全部" : "all";
	if (!isChineseUi) return normalized;
	return KIND_LABELS_ZH[normalized] ?? normalized;
}

function memoryStatusLabel(
	value: string | null | undefined,
	isChineseUi: boolean,
) {
	const normalized = value || "";
	if (!normalized) return isChineseUi ? "未知" : "unknown";
	if (!isChineseUi) return normalized;
	return STATUS_LABELS_ZH[normalized] ?? normalized;
}

function memoryStatusOptionLabel(
	value: string | null | undefined,
	isChineseUi: boolean,
) {
	const normalized = value || "";
	if (!normalized) return isChineseUi ? "全部" : "all";
	return memoryStatusLabel(normalized, isChineseUi);
}

function memoryVisibilityLabel(
	value: string | null | undefined,
	isChineseUi: boolean,
) {
	const normalized = value || "";
	if (!normalized) return isChineseUi ? "全部" : "all";
	if (!isChineseUi) return normalized;
	return VISIBILITY_LABELS_ZH[normalized] ?? normalized;
}

function auditActionLabel(
	value: string | null | undefined,
	isChineseUi: boolean,
) {
	const normalized = value || "";
	if (!normalized) return isChineseUi ? "未知操作" : "unknown";
	if (!isChineseUi) return normalized;
	return AUDIT_ACTION_LABELS_ZH[normalized] ?? normalized;
}
