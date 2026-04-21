import type { FocusAgentConversationSummary } from "@focus-agent/web-sdk";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { ChangeEvent, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useConversationActions } from "@/features/conversations/use-conversation-actions";
import { useConversations } from "@/features/conversations/use-conversations";
import { tooltipProps } from "@/shared/ui/tooltip";

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
  const conversations = data?.conversations ?? [];
  const { isChineseUi, setShellStatus } = useShellUi();
  const activeConversations = conversations.filter((conversation) => !conversation.is_archived);
  const archivedConversations = conversations.filter((conversation) => conversation.is_archived);

  const activeConversation = useMemo(
    () =>
      conversations.find((conversation) => conversation.root_thread_id === conversationId) ??
      conversations.find((conversation) => !conversation.is_archived) ??
      conversations[0],
    [conversationId, conversations],
  );

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
          text: isChineseUi ? "正在新建对话" : "creating conversation",
        },
        { autoClearMs: 2200 },
      );
      const conversation = await createConversation();
      await openConversation(conversation.root_thread_id);
      setShellStatus(
        {
          tone: "success",
          text: isChineseUi ? "对话已就绪" : "conversation ready",
        },
        { autoClearMs: 2200 },
      );
    } finally {
      setIsWorking(false);
    }
  }

  async function handleRenameConversation(conversation: FocusAgentConversationSummary) {
    const title = window.prompt(
      isChineseUi ? "重命名对话" : "Rename conversation",
      conversation.title,
    );
    if (!title || !title.trim()) return;
    setIsWorking(true);
    try {
      setShellStatus(
        {
          tone: "warn",
          text: isChineseUi ? "正在重命名对话" : "renaming conversation",
        },
        { autoClearMs: 2200 },
      );
      await renameConversation(conversation.root_thread_id, title.trim());
      setShellStatus(
        {
          tone: "success",
          text: isChineseUi ? "对话已就绪" : "conversation ready",
        },
        { autoClearMs: 2200 },
      );
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
            text: isChineseUi ? "正在恢复对话" : "activating conversation",
          },
          { autoClearMs: 2200 },
        );
        await activateConversation(conversation.root_thread_id);
        setShellStatus(
          {
            tone: "success",
            text: isChineseUi ? "对话已就绪" : "conversation ready",
          },
          { autoClearMs: 2200 },
        );
      } else {
        setShellStatus(
          {
            tone: "warn",
            text: isChineseUi ? "正在归档对话" : "archiving conversation",
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
            text: isChineseUi ? "对话已归档" : "conversation archived",
          },
          { autoClearMs: 2200 },
        );
      }
    } finally {
      setIsWorking(false);
    }
  }

  return (
    <div className="fa-toolbar-cluster">
      <label
        className="fa-conversation-switcher"
        {...tooltipProps(isChineseUi ? "切换或新建对话" : "Switch or create a conversation")}
      >
        <span className="sr-only">{isChineseUi ? "对话" : "Conversation"}</span>
        <select
          aria-label={isChineseUi ? "对话" : "Conversation"}
          className="fa-conversation-select"
          disabled={isLoading || isWorking || conversations.length === 0}
          onChange={(event) => void handleSelectChange(event)}
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
          {!isLoading && archivedConversations.length ? (
            <optgroup label={isChineseUi ? "已归档对话" : "Archived conversations"}>
              {archivedConversations.map((conversation) => (
                <option key={conversation.root_thread_id} value={conversation.root_thread_id}>
                  {conversation.title}
                </option>
              ))}
            </optgroup>
          ) : null}
        </select>
      </label>

      <button
        className="fa-chat-toolbar-button fa-conversation-icon-button"
        {...tooltipProps(isChineseUi ? "重命名对话" : "Rename conversation")}
        disabled={isWorking || !activeConversation}
        onClick={() => activeConversation && void handleRenameConversation(activeConversation)}
        type="button"
      >
        <span className="fa-toolbar-icon" aria-hidden="true">
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
      </button>
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

      {error ? (
        <div className="fa-toolbar-note is-danger">
          {isChineseUi ? "加载对话失败。" : "Failed to load conversations."}
        </div>
      ) : null}
    </div>
  );
}
