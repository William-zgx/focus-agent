import { useShellUi } from "@/app/shell/shell-ui-context";

import { mergeBundleActionLabel } from "./agent-team-workbench-utils";
import { EmptyList, FieldList, HelpText, StatusPill } from "./agent-team-workbench-shared";
import type { AgentTeamMergeBundle, AgentTeamTask } from "./types";

export function PreMergeCheckPanel({
  changedFiles,
  evidenceItems,
  riskItems,
}: {
  changedFiles: string[];
  evidenceItems: string[];
  riskItems: string[];
}) {
  const { isChineseUi } = useShellUi();

  return (
    <section className="fa-agent-team-panel">
      <div className="fa-agent-team-panel-header">
        <div>
          <span>{isChineseUi ? "产出与风险" : "Outputs and risks"}</span>
          <strong>{isChineseUi ? "合并前检查" : "Pre-merge check"}</strong>
          <HelpText>
            {isChineseUi
              ? "这里聚合跨任务文件、artifact 和阻塞项，方便合并前最后检查。"
              : "This aggregates cross-task files, artifacts, and blockers before merge review."}
          </HelpText>
        </div>
      </div>
      <div className="fa-agent-team-detail">
        <section>
          <h3>{isChineseUi ? "改动文件" : "Changed files"}</h3>
          <FieldList items={changedFiles} />
        </section>
        <section>
          <h3>{isChineseUi ? "产出证据" : "Evidence"}</h3>
          <FieldList items={evidenceItems} />
        </section>
        <section>
          <h3>{isChineseUi ? "阻塞 / 风险" : "Blocked / Risks"}</h3>
          <FieldList items={riskItems} />
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
          <span>{isChineseUi ? "第四步 · 合并汇总" : "Step 4 · Merge summary"}</span>
          <strong>{isChineseUi ? "改动、证据、风险一次看清" : "Changes, evidence, and risks"}</strong>
          <HelpText>
            {isChineseUi
              ? "把各任务的改动、证据、风险和未决问题收束成一次可审查的合并建议。"
              : "Collect task changes, evidence, risks, and open questions into one reviewable merge recommendation."}
          </HelpText>
        </div>
        {activeBundle?.recommended_next_action ? (
          <StatusPill status={activeBundle.recommended_next_action} />
        ) : null}
      </div>
      {activeBundle ? (
        <div className="fa-agent-team-merge-grid">
          <p>{activeBundle.summary || (isChineseUi ? "暂无摘要。" : "No summary yet.")}</p>
          <div>
            <h3>{isChineseUi ? "关键发现" : "Key findings"}</h3>
            <FieldList items={activeBundle.key_findings} />
          </div>
          <div>
            <h3>{isChineseUi ? "改动文件" : "Changed files"}</h3>
            <FieldList items={activeBundle.changed_files} />
          </div>
          <div>
            <h3>{isChineseUi ? "验证证据" : "Test evidence"}</h3>
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
        <EmptyList>{isChineseUi ? "还没有生成协作汇总。" : "No collaboration summary generated yet."}</EmptyList>
      )}
      {error ? <div className="fa-inline-notice is-danger">{error.message}</div> : null}
      {!hideAction ? (
        <button
          className="fa-observability-preset is-primary"
          disabled={!canGenerate || isGenerating}
          onClick={onGenerate}
          type="button"
        >
          {mergeBundleActionLabel({
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
