import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import { STATUS_TONES, statusLabel } from "./agent-team-workbench-utils";

export function StatusPill({ status }: { status: string }) {
  const { isChineseUi } = useShellUi();
  const tone = STATUS_TONES[status] ?? "neutral";
  return <span className={`fa-agent-team-pill is-${tone}`}>{statusLabel(status, isChineseUi)}</span>;
}

export function EmptyList({ children }: { children: string }) {
  return <div className="fa-agent-team-empty">{children}</div>;
}

export function FieldList({ items }: { items?: string[] }) {
  if (!items?.length) return <EmptyList>—</EmptyList>;
  return (
    <ul className="fa-agent-team-list">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function HelpText({ children }: { children: string }) {
  const { isChineseUi } = useShellUi();
  return (
    <span
      aria-label={isChineseUi ? "说明" : "Help"}
      className="fa-agent-team-help-tip"
      role="img"
      tabIndex={0}
      {...tooltipProps(children)}
    />
  );
}

export function WorkflowGuide({ compact = false }: { compact?: boolean }) {
  const { isChineseUi } = useShellUi();
  const summary = isChineseUi
    ? "把一个大目标拆给多个 Agent，并保留可回溯证据。"
    : "Split one large goal across agents while keeping traceable evidence.";
  const steps = isChineseUi
    ? [
        ["1", "写目标", "说明这组 Agent 要一起完成什么"],
        ["2", "生成任务", "自动拆成规划、执行、测试、审查、验证分支"],
        ["3", "进分支做事", "每个 Agent 在线程里留下产出和证据"],
        ["4", "汇总合并", "把改动、风险、验证证据收束成建议"],
      ]
    : [
        ["1", "Write goal", "Describe what the agents should finish together"],
        ["2", "Create tasks", "Split into planning, execution, test, review, and verification branches"],
        ["3", "Work in branches", "Each agent leaves outputs and evidence in its thread"],
        ["4", "Merge summary", "Collect changes, risks, and evidence into a recommendation"],
      ];

  return (
    <section className={`fa-agent-team-guide ${compact ? "is-compact" : ""}`.trim()}>
      <div className="fa-agent-team-guide-heading">
        <span>{isChineseUi ? "它是做什么的" : "What this does"}</span>
        <strong {...tooltipProps(summary)}>
          {isChineseUi ? "4 步完成多 Agent 协作" : "Finish multi-agent work in 4 steps"}
        </strong>
      </div>
      <div className="fa-agent-team-step-strip">
        {steps.map(([index, title, description]) => (
          <div className="fa-agent-team-step" key={index} {...tooltipProps(description)}>
            <span>{index}</span>
            <strong>{title}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

export function StatusLegend() {
  const { isChineseUi } = useShellUi();
  const legendText = isChineseUi
    ? "待开始：任务已创建但未执行；执行中：Agent 正在分支工作；已完成：产出和验证已回传；阻塞：需要处理风险或缺口。"
    : "Pending: task exists but has not run; Running: agent is working in a branch; Completed: outputs and evidence are returned; Blocked: risk or gap needs attention.";
  return (
    <span className="fa-agent-team-legend-chip" {...tooltipProps(legendText)}>
      {isChineseUi ? "状态图例" : "Status legend"}
    </span>
  );
}
