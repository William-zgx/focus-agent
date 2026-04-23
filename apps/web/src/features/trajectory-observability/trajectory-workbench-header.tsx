import { Link } from "@tanstack/react-router";

interface TrajectoryWorkbenchHeaderProps {
  activeTurnLabel: string;
  commandSnippet: string;
  isChineseUi: boolean;
  isOverviewRoute: boolean;
  onCopyCommand: () => void;
  onCopyLink: () => void;
}

export function TrajectoryWorkbenchHeader({
  activeTurnLabel,
  commandSnippet,
  isChineseUi,
  isOverviewRoute,
  onCopyCommand,
  onCopyLink,
}: TrajectoryWorkbenchHeaderProps) {
  const title = isOverviewRoute
    ? isChineseUi
      ? "Trajectory 运行总览"
      : "Trajectory operations overview"
    : isChineseUi
      ? "Trajectory 复盘台"
      : "Trajectory review workbench";
  const subtitle = isOverviewRoute
    ? isChineseUi
      ? "先判断当前范围里哪里失稳，再决定是否进入单条样本。"
      : "Read the slice health first, then decide whether a single-turn review is needed."
    : isChineseUi
      ? "从样本队列进入一条 case，顺着证据读完整个过程，再在右侧执行动作。"
      : "Enter from the sample queue, read the evidence in order, then act from the right rail.";

  return (
    <section className="fa-trajectory-workbench-header">
      <div className="fa-trajectory-workbench-header-copy">
        <p className="fa-trajectory-workbench-eyebrow">
          {isChineseUi ? "内部诊断" : "Internal diagnostics"}
        </p>
        <div className="fa-trajectory-workbench-heading">
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        <nav
          aria-label={isChineseUi ? "Observability 页面" : "Observability views"}
          className="fa-trajectory-workbench-tabs fa-observability-route-tabs"
        >
          <Link
            className={`fa-trajectory-workbench-tab fa-observability-route-tab ${isOverviewRoute ? "is-active" : ""}`.trim()}
            search
            to="/observability/overview"
          >
            <span>{isChineseUi ? "全局诊断" : "Global health"}</span>
            <strong>{isChineseUi ? "趋势 / 热点" : "Trends / hotspots"}</strong>
          </Link>
          <Link
            className={`fa-trajectory-workbench-tab fa-observability-route-tab ${isOverviewRoute ? "" : "is-active"}`.trim()}
            search
            to="/observability/trajectory"
          >
            <span>{isChineseUi ? "单条复盘" : "Single-turn review"}</span>
            <strong>{isChineseUi ? "样本 / 证据 / 动作" : "Samples / evidence / actions"}</strong>
          </Link>
        </nav>
      </div>

      <div className="fa-trajectory-workbench-header-side">
        <p className="fa-trajectory-workbench-focus-note">{activeTurnLabel}</p>
        <div className="fa-trajectory-workbench-header-actions">
          <button
            className="fa-chat-toolbar-button is-primary"
            onClick={onCopyLink}
            type="button"
          >
            {isChineseUi ? "复制当前链接" : "Copy link"}
          </button>
          {commandSnippet ? (
            <button
              className="fa-chat-toolbar-button"
              onClick={onCopyCommand}
              type="button"
            >
              {isChineseUi ? "复制 CLI 命令" : "Copy CLI command"}
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
