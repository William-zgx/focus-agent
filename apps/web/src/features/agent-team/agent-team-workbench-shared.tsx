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
    ? "Mission Runner 负责计划、运行和生成最终结果；分支线程只是辅助入口。"
    : "Mission Runner plans, runs, and prepares final results; branch threads are supporting links.";
  const steps = isChineseUi
    ? [
        ["1", "生成方案", "把目标拆成几个协作任务"],
        ["2", "运行 Mission", "只启动依赖满足的任务"],
        ["3", "查看结果", "把依据、风险和下一步收束成结果"],
      ]
    : [
        ["1", "Generate plan", "Split the goal into collaboration tasks"],
        ["2", "Run Mission", "Run tasks whose dependencies are ready"],
        ["3", "View result", "Collect evidence, risks, and next steps"],
      ];

  return (
    <section className={`fa-agent-team-guide ${compact ? "is-compact" : ""}`.trim()}>
      <div className="fa-agent-team-guide-heading">
        <span>{isChineseUi ? "Mission Runner" : "Mission Runner"}</span>
        <strong {...tooltipProps(summary)}>
          {isChineseUi ? "从目标到最终结果" : "From goal to final result"}
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
    ? "待开始：任务已创建但未执行；执行中：Agent 正在工作；已完成：产出和验证已回传；需要处理：存在风险或缺口。"
    : "Pending: task exists but has not run; Running: agent is working; Completed: outputs and evidence are returned; Needs attention: risk or gap needs handling.";
  return (
    <span className="fa-agent-team-legend-chip" {...tooltipProps(legendText)}>
      {isChineseUi ? "状态图例" : "Status legend"}
    </span>
  );
}
