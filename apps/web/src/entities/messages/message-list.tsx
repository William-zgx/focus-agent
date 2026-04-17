import type {
  FocusAgentToolCallEvent,
  FocusAgentToolEvent,
  TurnFailedPayload,
} from "@focus-agent/web-sdk";
import { createElement, Fragment, type ReactNode, useMemo, useState } from "react";

interface MessageListProps {
  isReadOnly?: boolean;
  messages: Array<Record<string, unknown>>;
  streamVisibleText?: string;
  streamReasoningText?: string;
  streamToolCalls?: FocusAgentToolCallEvent[];
  streamToolEvents?: FocusAgentToolEvent[];
  streamFailed?: TurnFailedPayload;
  isChineseUi?: boolean;
  onEditMessage?: (message: { id: string; content: string }) => void;
}

function roleLabel(type: unknown, isChineseUi = false) {
  const normalized = String(type || "").toLowerCase();
  if (normalized === "human") return isChineseUi ? "你" : "You";
  if (normalized === "ai") return "Focus Agent";
  if (normalized === "system") return isChineseUi ? "系统" : "System";
  return normalized || (isChineseUi ? "消息" : "Message");
}

function bubbleClass(type: unknown) {
  const normalized = String(type || "").toLowerCase();
  if (normalized === "human") {
    return "fa-message-bubble is-user";
  }
  if (normalized === "system") {
    return "fa-message-bubble is-system";
  }
  return "fa-message-bubble is-assistant";
}

function messageLayoutClass(type: unknown) {
  const normalized = String(type || "").toLowerCase();
  if (normalized === "human") {
    return "fa-message-row is-user user";
  }
  if (normalized === "system") {
    return "fa-message-row is-system system";
  }
  return "fa-message-row is-assistant assistant";
}

function roleClass(type: unknown) {
  const normalized = String(type || "").toLowerCase();
  if (normalized === "human") {
    return "fa-message-role fa-message-meta is-user";
  }
  if (normalized === "system") {
    return "fa-message-role fa-message-meta is-system";
  }
  return "fa-message-role fa-message-meta";
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

function inlineNodes(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`)|(\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null = pattern.exec(text);
  let nodeIndex = 0;

  while (match) {
    if (match.index > lastIndex) {
      nodes.push(
        <Fragment key={`${keyPrefix}-text-${nodeIndex}`}>
          {text.slice(lastIndex, match.index)}
        </Fragment>,
      );
      nodeIndex += 1;
    }

    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(
        <code key={`${keyPrefix}-code-${nodeIndex}`} className="fa-message-inline-code">
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        nodes.push(
          <a
            key={`${keyPrefix}-link-${nodeIndex}`}
            href={linkMatch[2]}
            rel="noreferrer"
            target="_blank"
          >
            {linkMatch[1]}
          </a>,
        );
      }
    }

    nodeIndex += 1;
    lastIndex = match.index + token.length;
    match = pattern.exec(text);
  }

  if (lastIndex < text.length) {
    nodes.push(<Fragment key={`${keyPrefix}-tail-${nodeIndex}`}>{text.slice(lastIndex)}</Fragment>);
  }

  return nodes;
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

function AgentRunBubble({
  reasoningText,
  toolCalls,
  toolEvents,
  isChineseUi,
}: {
  reasoningText?: string;
  toolCalls?: FocusAgentToolCallEvent[];
  toolEvents?: FocusAgentToolEvent[];
  isChineseUi: boolean;
}) {
  const tone = toolEventTone(toolEvents ?? []);
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

  if (steps.length === 0) {
    return null;
  }

  return (
    <div className="fa-message-row is-assistant assistant">
      <div className="fa-message-stack">
        <div className={`fa-agent-run-bubble is-${tone}`}>
          <div className="fa-agent-run-head">
            <div className={`fa-agent-run-pulse is-${tone}`} />
            <div className="fa-agent-run-copy">
              <div className="fa-agent-run-title">
                {isChineseUi ? "Agent 正在运行" : "Agent is working"}
              </div>
              <div className="fa-agent-run-detail">
                {isChineseUi
                  ? "思考、规划和工具调用会先显示在这里，正式回复生成后会自动切换。"
                  : "Thinking, planning, and tool activity appear here first, then switch to the final answer automatically."}
              </div>
            </div>
          </div>
          <div className="fa-agent-run-steps">
            {steps.map((step, index) => (
              <div key={`${step.label}-${index}`} className={`fa-agent-run-step is-${step.tone}`}>
                <span className="fa-agent-run-step-dot" />
                <span>{step.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function MessageList({
  isReadOnly = false,
  messages,
  streamVisibleText,
  streamReasoningText,
  streamToolCalls,
  streamToolEvents,
  streamFailed,
  isChineseUi = false,
  onEditMessage,
}: MessageListProps) {
  return (
    <div className="fa-message-list">
      {messages.map((message, index) => {
        const content = String(message.content ?? "");
        const messageId = String(message.id ?? `message-${index}`);
        const isHuman = String(message.type || "").toLowerCase() === "human";
        return (
          <div key={messageId} className={messageLayoutClass(message.type)}>
            <div className="fa-message-stack">
              <div className="fa-message-head">
                <div className={roleClass(message.type)}>{roleLabel(message.type, isChineseUi)}</div>
              </div>
              <div className={bubbleClass(message.type)}>
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
        isChineseUi={isChineseUi}
        reasoningText={streamReasoningText}
        toolCalls={streamToolCalls}
        toolEvents={streamToolEvents}
      />

      {streamReasoningText ? (
        <div className="fa-message-row is-assistant assistant">
          <div className="fa-message-stack">
            <div className="fa-message-head">
              <div className="fa-message-role fa-message-meta is-reasoning">
                {isChineseUi ? "思考" : "Reasoning"}
              </div>
            </div>
            <div className="fa-message-bubble is-reasoning">
              <div className="fa-message-content">
                <MessageMarkdown isChineseUi={isChineseUi} text={streamReasoningText} />
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {streamVisibleText ? (
        <div className="fa-message-row is-assistant assistant">
          <div className="fa-message-stack">
            <div className="fa-message-head">
              <div className="fa-message-role fa-message-meta is-streaming">
                {isChineseUi ? "输出中" : "Streaming"}
              </div>
            </div>
            <div className="fa-message-bubble is-streaming">
              <div className="fa-message-content">
                <MessageMarkdown isChineseUi={isChineseUi} text={streamVisibleText} />
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
