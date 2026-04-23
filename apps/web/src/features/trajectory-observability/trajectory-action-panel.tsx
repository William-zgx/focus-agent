import {
  type FocusAgentTrajectoryPromotionResponse,
  type FocusAgentTrajectoryReplayResponse,
  type FocusAgentTrajectoryTurnDetail,
} from "@focus-agent/web-sdk";
import { useEffect, useState } from "react";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

interface TrajectoryActionPanelProps {
  isChineseUi: boolean;
  selected: FocusAgentTrajectoryTurnDetail | null;
}

function downloadTextArtifact(name: string, body: string, mime: string) {
  const blob = new Blob([body], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function copyText(value: string) {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    // ignore clipboard failures
  }
}

function formatDuration(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

function formatSignedDelta(next: number, previous: number, unit = "") {
  const delta = next - previous;
  const prefix = delta > 0 ? "+" : "";
  return `${prefix}${delta.toFixed(1)}${unit}`;
}

export function TrajectoryActionPanel({
  isChineseUi,
  selected,
}: TrajectoryActionPanelProps) {
  const { client } = useFocusAgent();
  const [caseIdPrefix, setCaseIdPrefix] = useState("traj");
  const [copyToolTrajectory, setCopyToolTrajectory] = useState(true);
  const [copyAnswerSubstring, setCopyAnswerSubstring] = useState(false);
  const [answerSubstringChars, setAnswerSubstringChars] = useState("160");
  const [runningAction, setRunningAction] = useState<"replay" | "promote" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replayResult, setReplayResult] = useState<FocusAgentTrajectoryReplayResponse | null>(null);
  const [promotionResult, setPromotionResult] = useState<FocusAgentTrajectoryPromotionResponse | null>(null);
  const [expandedReplayDetails, setExpandedReplayDetails] = useState(false);
  const [expandedPromotionDetails, setExpandedPromotionDetails] = useState(false);

  useEffect(() => {
    setReplayResult(null);
    setPromotionResult(null);
    setError(null);
    setExpandedReplayDetails(false);
    setExpandedPromotionDetails(false);
  }, [selected?.id]);

  async function handleReplay() {
    if (!selected) return;
    setRunningAction("replay");
    setError(null);
    try {
      const result = await client.replayTrajectoryTurn(selected.id, {
        case_id_prefix: caseIdPrefix,
        copy_tool_trajectory: copyToolTrajectory,
        copy_answer_substring: copyAnswerSubstring,
        answer_substring_chars: Number(answerSubstringChars || 0),
      });
      setReplayResult(result);
      setExpandedReplayDetails(false);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to replay trajectory turn.");
    } finally {
      setRunningAction(null);
    }
  }

  async function handlePromote() {
    if (!selected) return;
    setRunningAction("promote");
    setError(null);
    try {
      const result = await client.promoteTrajectoryTurn(selected.id, {
        case_id_prefix: caseIdPrefix,
        copy_tool_trajectory: copyToolTrajectory,
        copy_answer_substring: copyAnswerSubstring,
        answer_substring_chars: Number(answerSubstringChars || 0),
      });
      setPromotionResult(result);
      setExpandedPromotionDetails(false);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to promote trajectory turn.");
    } finally {
      setRunningAction(null);
    }
  }

  if (!selected) {
    return (
      <div className="fa-observability-detail-block fa-trajectory-workbench-action-panel">
        <h3>{isChineseUi ? "复盘动作" : "Replay actions"}</h3>
        <div className="fa-observability-empty">
          {isChineseUi
            ? "选择一条 turn 后，这里可以直接执行 replay 或生成 dataset skeleton。"
            : "Select a turn to run replay or generate a dataset skeleton."}
        </div>
      </div>
    );
  }

  return (
    <div className="fa-observability-detail-block fa-trajectory-workbench-action-panel">
      <h3>{isChineseUi ? "复盘动作" : "Replay actions"}</h3>

      <p>
        {isChineseUi
          ? "从当前样本直接回放，或把它沉淀成可复制、可下载的评测样本。"
          : "Replay the selected turn directly, or turn it into a reusable evaluation sample."}
      </p>

      <div className="fa-observability-action-grid">
        <label className="fa-observability-action-option">
          <span>{isChineseUi ? "Case 前缀" : "Case prefix"}</span>
          <input onChange={(event) => setCaseIdPrefix(event.target.value)} placeholder="traj" value={caseIdPrefix} />
        </label>
        <label className="fa-observability-action-option">
          <span>{isChineseUi ? "答案锚点长度" : "Answer anchor chars"}</span>
          <input
            inputMode="numeric"
            onChange={(event) => setAnswerSubstringChars(event.target.value)}
            placeholder="160"
            value={answerSubstringChars}
          />
        </label>
      </div>

      <div className="fa-observability-action-toggles">
        <label className="fa-observability-action-toggle">
          <input checked={copyToolTrajectory} onChange={(event) => setCopyToolTrajectory(event.target.checked)} type="checkbox" />
          <span>{isChineseUi ? "拷贝工具轨迹约束" : "Copy tool-path expectations"}</span>
        </label>
        <label className="fa-observability-action-toggle">
          <input checked={copyAnswerSubstring} onChange={(event) => setCopyAnswerSubstring(event.target.checked)} type="checkbox" />
          <span>{isChineseUi ? "拷贝答案片段锚点" : "Copy answer substring anchor"}</span>
        </label>
      </div>

      <div className="fa-observability-command-bar">
        <button className="fa-chat-toolbar-button is-primary" disabled={runningAction !== null} onClick={() => void handleReplay()} type="button">
          {runningAction === "replay"
            ? isChineseUi
              ? "Replay 中..."
              : "Replaying..."
            : isChineseUi
              ? "执行 Replay"
              : "Run replay"}
        </button>
        <button className="fa-chat-toolbar-button" disabled={runningAction !== null} onClick={() => void handlePromote()} type="button">
          {runningAction === "promote"
            ? isChineseUi
              ? "生成中..."
              : "Promoting..."
            : isChineseUi
              ? "生成评测样本"
              : "Generate eval sample"}
        </button>
      </div>

      {error ? <div className="fa-inline-notice is-danger">{error}</div> : null}

      {replayResult ? (
        <div className="fa-observability-action-console">
          <div className={`fa-inline-notice ${replayResult.replay_result.passed ? "is-success" : "is-danger"}`.trim()}>
            {replayResult.replay_result.passed
              ? isChineseUi
                ? "Replay 已完成，结果通过。"
                : "Replay completed successfully."
              : isChineseUi
                ? "Replay 已完成，但结果未通过。"
                : "Replay completed, but the case did not pass."}
          </div>
          <div className="fa-observability-action-summary">
            <div>
              <span>{isChineseUi ? "Case ID" : "Case ID"}</span>
              <strong>{replayResult.replay_case.id}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "回放模型" : "Replay model"}</span>
              <strong>{replayResult.model_used}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "回放延迟" : "Replay latency"}</span>
              <strong>{formatDuration(Number(replayResult.replay_result.metrics?.latency_ms ?? 0))}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "路径是否变化" : "Tool path changed"}</span>
              <strong>{String(replayResult.comparison.tool_path_changed)}</strong>
            </div>
          </div>
          <details
            className="fa-observability-action-disclosure"
            open={expandedReplayDetails}
            onToggle={(event) => setExpandedReplayDetails((event.currentTarget as HTMLDetailsElement).open)}
          >
            <summary>{isChineseUi ? "展开 Replay 详情" : "Show replay details"}</summary>
            <div className="fa-observability-action-console">
              <div className="fa-observability-command-bar">
                <button className="fa-chat-toolbar-button" onClick={() => void copyText(JSON.stringify(replayResult.replay_case, null, 2))} type="button">
                  {isChineseUi ? "复制 Replay Case" : "Copy replay case"}
                </button>
                <button className="fa-chat-toolbar-button" onClick={() => void copyText(replayResult.replay_case_jsonl)} type="button">
                  {isChineseUi ? "复制 Replay JSONL" : "Copy replay JSONL"}
                </button>
                <button className="fa-chat-toolbar-button" onClick={() => void copyText(JSON.stringify(replayResult.replay_result, null, 2))} type="button">
                  {isChineseUi ? "复制 Replay 结果" : "Copy replay result"}
                </button>
              </div>
              <div className="fa-observability-diff-grid">
                <div className="fa-observability-diff-card">
                  <span>{isChineseUi ? "工具路径变化" : "Tool path delta"}</span>
                  <strong>{replayResult.comparison.tool_path_changed ? (isChineseUi ? "已变化" : "Changed") : (isChineseUi ? "未变化" : "Unchanged")}</strong>
                  <div className="fa-observability-diff-paths">
                    <div>
                      <span>{isChineseUi ? "原始" : "Source"}</span>
                      <p>{replayResult.comparison.source_tools.join(" → ") || "—"}</p>
                    </div>
                    <div>
                      <span>{isChineseUi ? "回放" : "Replay"}</span>
                      <p>{replayResult.comparison.replay_tools.join(" → ") || "—"}</p>
                    </div>
                  </div>
                </div>
                <div className="fa-observability-diff-card">
                  <span>{isChineseUi ? "指标对比" : "Metric delta"}</span>
                  <strong>
                    {isChineseUi ? "延迟差值" : "Latency delta"}{" "}
                    {formatSignedDelta(
                      replayResult.comparison.replay_latency_ms,
                      replayResult.comparison.source_latency_ms,
                      "ms",
                    )}
                  </strong>
                  <div className="fa-observability-diff-metrics">
                    <div>
                      <span>{isChineseUi ? "Fallback" : "Fallback"}</span>
                      <p>{`${replayResult.comparison.source_fallback_uses} → ${replayResult.comparison.replay_fallback_uses}`}</p>
                    </div>
                    <div>
                      <span>{isChineseUi ? "Cache Hits" : "Cache hits"}</span>
                      <p>{`${replayResult.comparison.source_cache_hits} → ${replayResult.comparison.replay_cache_hits}`}</p>
                    </div>
                    <div>
                      <span>{isChineseUi ? "工具数" : "Tool calls"}</span>
                      <p>{`${replayResult.comparison.source_tool_calls} → ${replayResult.comparison.replay_tool_calls}`}</p>
                    </div>
                  </div>
                </div>
                <div className="fa-observability-diff-card">
                  <span>{isChineseUi ? "答案预览" : "Answer preview"}</span>
                  <strong>{isChineseUi ? "原始 / 回放" : "Source / replay"}</strong>
                  <div className="fa-observability-diff-previews">
                    <div>
                      <span>{isChineseUi ? "原始" : "Source"}</span>
                      <p>{replayResult.comparison.source_answer_preview || "—"}</p>
                    </div>
                    <div>
                      <span>{isChineseUi ? "回放" : "Replay"}</span>
                      <p>{replayResult.comparison.replay_answer_preview || "—"}</p>
                    </div>
                  </div>
                </div>
              </div>
              <div className="fa-observability-action-snippet">
                <span>{isChineseUi ? "Replay 结果" : "Replay result"}</span>
                <pre>{JSON.stringify(replayResult.replay_result, null, 2)}</pre>
              </div>
            </div>
          </details>
        </div>
      ) : null}

      {promotionResult ? (
        <div className="fa-observability-action-console">
          <div className="fa-inline-notice is-success">
          {isChineseUi ? "Promote skeleton 已生成。" : "Promotion skeleton generated."}
          </div>
          <div className="fa-observability-action-summary">
            <div>
              <span>{isChineseUi ? "Case ID" : "Case ID"}</span>
              <strong>{promotionResult.case_id}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "来源 Turn" : "Source turn"}</span>
              <strong>{promotionResult.source_turn_id}</strong>
            </div>
          </div>
          <details
            className="fa-observability-action-disclosure"
            open={expandedPromotionDetails}
            onToggle={(event) => setExpandedPromotionDetails((event.currentTarget as HTMLDetailsElement).open)}
          >
            <summary>{isChineseUi ? "展开 Promote 详情" : "Show promotion details"}</summary>
            <div className="fa-observability-action-console">
              <div className="fa-observability-command-bar">
                <button className="fa-chat-toolbar-button" onClick={() => void copyText(promotionResult.jsonl)} type="button">
                  {isChineseUi ? "复制 JSONL" : "Copy JSONL"}
                </button>
                <button
                  className="fa-chat-toolbar-button"
                  onClick={() => downloadTextArtifact(`${promotionResult.case_id}.jsonl`, `${promotionResult.jsonl}\n`, "application/x-ndjson")}
                  type="button"
                >
                  {isChineseUi ? "下载 JSONL" : "Download JSONL"}
                </button>
              </div>
              <div className="fa-observability-action-snippet">
                <span>{isChineseUi ? "Promote Skeleton" : "Promotion skeleton"}</span>
                <pre>{promotionResult.jsonl}</pre>
              </div>
            </div>
          </details>
        </div>
      ) : null}

      {!replayResult && !promotionResult && !error ? (
        <div className="fa-inline-notice">
          {isChineseUi
            ? "从当前选中的 trajectory turn 直接执行 replay，或生成一条可复制/下载的 promote JSONL。"
            : "Run replay directly from the selected trajectory turn, or generate a promotion JSONL you can copy or download."}
        </div>
      ) : null}
    </div>
  );
}
