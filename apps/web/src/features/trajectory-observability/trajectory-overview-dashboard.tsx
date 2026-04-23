import { Link } from "@tanstack/react-router";

type OverviewMetric = {
  labelEn: string;
  labelZh: string;
  value: string;
};

type OverviewListItem = {
  id: string;
  meta: string;
  title: string;
  value: string;
};

interface TrajectoryOverviewDashboardProps {
  byModel: OverviewListItem[];
  byScene: OverviewListItem[];
  hottestTools: OverviewListItem[];
  isChineseUi: boolean;
  onSelectTool: (tool: string) => void;
  runtimeLabel: string;
  summaryMetrics: OverviewMetric[];
  toolFilter: string;
}

function EmptyState({ isChineseUi }: { isChineseUi: boolean }) {
  return (
    <div className="fa-observability-empty is-compact">
      {isChineseUi ? "当前范围还没有可展示的聚合数据。" : "No aggregates are available in this slice yet."}
    </div>
  );
}

export function TrajectoryOverviewDashboard({
  byModel,
  byScene,
  hottestTools,
  isChineseUi,
  onSelectTool,
  runtimeLabel,
  summaryMetrics,
  toolFilter,
}: TrajectoryOverviewDashboardProps) {
  return (
    <div className="fa-trajectory-overview-shell">
      <section className="fa-trajectory-overview-hero">
        <div className="fa-trajectory-overview-hero-copy">
          <p className="fa-trajectory-workbench-eyebrow">
            {isChineseUi ? "问题发现" : "Issue discovery"}
          </p>
          <h2>
            {isChineseUi
              ? "总览页只负责告诉你哪里值得进复盘台"
              : "The overview should only tell you what deserves a review session"}
          </h2>
          <p>
            {isChineseUi
              ? "保留健康、热点和分布，去掉复盘页才需要的重型模块。"
              : "Keep health, hotspots, and distribution. Leave heavy review tasks to the workbench."}
          </p>
        </div>
        <div className="fa-trajectory-overview-runtime">
          <span>{isChineseUi ? "运行态" : "Runtime"}</span>
          <strong>{runtimeLabel}</strong>
        </div>
      </section>

      <section className="fa-trajectory-overview-metrics">
        {summaryMetrics.map((metric) => (
          <article
            key={metric.labelEn}
            className="fa-trajectory-overview-metric-card"
          >
            <span>{isChineseUi ? metric.labelZh : metric.labelEn}</span>
            <strong>{metric.value}</strong>
          </article>
        ))}
      </section>

      <section className="fa-trajectory-overview-grid">
        <article className="fa-trajectory-overview-column">
          <div className="fa-trajectory-overview-section-head">
            <div>
              <p>{isChineseUi ? "场景压力" : "Scene pressure"}</p>
              <h3>{isChineseUi ? "问题最密集的场景" : "Where failures concentrate"}</h3>
            </div>
          </div>
          <div className="fa-trajectory-overview-list">
            {byScene.length ? (
              byScene.map((item) => (
                <div
                  key={item.id}
                  className="fa-trajectory-overview-list-item"
                >
                  <div>
                    <strong>{item.title}</strong>
                    <span>{item.meta}</span>
                  </div>
                  <em>{item.value}</em>
                </div>
              ))
            ) : (
              <EmptyState isChineseUi={isChineseUi} />
            )}
          </div>
        </article>

        <article className="fa-trajectory-overview-column">
          <div className="fa-trajectory-overview-section-head">
            <div>
              <p>{isChineseUi ? "模型分布" : "Model pressure"}</p>
              <h3>{isChineseUi ? "优先排查的模型切片" : "Model slices to inspect first"}</h3>
            </div>
          </div>
          <div className="fa-trajectory-overview-list">
            {byModel.length ? (
              byModel.map((item) => (
                <div
                  key={item.id}
                  className="fa-trajectory-overview-list-item"
                >
                  <div>
                    <strong>{item.title}</strong>
                    <span>{item.meta}</span>
                  </div>
                  <em>{item.value}</em>
                </div>
              ))
            ) : (
              <EmptyState isChineseUi={isChineseUi} />
            )}
          </div>
        </article>

        <article className="fa-trajectory-overview-column">
          <div className="fa-trajectory-overview-section-head">
            <div>
              <p>{isChineseUi ? "工具热点" : "Tool hotspots"}</p>
              <h3>{isChineseUi ? "直接进入复盘的入口" : "Fastest path into review"}</h3>
            </div>
          </div>
          <div className="fa-trajectory-overview-list">
            {hottestTools.length ? (
              hottestTools.map((item) => (
                <button
                  key={item.id}
                  className={`fa-trajectory-overview-list-item is-button ${toolFilter === item.id ? "is-active" : ""}`.trim()}
                  onClick={() => onSelectTool(item.id)}
                  type="button"
                >
                  <div>
                    <strong>{item.title}</strong>
                    <span>{item.meta}</span>
                  </div>
                  <em>{item.value}</em>
                </button>
              ))
            ) : (
              <EmptyState isChineseUi={isChineseUi} />
            )}
          </div>
        </article>
      </section>

      <section className="fa-trajectory-overview-handoff">
        <div>
          <p className="fa-trajectory-workbench-eyebrow">
            {isChineseUi ? "下一步" : "Next step"}
          </p>
          <h3>
            {isChineseUi
              ? "确认值得复盘的切片后，再进入单条样本。"
              : "Once a slice looks suspicious, move into the single-turn review."}
          </h3>
        </div>
        <Link
          className="fa-chat-toolbar-button is-primary"
          search
          to="/observability/trajectory"
        >
          {isChineseUi ? "进入复盘台" : "Open review workbench"}
        </Link>
      </section>
    </div>
  );
}
