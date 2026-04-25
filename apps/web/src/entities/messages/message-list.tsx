import type {
  FocusAgentToolCallEvent,
  FocusAgentToolEvent,
  TurnFailedPayload,
} from "@focus-agent/web-sdk";
import { looksLikeTextualToolCallArtifact } from "@focus-agent/web-sdk";
import { createElement, Fragment, type ReactNode, useMemo, useState } from "react";

interface MessageListProps {
  isReadOnly?: boolean;
  isStreaming?: boolean;
  messages: Array<Record<string, unknown>>;
  assistantMessage?: string | null;
  streamVisibleText?: string;
  streamReasoningText?: string;
  streamToolCalls?: FocusAgentToolCallEvent[];
  streamToolEvents?: FocusAgentToolEvent[];
  streamFailed?: TurnFailedPayload;
  isChineseUi?: boolean;
  onEditMessage?: (message: { id: string; content: string }) => void;
}

interface TranscriptDisplayMessage {
  kind: "message";
  id: string;
  type: string;
  content: string;
  totalTokens?: number;
}

interface ToolDetailEntry {
  id: string;
  label: string;
  content: string;
  language: string;
}

interface ToolActivityItem {
  kind: "tool-activity";
  id: string;
  toolNames: string[];
  summaryText: string;
  details: ToolDetailEntry[];
}

type TranscriptItem = TranscriptDisplayMessage | ToolActivityItem;

function normalizeMessageType(type: unknown) {
  return String(type || "").trim().toLowerCase();
}

function normalizeText(value: unknown) {
  return String(value ?? "").trim();
}

function looksLikeInternalToolMarkup(value: unknown) {
  return looksLikeTextualToolCallArtifact(normalizeText(value));
}

function looksLikeToolPlanningPayload(value: unknown) {
  const text = normalizeText(value);
  if (!text) {
    return false;
  }

  const lowered = text.toLowerCase();
  if (
    (lowered.includes('"steps"') || lowered.includes('"step"')) &&
    lowered.includes('"expected_tools"')
  ) {
    return true;
  }

  const parsed = parseJsonValue(text);
  if (!parsed || typeof parsed !== "object") {
    return false;
  }

  if (!("steps" in parsed) || !Array.isArray(parsed.steps)) {
    return false;
  }

  return parsed.steps.some((step) => {
    if (!step || typeof step !== "object") {
      return false;
    }
    const record = step as Record<string, unknown>;
    return Array.isArray(record.expected_tools) || typeof record.goal === "string";
  });
}

function shouldHideStreamingInternalContent(value: unknown) {
  return looksLikeInternalToolMarkup(value) || looksLikeToolPlanningPayload(value);
}

function roleLabel(type: unknown, isChineseUi = false) {
  const normalized = normalizeMessageType(type);
  if (normalized === "human") return isChineseUi ? "你" : "You";
  if (normalized === "ai") return "Focus Agent";
  if (normalized === "system") return isChineseUi ? "系统" : "System";
  return normalized || (isChineseUi ? "消息" : "Message");
}

function bubbleClass(type: unknown) {
  const normalized = normalizeMessageType(type);
  if (normalized === "human") {
    return "fa-message-bubble is-user";
  }
  if (normalized === "system") {
    return "fa-message-bubble is-system";
  }
  return "fa-message-bubble is-assistant";
}

function messageLayoutClass(type: unknown) {
  const normalized = normalizeMessageType(type);
  if (normalized === "human") {
    return "fa-message-row is-user user";
  }
  if (normalized === "system") {
    return "fa-message-row is-system system";
  }
  return "fa-message-row is-assistant assistant";
}

function roleClass(type: unknown) {
  const normalized = normalizeMessageType(type);
  if (normalized === "human") {
    return "fa-message-role fa-message-meta is-user";
  }
  if (normalized === "system") {
    return "fa-message-role fa-message-meta is-system";
  }
  return "fa-message-role fa-message-meta";
}

function totalTokensFromUsageMetadata(value: unknown) {
  if (!value || typeof value !== "object") {
    return 0;
  }
  const record = value as Record<string, unknown>;
  const total = Number(record.total_tokens ?? 0);
  if (Number.isFinite(total) && total > 0) {
    return Math.round(total);
  }
  const input = Number(record.input_tokens ?? 0);
  const output = Number(record.output_tokens ?? 0);
  const sum = (Number.isFinite(input) ? input : 0) + (Number.isFinite(output) ? output : 0);
  return sum > 0 ? Math.round(sum) : 0;
}

function formatTokenCount(value: number) {
  const normalized = Math.max(0, Number(value) || 0);
  if (normalized >= 1_000_000) {
    const millions = normalized / 1_000_000;
    return `${millions >= 10 ? millions.toFixed(0) : millions.toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (normalized >= 1_000) {
    const thousands = normalized / 1_000;
    return `${thousands >= 10 ? thousands.toFixed(0) : thousands.toFixed(1).replace(/\.0$/, "")}K`;
  }
  return new Intl.NumberFormat("en-US").format(Math.round(normalized));
}

function tokenUsageLabel(totalTokens: number, isChineseUi: boolean) {
  if (totalTokens <= 0) {
    return "";
  }
  return isChineseUi
    ? `本次回复 · ${formatTokenCount(totalTokens)} tokens`
    : `Reply · ${formatTokenCount(totalTokens)} tokens`;
}

function parseLineList(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function toolEventLabel(event: FocusAgentToolEvent, isChineseUi: boolean) {
  const toolName = String(event.data.tool_name || event.data.event || "tool").trim();
  switch (event.event) {
    case "tool.requested":
      return isChineseUi ? `准备调用 ${toolName}` : `Preparing ${toolName}`;
    case "tool.start":
      return isChineseUi ? `正在执行 ${toolName}` : `Running ${toolName}`;
    case "tool.result":
    case "tool.end":
      return isChineseUi ? `已完成 ${toolName}` : `Completed ${toolName}`;
    case "tool.error":
      return isChineseUi ? `${toolName} 执行失败` : `${toolName} failed`;
    case "tool.delta":
      return isChineseUi ? `${toolName} 返回中` : `${toolName} streaming`;
    default:
      return toolName;
  }
}

function toolEventTone(events: FocusAgentToolEvent[]) {
  if (events.some((event) => event.event === "tool.error")) {
    return "danger";
  }
  if (
    events.length > 0 &&
    events.every((event) => event.event === "tool.end" || event.event === "tool.result")
  ) {
    return "success";
  }
  return "warn";
}

function codeCopyLabel(isChineseUi: boolean, copied: boolean) {
  if (copied) {
    return isChineseUi ? "已复制" : "Copied";
  }
  return isChineseUi ? "复制代码" : "Copy code";
}

function messageCopyLabel(isChineseUi: boolean, copied: boolean) {
  if (copied) {
    return isChineseUi ? "已复制" : "Copied";
  }
  return isChineseUi ? "复制消息" : "Copy message";
}

function editMessageLabel(isChineseUi: boolean) {
  return isChineseUi ? "编辑并重发" : "Edit and resend";
}

function mergedBranchReadOnlyLabel(isChineseUi: boolean) {
  return isChineseUi ? "已合并分支不允许继续对话" : "Merged branches are read-only";
}

function failureText(failed: TurnFailedPayload, isChineseUi: boolean) {
  const message = String(failed.message || failed.error || "").trim();
  if (!message) {
    return isChineseUi ? "本轮执行失败。" : "This turn failed.";
  }
  return isChineseUi ? `本轮执行失败。\n\n${message}` : `This turn failed.\n\n${message}`;
}

function truncateText(text: string, maxLength = 220) {
  const normalized = normalizeText(text).replace(/\s+/g, " ");
  if (!normalized) {
    return "";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function parseJsonValue(text: string): unknown | null {
  const candidate = normalizeText(text);
  if (!candidate) {
    return null;
  }
  try {
    return JSON.parse(candidate);
  } catch {
    return null;
  }
}

function extractToolSummaryCandidate(value: unknown): string {
  if (typeof value === "string") {
    return normalizeText(value);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const candidate = extractToolSummaryCandidate(item);
      if (candidate) {
        return candidate;
      }
    }
    return "";
  }
  if (!value || typeof value !== "object") {
    return "";
  }

  const record = value as Record<string, unknown>;
  for (const key of ["answer", "summary", "message", "content", "result", "output", "text"]) {
    const candidate = extractToolSummaryCandidate(record[key]);
    if (candidate) {
      return candidate;
    }
  }

  const results = record.results;
  if (Array.isArray(results) && results.length > 0) {
    for (const item of results) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const resultRecord = item as Record<string, unknown>;
      const candidate =
        extractToolSummaryCandidate(resultRecord.content) ||
        extractToolSummaryCandidate(resultRecord.snippet) ||
        extractToolSummaryCandidate(resultRecord.title);
      if (candidate) {
        return candidate;
      }
    }
  }

  return "";
}

function summarizeToolResult(content: string) {
  const parsed = parseJsonValue(content);
  if (parsed !== null) {
    return truncateText(extractToolSummaryCandidate(parsed));
  }
  return truncateText(content);
}

function formatToolDetailContent(content: string) {
  const parsed = parseJsonValue(content);
  if (parsed !== null) {
    return {
      content: JSON.stringify(parsed, null, 2),
      language: "json",
    };
  }
  return {
    content: normalizeText(content),
    language: "text",
  };
}

function uniqueToolNames(toolNames: string[]) {
  return [...new Set(toolNames.map((item) => normalizeText(item)).filter(Boolean))];
}

function toolActivityTitle(toolNames: string[], isChineseUi: boolean) {
  if (toolNames.length === 0) {
    return isChineseUi ? "工具调用已完成" : "Tool activity completed";
  }
  if (toolNames.length === 1) {
    return isChineseUi ? `已调用 ${toolNames[0]}` : `Used ${toolNames[0]}`;
  }
  return isChineseUi ? `已调用 ${toolNames.length} 个工具` : `Used ${toolNames.length} tools`;
}

function toolActivityNote(toolNames: string[], isChineseUi: boolean) {
  if (toolNames.length > 1) {
    return toolNames.join(" · ");
  }
  return isChineseUi ? "结果已收集，可展开查看详情。" : "Results captured. Expand for details.";
}

function toolDetailsToggleLabel(isChineseUi: boolean, isOpen: boolean) {
  if (isOpen) {
    return isChineseUi ? "收起详情" : "Hide details";
  }
  return isChineseUi ? "查看详情" : "View details";
}

function toolSummaryLabel(isChineseUi: boolean) {
  return isChineseUi ? "结果摘要" : "Result summary";
}

function toolLabel(isChineseUi: boolean) {
  return isChineseUi ? "工具" : "Tool";
}

function processingStepsSummaryLabel(count: number, isChineseUi: boolean) {
  if (isChineseUi) {
    return `处理步骤（${count}）`;
  }
  return `Processing details (${count})`;
}

function processingStepsToggleHint(isChineseUi: boolean) {
  return isChineseUi ? "展开查看" : "Expand";
}

function buildTranscriptItems(
  messages: Array<Record<string, unknown>>,
  assistantMessage?: string | null,
): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  let pendingToolActivity: ToolActivityItem | null = null;

  function flushToolActivity() {
    if (!pendingToolActivity) {
      return;
    }
    pendingToolActivity.toolNames = uniqueToolNames(pendingToolActivity.toolNames);
    pendingToolActivity.summaryText = truncateText(pendingToolActivity.summaryText);
    items.push(pendingToolActivity);
    pendingToolActivity = null;
  }

  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index] ?? {};
    const type = normalizeMessageType(message.type);
    const content = String(message.content ?? "");
    const messageId = String(message.id ?? `${type || "message"}-${index}`);
    const toolCalls = Array.isArray(message.tool_calls)
      ? (message.tool_calls as Array<Record<string, unknown>>)
      : [];

    if (type === "ai" && toolCalls.length > 0) {
      flushToolActivity();
      pendingToolActivity = {
        kind: "tool-activity",
        id: `tool-activity-${messageId}`,
        toolNames: toolCalls
          .map((call) => normalizeText(call.name))
          .filter(Boolean),
        summaryText: "",
        details: [],
      };
      continue;
    }

    if (type === "tool") {
      if (!pendingToolActivity) {
        pendingToolActivity = {
          kind: "tool-activity",
          id: `tool-activity-${messageId}`,
          toolNames: [],
          summaryText: "",
          details: [],
        };
      }

      const toolName = normalizeText(message.name);
      if (toolName) {
        pendingToolActivity.toolNames.push(toolName);
      }
      if (!pendingToolActivity.summaryText) {
        pendingToolActivity.summaryText = summarizeToolResult(content);
      }
      const detail = formatToolDetailContent(content);
      if (detail.content) {
        pendingToolActivity.details.push({
          id: `${pendingToolActivity.id}-detail-${pendingToolActivity.details.length}`,
          label: toolName || `tool-${pendingToolActivity.details.length + 1}`,
          content: detail.content,
          language: detail.language,
        });
      }
      continue;
    }

    flushToolActivity();

    if (!normalizeText(content) || shouldHideStreamingInternalContent(content)) {
      continue;
    }

    items.push({
      kind: "message",
      id: messageId,
      type: type || "message",
      content,
      totalTokens: type === "ai" ? totalTokensFromUsageMetadata(message.usage_metadata) : 0,
    });
  }

  flushToolActivity();

  const normalizedAssistantMessage = normalizeText(assistantMessage);
  const shouldHideAssistantFallback = shouldHideStreamingInternalContent(normalizedAssistantMessage);
  const hasVisibleAssistantMessage = items.some(
    (item) =>
      item.kind === "message" &&
      normalizeMessageType(item.type) === "ai" &&
      normalizeText(item.content) === normalizedAssistantMessage,
  );

  if (normalizedAssistantMessage && !hasVisibleAssistantMessage && !shouldHideAssistantFallback) {
    items.push({
      kind: "message",
      id: "assistant-message-fallback",
      type: "ai",
      content: normalizedAssistantMessage,
      totalTokens: 0,
    });
    return items;
  }

  const lastItem = items.at(-1);
  if (lastItem?.kind === "tool-activity" && lastItem.summaryText) {
    items.push({
      kind: "message",
      id: `${lastItem.id}-summary`,
      type: "ai",
      content: lastItem.summaryText,
      totalTokens: 0,
    });
  }

  return items;
}

function inlineNodes(text: string, keyPrefix: string): ReactNode[] {
  function pushTextNode(nodes: ReactNode[], value: string, key: string) {
    if (!value) {
      return;
    }
    nodes.push(<Fragment key={key}>{value}</Fragment>);
  }

  function findClosingToken(value: string, token: string, startIndex: number) {
    let searchIndex = startIndex;
    while (searchIndex < value.length) {
      const matchIndex = value.indexOf(token, searchIndex);
      if (matchIndex === -1) {
        return -1;
      }
      if (matchIndex > startIndex) {
        return matchIndex;
      }
      searchIndex = matchIndex + token.length;
    }
    return -1;
  }

  const nodes: ReactNode[] = [];
  let buffer = "";
  let index = 0;
  let nodeIndex = 0;

  while (index < text.length) {
    if (text.startsWith("`", index)) {
      const closeIndex = text.indexOf("`", index + 1);
      if (closeIndex !== -1) {
        pushTextNode(nodes, buffer, `${keyPrefix}-text-${nodeIndex}`);
        buffer = "";
        nodes.push(
          <code key={`${keyPrefix}-code-${nodeIndex}`} className="fa-message-inline-code">
            {text.slice(index + 1, closeIndex)}
          </code>,
        );
        nodeIndex += 1;
        index = closeIndex + 1;
        continue;
      }
    }

    if (text.startsWith("[", index)) {
      const labelEnd = text.indexOf("]", index + 1);
      const urlStart = labelEnd === -1 ? -1 : text.indexOf("(", labelEnd);
      const urlEnd = urlStart === -1 ? -1 : text.indexOf(")", urlStart + 1);
      if (labelEnd !== -1 && urlStart === labelEnd + 1 && urlEnd !== -1) {
        pushTextNode(nodes, buffer, `${keyPrefix}-text-${nodeIndex}`);
        buffer = "";
        const label = text.slice(index + 1, labelEnd);
        const href = text.slice(urlStart + 1, urlEnd);
        nodes.push(
          <a
            key={`${keyPrefix}-link-${nodeIndex}`}
            href={href}
            rel="noreferrer"
            target="_blank"
          >
            {inlineNodes(label, `${keyPrefix}-link-label-${nodeIndex}`)}
          </a>,
        );
        nodeIndex += 1;
        index = urlEnd + 1;
        continue;
      }
    }

    const strongToken = text.startsWith("**", index)
      ? "**"
      : text.startsWith("__", index)
        ? "__"
        : "";
    if (strongToken) {
      const closeIndex = findClosingToken(text, strongToken, index + strongToken.length);
      if (closeIndex !== -1) {
        pushTextNode(nodes, buffer, `${keyPrefix}-text-${nodeIndex}`);
        buffer = "";
        const content = text.slice(index + strongToken.length, closeIndex);
        nodes.push(
          <strong key={`${keyPrefix}-strong-${nodeIndex}`}>
            {inlineNodes(content, `${keyPrefix}-strong-content-${nodeIndex}`)}
          </strong>,
        );
        nodeIndex += 1;
        index = closeIndex + strongToken.length;
        continue;
      }
    }

    const emphasisToken = text[index] === "*" || text[index] === "_" ? text[index] : "";
    if (emphasisToken) {
      const doubleToken = emphasisToken.repeat(2);
      if (!text.startsWith(doubleToken, index)) {
        const closeIndex = findClosingToken(text, emphasisToken, index + 1);
        if (closeIndex !== -1) {
          pushTextNode(nodes, buffer, `${keyPrefix}-text-${nodeIndex}`);
          buffer = "";
          const content = text.slice(index + 1, closeIndex);
          nodes.push(
            <em key={`${keyPrefix}-em-${nodeIndex}`}>
              {inlineNodes(content, `${keyPrefix}-em-content-${nodeIndex}`)}
            </em>,
          );
          nodeIndex += 1;
          index = closeIndex + 1;
          continue;
        }
      }
    }

    buffer += text[index];
    index += 1;
  }

  if (buffer) {
    pushTextNode(nodes, buffer, `${keyPrefix}-tail-${nodeIndex}`);
  }

  return nodes;
}

type MarkdownTableAlignment = "left" | "center" | "right" | null;

function parseMarkdownTableRow(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) {
    return null;
  }

  const normalized = trimmed.replace(/^\|/, "").replace(/\|$/, "");
  const cells = normalized.split("|").map((cell) => cell.trim());
  if (cells.length < 2 || cells.every((cell) => !cell)) {
    return null;
  }
  return cells;
}

function isMarkdownTableDelimiter(line: string) {
  const cells = parseMarkdownTableRow(line);
  return !!cells && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function parseMarkdownTableAlignments(line: string, columnCount: number): MarkdownTableAlignment[] {
  const cells = parseMarkdownTableRow(line) ?? [];
  return Array.from({ length: columnCount }, (_, index) => {
    const cell = cells[index] ?? "";
    if (cell.startsWith(":") && cell.endsWith(":")) {
      return "center";
    }
    if (cell.endsWith(":")) {
      return "right";
    }
    if (cell.startsWith(":")) {
      return "left";
    }
    return null;
  });
}

function normalizeMarkdownTableRow(row: string[], columnCount: number) {
  return Array.from({ length: columnCount }, (_, index) => row[index] ?? "");
}

function tableCellAlignmentClass(alignment: MarkdownTableAlignment) {
  if (alignment === "center") {
    return "is-align-center";
  }
  if (alignment === "right") {
    return "is-align-right";
  }
  return "";
}

function paragraphNode(text: string, key: string) {
  const lines = text.split("\n");
  return (
    <p key={key}>
      {lines.map((line, index) => (
        <Fragment key={`${key}-line-${index}`}>
          {inlineNodes(line, `${key}-inline-${index}`)}
          {index < lines.length - 1 ? <br /> : null}
        </Fragment>
      ))}
    </p>
  );
}

function renderMarkdownBlocks(text: string, isChineseUi: boolean) {
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index] ?? "";
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (trimmed.startsWith("```")) {
      const language = trimmed.slice(3).trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push(
        <CodeBlock
          key={`code-${blocks.length}`}
          code={codeLines.join("\n")}
          language={language}
          isChineseUi={isChineseUi}
        />,
      );
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      blocks.push(<hr key={`hr-${blocks.length}`} />);
      index += 1;
      continue;
    }

    const nextLine = lines[index + 1] ?? "";
    const tableHeader = parseMarkdownTableRow(line);
    if (tableHeader && isMarkdownTableDelimiter(nextLine)) {
      const columnCount = tableHeader.length;
      const alignments = parseMarkdownTableAlignments(nextLine, columnCount);
      const bodyRows: string[][] = [];
      index += 2;
      while (index < lines.length) {
        const rowLine = lines[index] ?? "";
        const rowTrimmed = rowLine.trim();
        const row = parseMarkdownTableRow(rowLine);
        if (!rowTrimmed || !row || isMarkdownTableDelimiter(rowTrimmed)) {
          break;
        }
        bodyRows.push(normalizeMarkdownTableRow(row, columnCount));
        index += 1;
      }
      blocks.push(
        <div key={`table-${blocks.length}`} className="fa-message-table-wrap">
          <table className="fa-message-table">
            <thead>
              <tr>
                {tableHeader.map((cell, cellIndex) => (
                  <th
                    key={`table-head-${blocks.length}-${cellIndex}`}
                    className={tableCellAlignmentClass(alignments[cellIndex] ?? null)}
                    scope="col"
                  >
                    {inlineNodes(cell, `table-head-${blocks.length}-${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            {bodyRows.length > 0 ? (
              <tbody>
                {bodyRows.map((row, rowIndex) => (
                  <tr key={`table-row-${blocks.length}-${rowIndex}`}>
                    {row.map((cell, cellIndex) => (
                      <td
                        key={`table-cell-${blocks.length}-${rowIndex}-${cellIndex}`}
                        className={tableCellAlignmentClass(alignments[cellIndex] ?? null)}
                      >
                        {inlineNodes(
                          cell,
                          `table-cell-${blocks.length}-${rowIndex}-${cellIndex}`,
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            ) : null}
          </table>
        </div>,
      );
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length, 6);
      blocks.push(
        createElement(
          `h${level}`,
          { key: `h-${blocks.length}` },
          inlineNodes(heading[2], `h-${blocks.length}`),
        ),
      );
      index += 1;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quoteLines: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(<blockquote key={`quote-${blocks.length}`}>{paragraphNode(quoteLines.join("\n"), `quote-p-${blocks.length}`)}</blockquote>);
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul key={`ul-${blocks.length}`}>
          {items.map((item, itemIndex) => (
            <li key={`ul-${blocks.length}-${itemIndex}`}>{inlineNodes(item, `ul-${blocks.length}-${itemIndex}`)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ol key={`ol-${blocks.length}`}>
          {items.map((item, itemIndex) => (
            <li key={`ol-${blocks.length}-${itemIndex}`}>{inlineNodes(item, `ol-${blocks.length}-${itemIndex}`)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length) {
      const paragraphLine = lines[index];
      const paragraphTrimmed = paragraphLine.trim();
      if (
        !paragraphTrimmed ||
        paragraphTrimmed.startsWith("```") ||
        /^---+$/.test(paragraphTrimmed) ||
        /^(#{1,6})\s+/.test(paragraphTrimmed) ||
        paragraphTrimmed.startsWith(">") ||
        /^[-*]\s+/.test(paragraphTrimmed) ||
        /^\d+\.\s+/.test(paragraphTrimmed)
      ) {
        break;
      }
      paragraphLines.push(paragraphLine);
      index += 1;
    }
    blocks.push(paragraphNode(paragraphLines.join("\n"), `p-${blocks.length}`));
  }

  return blocks;
}

function MessageMarkdown({
  text,
  isChineseUi,
}: {
  text: string;
  isChineseUi: boolean;
}) {
  return <div className="fa-message-markdown">{renderMarkdownBlocks(text, isChineseUi)}</div>;
}

function CopyButton({
  label,
  onCopy,
}: {
  label: string;
  onCopy: () => Promise<void> | void;
}) {
  return (
    <button className="fa-message-action-button" onClick={() => void onCopy()} type="button">
      <span className="fa-message-action-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20">
          <path
            d="M7 5.2A2.2 2.2 0 0 1 9.2 3h5.6A2.2 2.2 0 0 1 17 5.2v7.6a2.2 2.2 0 0 1-2.2 2.2H9.2A2.2 2.2 0 0 1 7 12.8V5.2Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          <path
            d="M5.2 7H5A2 2 0 0 0 3 9v6a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-.2"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
        </svg>
      </span>
      <span className="sr-only">{label}</span>
    </button>
  );
}

function EditButton({
  disabled = false,
  label,
  onEdit,
  title,
}: {
  disabled?: boolean;
  label: string;
  onEdit: () => void;
  title?: string;
}) {
  return (
    <button
      aria-label={title || label}
      className="fa-message-action-button"
      disabled={disabled}
      onClick={onEdit}
      title={title || label}
      type="button"
    >
      <span className="fa-message-action-icon" aria-hidden="true">
        <svg viewBox="0 0 20 20">
          <path
            d="M5.7 13.9 4.9 17l3.1-.8 7.1-7.1-2.3-2.3-7.1 7.1Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
          <path
            d="m11.9 5.8 2.3 2.3 1.4-1.4a1.6 1.6 0 0 0 0-2.3l-.1-.1a1.6 1.6 0 0 0-2.3 0l-1.3 1.5Z"
            fill="currentColor"
          />
        </svg>
      </span>
      <span className="sr-only">{title || label}</span>
    </button>
  );
}

function CodeBlock({
  code,
  language,
  isChineseUi,
}: {
  code: string;
  language: string;
  isChineseUi: boolean;
}) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div className="fa-message-code-block">
      <div className="fa-message-code-header">
        <span className="fa-message-code-label">{language || "text"}</span>
        <button className="fa-code-copy-button" onClick={() => void handleCopy()} type="button">
          {codeCopyLabel(isChineseUi, copied)}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

function MessageActions({
  content,
  isChineseUi,
  isReadOnly = false,
  onEdit,
}: {
  content: string;
  isChineseUi: boolean;
  isReadOnly?: boolean;
  onEdit?: (() => void) | null;
}) {
  const [copied, setCopied] = useState(false);
  const editTitle = isReadOnly ? mergedBranchReadOnlyLabel(isChineseUi) : editMessageLabel(isChineseUi);

  async function handleCopy() {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div className="fa-message-actions">
      <CopyButton
        label={messageCopyLabel(isChineseUi, copied)}
        onCopy={() => void handleCopy()}
      />
      {onEdit ? (
        <EditButton disabled={isReadOnly} label={editMessageLabel(isChineseUi)} onEdit={onEdit} title={editTitle} />
      ) : null}
    </div>
  );
}

function ToolActivityCard({
  activity,
  isChineseUi,
}: {
  activity: ToolActivityItem;
  isChineseUi: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="fa-message-row is-assistant assistant">
      <div className="fa-message-stack fa-tool-activity-stack">
        <details
          className="fa-tool-activity-card"
          onToggle={(event) =>
            setIsOpen((event.currentTarget as HTMLDetailsElement).open)
          }
        >
          <summary className="fa-tool-activity-summary">
            <span className="fa-tool-activity-badge">{toolLabel(isChineseUi)}</span>
            <span className="fa-tool-activity-copy">
              <span className="fa-tool-activity-title">
                {toolActivityTitle(activity.toolNames, isChineseUi)}
              </span>
              <span className="fa-tool-activity-note">
                {toolActivityNote(activity.toolNames, isChineseUi)}
              </span>
            </span>
            <span className="fa-tool-activity-toggle">
              {toolDetailsToggleLabel(isChineseUi, isOpen)}
            </span>
          </summary>

          <div className="fa-tool-activity-body">
            {activity.summaryText ? (
              <div className="fa-tool-activity-summary-block">
                <div className="fa-tool-activity-summary-label">{toolSummaryLabel(isChineseUi)}</div>
                <p>{activity.summaryText}</p>
              </div>
            ) : null}

            {activity.details.map((detail) => (
              <div key={detail.id} className="fa-tool-activity-detail">
                <div className="fa-tool-activity-detail-label">{detail.label}</div>
                <CodeBlock
                  code={detail.content}
                  isChineseUi={isChineseUi}
                  language={detail.language}
                />
              </div>
            ))}
          </div>
        </details>
      </div>
    </div>
  );
}

function AgentRunBubble({
  isStreaming,
  reasoningText,
  toolCalls,
  toolEvents,
  visibleText,
  isChineseUi,
}: {
  isStreaming: boolean;
  reasoningText?: string;
  toolCalls?: FocusAgentToolCallEvent[];
  toolEvents?: FocusAgentToolEvent[];
  visibleText?: string;
  isChineseUi: boolean;
}) {
  const hasVisibleText = Boolean(visibleText?.trim());
  const tone = toolEventTone(toolEvents ?? []);
  const hasReasoningText = Boolean(reasoningText?.trim());
  const hasToolActivity = Boolean((toolCalls?.length ?? 0) || (toolEvents?.length ?? 0));
  const stageTitle = hasToolActivity
    ? isChineseUi
      ? "正在处理请求"
      : "Processing the request"
    : hasReasoningText
      ? isChineseUi
        ? "正在思考"
        : "Thinking"
      : isChineseUi
        ? "已收到，正在思考"
        : "Message received, thinking";
  const stageDetail = hasToolActivity
    ? isChineseUi
      ? "工具步骤已经开始，默认折叠显示；展开后可以查看处理明细。"
      : "Tool steps are underway. They stay folded by default so the main reply remains calm."
    : hasReasoningText
      ? isChineseUi
        ? "Agent 正在整理上下文和回答结构，准备进入下一阶段。"
        : "The agent is organizing context and shaping the reply before moving on."
      : isChineseUi
        ? "消息已经发送成功，系统正在建立本轮响应。"
        : "Your message has been sent. The system is preparing this turn now.";
  const steps = useMemo(() => {
    const items: Array<{ label: string; tone: "warn" | "success" | "danger" }> = [];
    if (reasoningText?.trim()) {
      items.push({
        label: isChineseUi ? "正在整理推理链路" : "Reasoning in progress",
        tone: "warn",
      });
    }
    for (const call of toolCalls ?? []) {
      const toolName = String(call.data.name || "tool").trim();
      items.push({
        label: isChineseUi ? `规划调用 ${toolName}` : `Planning ${toolName}`,
        tone: "warn",
      });
    }
    for (const event of toolEvents ?? []) {
      items.push({
        label: toolEventLabel(event, isChineseUi),
        tone:
          event.event === "tool.error"
            ? "danger"
            : event.event === "tool.end" || event.event === "tool.result"
              ? "success"
              : "warn",
      });
    }
    return items.slice(-5);
  }, [isChineseUi, reasoningText, toolCalls, toolEvents]);

  if (!isStreaming || hasVisibleText) {
    return null;
  }

  return (
    <div className="fa-message-row is-assistant assistant">
      <div className="fa-message-stack">
        <div className={`fa-agent-run-bubble is-${tone}`}>
          <div className="fa-agent-run-head">
            <div className={`fa-agent-run-pulse is-${tone}`} />
            <div className="fa-agent-run-copy">
              <div className="fa-agent-run-title">{stageTitle}</div>
              <div className="fa-agent-run-detail">{stageDetail}</div>
            </div>
          </div>
          {steps.length > 0 ? (
            <details className="fa-agent-run-steps-shell">
              <summary className="fa-agent-run-steps-summary">
                <span>{processingStepsSummaryLabel(steps.length, isChineseUi)}</span>
                <span className="fa-agent-run-steps-hint">
                  {processingStepsToggleHint(isChineseUi)}
                </span>
              </summary>
              <div className="fa-agent-run-steps">
                {steps.map((step, index) => (
                  <div
                    key={`${step.label}-${index}`}
                    className={`fa-agent-run-step is-${step.tone}`}
                  >
                    <span className="fa-agent-run-step-dot" />
                    <span>{step.label}</span>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function MessageList({
  isReadOnly = false,
  isStreaming = false,
  messages,
  assistantMessage,
  streamVisibleText,
  streamReasoningText,
  streamToolCalls,
  streamToolEvents,
  streamFailed,
  isChineseUi = false,
  onEditMessage,
}: MessageListProps) {
  const transcriptItems = useMemo(
    () => buildTranscriptItems(messages, assistantMessage),
    [assistantMessage, messages],
  );
  const visibleStreamReply = shouldHideStreamingInternalContent(streamVisibleText)
    ? ""
    : normalizeText(streamVisibleText)
      ? String(streamVisibleText)
      : "";

  return (
    <div className="fa-message-list">
      {transcriptItems.map((item) => {
        if (item.kind === "tool-activity") {
          return <ToolActivityCard key={item.id} activity={item} isChineseUi={isChineseUi} />;
        }

        const content = item.content;
        const messageId = item.id;
        const isHuman = normalizeMessageType(item.type) === "human";
        return (
          <div key={messageId} className={messageLayoutClass(item.type)}>
            <div className="fa-message-stack">
              <div className="fa-message-head">
                <div className={roleClass(item.type)}>{roleLabel(item.type, isChineseUi)}</div>
                {item.totalTokens ? (
                  <div className="fa-message-usage-meta">
                    {tokenUsageLabel(item.totalTokens, isChineseUi)}
                  </div>
                ) : null}
              </div>
              <div className={bubbleClass(item.type)}>
                <div className="fa-message-content">
                  <MessageMarkdown isChineseUi={isChineseUi} text={content} />
                </div>
              </div>
              <MessageActions
                content={content}
                isChineseUi={isChineseUi}
                isReadOnly={isReadOnly}
                onEdit={
                  isHuman && onEditMessage
                    ? () => onEditMessage({ id: messageId, content })
                    : null
                }
              />
            </div>
          </div>
        );
      })}

      <AgentRunBubble
        isStreaming={isStreaming}
        isChineseUi={isChineseUi}
        reasoningText={streamReasoningText}
        toolCalls={streamToolCalls}
        toolEvents={streamToolEvents}
        visibleText={visibleStreamReply}
      />

      {visibleStreamReply ? (
        <div className="fa-message-row is-assistant assistant">
          <div className="fa-message-stack">
            <div className="fa-message-head">
              <div className="fa-message-role fa-message-meta is-streaming">
                {isChineseUi ? "输出中" : "Streaming"}
              </div>
            </div>
            <div className="fa-message-bubble is-streaming">
              <div className="fa-message-content">
                <MessageMarkdown isChineseUi={isChineseUi} text={visibleStreamReply} />
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {streamFailed ? (
        <div className="fa-message-row is-system system">
          <div className="fa-message-stack">
            <div className="fa-message-head">
              <div className="fa-message-role fa-message-meta is-system">
                {isChineseUi ? "系统" : "System"}
              </div>
            </div>
            <div className="fa-message-bubble is-system">
              <div className="fa-message-content">
                <MessageMarkdown
                  isChineseUi={isChineseUi}
                  text={failureText(streamFailed, isChineseUi)}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
