import type {
  FocusAgentMemoryAuditEvent,
  FocusAgentMemoryCandidate,
  FocusAgentMemoryListRequest,
  FocusAgentMemoryRecord,
} from "@focus-agent/web-sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

const KIND_OPTIONS = ["", "user_preference", "user_profile", "project_fact", "turn_summary", "branch_finding", "imported_conclusion"];
const STATUS_OPTIONS = ["", "active", "conflict", "needs_review", "forgotten", "discarded"];
const VISIBILITY_OPTIONS = ["", "private", "promotable", "shared"];
const CANDIDATE_STATUS_OPTIONS = ["", "pending", "accepted", "rejected", "discarded"];

export function MemoryConsolePage() {
  const { client, ready } = useFocusAgent();
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
    () => (selectedMemoryId ? { memory_id: selectedMemoryId, limit: 30 } : { limit: 30 }),
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
    mutationFn: (memoryId: string) => client.forgetMemoryRecord(memoryId, { reason: "memory_console_forget" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.memoryRecordsRoot });
      await queryClient.invalidateQueries({ queryKey: queryKeys.memoryAuditRoot });
    },
  });

  const memories = memoryQuery.data?.items ?? [];
  const selected = memories.find((item) => item.memory_id === selectedMemoryId) ?? memories[0] ?? null;
  const auditItems = auditQuery.data?.items ?? [];
  const candidates = candidatesQuery.data?.items ?? [];

  return (
    <main className="fa-trajectory-workbench">
      <section className="fa-trajectory-workbench-header">
        <div className="fa-trajectory-workbench-header-copy">
          <p className="fa-trajectory-workbench-eyebrow">Canonical Memory</p>
          <div className="fa-trajectory-workbench-heading">
            <h1>Postgres Memory Console</h1>
          </div>
        </div>
        <div className="fa-trajectory-workbench-header-side">
          <p className="fa-trajectory-workbench-focus-note">
            {memoryQuery.data?.backend ?? "postgres"} · {memories.length} records
          </p>
        </div>
      </section>

      <section className="fa-trajectory-workbench-filters">
        <label className="fa-observability-filter">
          <span>Kind</span>
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            {KIND_OPTIONS.map((option) => (
              <option key={option || "all"} value={option}>
                {option || "all"}
              </option>
            ))}
          </select>
        </label>
        <label className="fa-observability-filter">
          <span>Status</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            {STATUS_OPTIONS.map((option) => (
              <option key={option || "all"} value={option}>
                {option || "all"}
              </option>
            ))}
          </select>
        </label>
        <label className="fa-observability-filter">
          <span>Visibility</span>
          <select value={visibility} onChange={(event) => setVisibility(event.target.value)}>
            {VISIBILITY_OPTIONS.map((option) => (
              <option key={option || "all"} value={option}>
                {option || "all"}
              </option>
            ))}
          </select>
        </label>
        <label className="fa-observability-filter">
          <span>Candidate status</span>
          <select value={candidateStatus} onChange={(event) => setCandidateStatus(event.target.value)}>
            {CANDIDATE_STATUS_OPTIONS.map((option) => (
              <option key={option || "all"} value={option}>
                {option || "all"}
              </option>
            ))}
          </select>
        </label>
        <label className="fa-observability-filter">
          <span>Root thread</span>
          <input value={rootThreadId} onChange={(event) => setRootThreadId(event.target.value)} />
        </label>
      </section>

      <section className="fa-trajectory-workbench-story-grid">
        <article className="fa-trajectory-workbench-story-card">
          <div className="fa-trajectory-workbench-section-head">
            <h2>Records</h2>
            <span>{memoryQuery.isFetching ? "loading" : `${memories.length}`}</span>
          </div>
          <div className="fa-trajectory-overview-list">
            {memories.map((item) => (
              <button
                key={item.memory_id}
                className={`fa-trajectory-overview-list-item is-button ${selected?.memory_id === item.memory_id ? "is-active" : ""}`.trim()}
                onClick={() => setSelectedMemoryId(item.memory_id)}
                type="button"
              >
                <span>{item.kind} · {item.status}</span>
                <strong>{compact(memoryDisplayText(item), 120)}</strong>
              </button>
            ))}
            {!memories.length ? <div className="fa-route-state-card">No memory records found.</div> : null}
          </div>
        </article>

        <article className="fa-trajectory-workbench-story-card">
          <div className="fa-trajectory-workbench-section-head">
            <h2>Detail</h2>
            {selected ? (
              <button
                className="fa-admin-secondary-button"
                disabled={forgetMutation.isPending || selected.status === "forgotten"}
                onClick={() => forgetMutation.mutate(selected.memory_id)}
                type="button"
              >
                {forgetMutation.isPending ? "Forgetting" : "Forget"}
              </button>
            ) : null}
          </div>
          {selected ? <MemoryDetail item={selected} /> : <div className="fa-route-state-card">Select a memory record.</div>}
        </article>

        <article className="fa-trajectory-workbench-story-card">
          <div className="fa-trajectory-workbench-section-head">
            <h2>Audit</h2>
            <span>{auditItems.length}</span>
          </div>
          <div className="fa-trajectory-workbench-raw-stack">
            {auditItems.map((item) => <AuditRow key={item.event_id} item={item} />)}
            {!auditItems.length ? <div className="fa-route-state-card">No audit events.</div> : null}
          </div>
        </article>

        <article className="fa-trajectory-workbench-story-card">
          <div className="fa-trajectory-workbench-section-head">
            <h2>Candidates</h2>
            <span>{candidates.length}</span>
          </div>
          <div className="fa-trajectory-workbench-raw-stack">
            {candidates.map((item) => <CandidateRow key={item.candidate_id} item={item} />)}
            {!candidates.length ? <div className="fa-route-state-card">No candidates.</div> : null}
          </div>
        </article>
      </section>
    </main>
  );
}

function MemoryDetail({ item }: { item: FocusAgentMemoryRecord }) {
  return (
    <dl className="fa-observability-detail-grid">
      <div>
        <dt>ID</dt>
        <dd>{item.memory_id}</dd>
      </div>
      <div>
        <dt>Namespace</dt>
        <dd>{(item.namespace ?? []).join("/")}</dd>
      </div>
      <div>
        <dt>Source</dt>
        <dd>{item.source_branch_id || item.source_thread_id || item.root_thread_id || "none"}</dd>
      </div>
      <div>
        <dt>Summary</dt>
        <dd>{memoryDisplayText(item)}</dd>
      </div>
    </dl>
  );
}

function AuditRow({ item }: { item: FocusAgentMemoryAuditEvent }) {
  return (
    <div className="fa-observability-detail-block">
      <strong>{item.action} · {item.decision}</strong>
      <p>{item.reason || item.memory_id || item.event_id}</p>
    </div>
  );
}

function CandidateRow({ item }: { item: FocusAgentMemoryCandidate }) {
  const candidateSummary =
    typeof item.record?.summary === "string"
      ? item.record.summary
      : typeof item.record?.content === "string"
        ? item.record.content
        : item.reason;

  return (
    <div className="fa-observability-detail-block">
      <strong>{item.status || "pending"} · {item.branch_id || item.task_id || item.candidate_id}</strong>
      <p>{compact(candidateSummary ?? "", 120)}</p>
    </div>
  );
}

function compact(value: string, limit: number) {
  return value.length > limit ? `${value.slice(0, limit - 1)}...` : value;
}

function memoryDisplayText(item: FocusAgentMemoryRecord) {
  if (item.payload_redacted || item.status === "forgotten") {
    return "[forgotten]";
  }
  return item.summary || item.content || item.memory_id;
}
