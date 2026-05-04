import { useEffect, useRef, useState } from "react";

interface ComposerEditDraft {
  id: string;
  content: string;
}

export function useMessageComposerDraft({
  editDraft,
  isReadOnly,
  onEditDraftLoaded,
  onPreviewContextUsage,
}: {
  editDraft?: ComposerEditDraft | null;
  isReadOnly: boolean;
  onEditDraftLoaded?: () => void;
  onPreviewContextUsage?: (draftMessage: string) => void;
}) {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const editSignatureRef = useRef<string>("");
  const contextPreviewTimerRef = useRef<number | null>(null);

  function autoResizeComposer() {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "34px";
    const nextHeight = Math.max(34, Math.min(textarea.scrollHeight, 136));
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > 136 ? "auto" : "hidden";
  }

  useEffect(() => {
    autoResizeComposer();
  }, [message]);

  useEffect(() => {
    if (!onPreviewContextUsage || isReadOnly) return;
    if (contextPreviewTimerRef.current !== null) {
      window.clearTimeout(contextPreviewTimerRef.current);
    }
    contextPreviewTimerRef.current = window.setTimeout(() => {
      onPreviewContextUsage(message);
      contextPreviewTimerRef.current = null;
    }, 500);
    return () => {
      if (contextPreviewTimerRef.current !== null) {
        window.clearTimeout(contextPreviewTimerRef.current);
        contextPreviewTimerRef.current = null;
      }
    };
  }, [isReadOnly, message, onPreviewContextUsage]);

  useEffect(() => {
    if (!editDraft) return;
    const signature = `${editDraft.id}:${editDraft.content}`;
    if (editSignatureRef.current === signature) return;
    editSignatureRef.current = signature;
    setMessage(editDraft.content);
    onEditDraftLoaded?.();
    window.requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(editDraft.content.length, editDraft.content.length);
    });
  }, [editDraft, onEditDraftLoaded]);

  function resetEditDraftSignature() {
    editSignatureRef.current = "";
  }

  return {
    message,
    resetEditDraftSignature,
    setMessage,
    textareaRef,
  };
}
