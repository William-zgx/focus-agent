import type { FocusAgentConversationSummary } from "@focus-agent/web-sdk";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { type ChangeEvent, type FormEvent, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useConversationActions } from "@/features/conversations/use-conversation-actions";
import { useConversations } from "@/features/conversations/use-conversations";
import { tooltipProps } from "@/shared/ui/tooltip";

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

function totalConversationTokens(conversation?: FocusAgentConversationSummary) {
  const raw = Number(conversation?.token_usage?.total_tokens ?? 0);
  return Number.isFinite(raw) ? Math.max(0, Math.round(raw)) : 0;
}

export function ConversationToolbar() {
  const navigate = useNavigate();
  const { conversationId, threadId } = useRouterState({
    select: (state) => {
      const routeParams = (state.matches.at(-1)?.params ?? {}) as Partial<
        Record<"conversationId" | "threadId", string>
      >;

      return {
        conversationId: String(routeParams.conversationId ?? ""),
        threadId: String(routeParams.threadId ?? ""),
      };
    },
  });
  const { data, isLoading, error } = useConversations();
  const { createConversation, renameConversation, archiveConversation, activateConversation } =
    useConversationActions();
  const [isWorking, setIsWorking] = useState(false);
  const [renameTarget, setRenameTarget] = useState<FocusAgentConversationSummary | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const conversations = data?.conversations ?? [];
  const { isChineseUi, setShellStatus } = useShellUi();
  const activeConversations = conversations.filter((conversation) => !conversation.is_archived);

  const activeConversation = useMemo(
    () =>
      activeConversations.find((conversation) => conversation.root_thread_id === conversationId) ??
      activeConversations[0],
    [activeConversations, conversationId],
  );
  const activeConversationTotalTokens = totalConversationTokens(activeConversation);

  async function openConversation(rootThreadId: string) {
    await navigate({
      to: "/c/$conversationId/t/$threadId",
      params: {
        conversationId: rootThreadId,
        threadId: rootThreadId,
      },
    });
  }

  async function handleSelectChange(event: ChangeEvent<HTMLSelectElement>) {
    const nextConversationId = event.target.value;
    if (!nextConversationId) return;
    await openConversation(nextConversationId);
  }

  async function handleCreateConversation() {
    setIsWorking(true);
    try {
      setShellStatus(
        {
          tone: "warn",
          text: isChineseUi ? "正在创建对话" : "Creating conversation",
          display: "chat-floating",
        },
        { autoClearMs: 2200 },
      );
      const conversation = await createConversation();
      await openConversation(conversation.root_thread_id);
      setShellStatus(
        {
          tone: "success",
          text: isChineseUi ? "对话已创建" : "Conversation created",
          display: "chat-floating",
        },
        { autoClearMs: 2200 },
      );
    } finally {
      setIsWorking(false);
    }
  }

  function startRenameConversation(conversation: FocusAgentConversationSummary) {
    setRenameTarget(conversation);
    setRenameDraft(conversation.title);
  }

  function cancelRenameConversation() {
    setRenameTarget(null);
    setRenameDraft("");
  }

  async function handleRenameConversation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!renameTarget) return;
    const title = renameDraft.trim();
    if (!title || title === renameTarget.title) {
      cancelRenameConversation();
      return;
    }
    setIsWorking(true);
    try {
      setShellStatus(
        {
          tone: "warn",
          text: isChineseUi ? "正在重命名对话" : "Renaming conversation",
          display: "chat-floating",
        },
        { autoClearMs: 2200 },
      );
      await renameConversation(renameTarget.root_thread_id, title);
      setShellStatus(
        {
          tone: "success",
          text: isChineseUi ? "对话已重命名" : "Conversation renamed",
          display: "chat-floating",
        },
        { autoClearMs: 2200 },
      );
      cancelRenameConversation();
    } finally {
      setIsWorking(false);
    }
  }

  async function handleArchiveToggle(conversation: FocusAgentConversationSummary) {
    setIsWorking(true);
    try {
      if (conversation.is_archived) {
        setShellStatus(
          {
            tone: "warn",
            text: isChineseUi ? "正在恢复对话" : "Restoring conversation",
            display: "chat-floating",
          },
          { autoClearMs: 2200 },
        );
        await activateConversation(conversation.root_thread_id);
        setShellStatus(
          {
            tone: "success",
            text: isChineseUi ? "对话已恢复" : "Conversation restored",
            display: "chat-floating",
          },
          { autoClearMs: 2200 },
        );
      } else {
        setShellStatus(
          {
            tone: "warn",
            text: isChineseUi ? "正在归档对话" : "Archiving conversation",
            display: "chat-floating",
          },
          { autoClearMs: 2200 },
        );
        await archiveConversation(conversation.root_thread_id);
        const nextConversation = conversations.find(
          (item) =>
            item.root_thread_id !== conversation.root_thread_id && !item.is_archived,
        );

        if (nextConversation) {
          await openConversation(nextConversation.root_thread_id);
        } else if (threadId) {
          await navigate({ to: "/" });
        }
        setShellStatus(
          {
            tone: "success",
            text: isChineseUi ? "对话已归档" : "Conversation archived",
            display: "chat-floating",
          },
          { autoClearMs: 2200 },
        );
      }
    } finally {
      setIsWorking(false);
    }
  }

  async function handleRenameActiveConversation() {
    if (!activeConversation || isWorking) return;
    startRenameConversation(activeConversation);
  }

  return (
    <div className="fa-toolbar-cluster fa-conversation-toolbar">
      <label
        className="fa-conversation-switcher"
        {...tooltipProps(
          activeConversation
            ? isChineseUi
              ? "切换对话；双击当前名称可重命名"
              : "Switch conversations; double-click the current name to rename"
            : isChineseUi
              ? "切换或新建对话"
              : "Switch or create a conversation",
        )}
        onDoubleClick={() => void handleRenameActiveConversation()}
      >
        <span className="sr-only">{isChineseUi ? "对话" : "Conversation"}</span>
        <select
          aria-label={isChineseUi ? "对话" : "Conversation"}
          className="fa-conversation-select"
          disabled={isLoading || isWorking || activeConversations.length === 0}
          onChange={(event) => void handleSelectChange(event)}
          onDoubleClick={() => void handleRenameActiveConversation()}
          value={activeConversation?.root_thread_id ?? ""}
        >
          {isLoading ? <option value="">{isChineseUi ? "正在加载对话..." : "Loading conversations..."}</option> : null}
          {!isLoading && !activeConversation ? <option value="">{isChineseUi ? "暂无对话" : "No conversations"}</option> : null}
          {!isLoading
            ? activeConversations.map((conversation) => (
                <option key={conversation.root_thread_id} value={conversation.root_thread_id}>
                  {conversation.title}
                </option>
              ))
            : null}
        </select>
      </label>

      <div className="fa-conversation-toolbar-actions">
        {activeConversation ? (
          <button
            className="fa-conversation-token-trigger"
            {...tooltipProps(
              isChineseUi
                ? `对话累计消耗 ${formatTokenCount(activeConversationTotalTokens)} tokens`
                : `Conversation total ${formatTokenCount(activeConversationTotalTokens)} tokens`,
            )}
            aria-label={
              isChineseUi
                ? `对话累计消耗 ${formatTokenCount(activeConversationTotalTokens)} tokens`
                : `Conversation total ${formatTokenCount(activeConversationTotalTokens)} tokens`
            }
            type="button"
          >
            <span className="fa-toolbar-icon" aria-hidden="true">
              <svg viewBox="0 0 20 20">
                <rect x="4" y="11" width="2.6" height="5" rx="1.1" fill="currentColor" />
                <rect x="8.7" y="8" width="2.6" height="8" rx="1.1" fill="currentColor" />
                <rect x="13.4" y="5" width="2.6" height="11" rx="1.1" fill="currentColor" />
              </svg>
            </span>
          </button>
        ) : null}
        <button
          className="fa-chat-toolbar-button fa-conversation-icon-button"
          {...tooltipProps(
            activeConversation?.is_archived
              ? isChineseUi
                ? "激活对话"
                : "Activate conversation"
              : isChineseUi
                ? "归档对话"
                : "Archive conversation"
          )}
          disabled={isWorking || !activeConversation}
          onClick={() => activeConversation && void handleArchiveToggle(activeConversation)}
          type="button"
        >
          {activeConversation?.is_archived ? (
            <span className="fa-toolbar-icon" aria-hidden="true">
              <svg viewBox="0 0 20 20">
                <path
                  d="M5.5 10a4.5 4.5 0 1 0 1.4-3.2"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
                <path
                  d="M4 4.7v3.6h3.6"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          ) : (
            <span className="fa-toolbar-icon" aria-hidden="true">
              <svg viewBox="0 0 20 20">
                <path d="M3.5 4.5h13v3h-13z" fill="currentColor" />
                <path
                  d="M5.5 8.5h9v7h-9z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinejoin="round"
                />
                <path d="M8 11h4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
            </span>
          )}
        </button>
        <button
          className="fa-chat-toolbar-button is-primary"
          {...tooltipProps(isChineseUi ? "新建对话" : "New conversation")}
          disabled={isWorking}
          onClick={() => void handleCreateConversation()}
          type="button"
        >
          {isChineseUi ? "新建" : "New"}
        </button>
      </div>

      {error ? (
        <div className="fa-toolbar-note is-danger">
          {isChineseUi ? "加载对话失败。" : "Failed to load conversations."}
        </div>
      ) : null}
      {renameTarget ? (
        <form className="fa-inline-rename-form" onSubmit={(event) => void handleRenameConversation(event)}>
          <label className="sr-only" htmlFor="conversation-rename-input">
            {isChineseUi ? "重命名对话" : "Rename conversation"}
          </label>
          <input
            id="conversation-rename-input"
            className="fa-inline-rename-input"
            autoFocus
            value={renameDraft}
            onChange={(event) => setRenameDraft(event.target.value)}
            disabled={isWorking}
          />
          <button className="fa-branch-action-button is-primary" disabled={isWorking || !renameDraft.trim()} type="submit">
            {isChineseUi ? "保存" : "Save"}
          </button>
          <button
            className="fa-branch-action-button"
            disabled={isWorking}
            onClick={cancelRenameConversation}
            type="button"
          >
            {isChineseUi ? "取消" : "Cancel"}
          </button>
        </form>
      ) : null}
    </div>
  );
}
