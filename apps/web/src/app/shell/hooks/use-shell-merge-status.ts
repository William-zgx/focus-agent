import { useEffect, useRef, useState } from "react";

import type { MergeProposalGenerationState } from "@/app/shell/shell-ui-context";

type MergeProposalRecord = Record<string, MergeProposalGenerationState>;

export function useShellMergeProposalState() {
  const [mergeProposalGeneration, setMergeProposalGeneration] = useState<MergeProposalRecord>({});
  const mergeProposalStatusTimersRef = useRef<Record<string, number>>({});

  useEffect(() => {
    return () => {
      for (const timer of Object.values(mergeProposalStatusTimersRef.current)) {
        window.clearTimeout(timer);
      }
      mergeProposalStatusTimersRef.current = {};
    };
  }, []);

  function markMergeProposalPreparing(targetThreadId: string) {
    if (!targetThreadId) return;
    const existingTimer = mergeProposalStatusTimersRef.current[targetThreadId];
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer);
      delete mergeProposalStatusTimersRef.current[targetThreadId];
    }
    setMergeProposalGeneration((current) => ({
      ...current,
      [targetThreadId]: { status: "preparing", showFloating: true },
    }));
  }

  function markMergeProposalReady(targetThreadId: string) {
    if (!targetThreadId) return;
    const existingTimer = mergeProposalStatusTimersRef.current[targetThreadId];
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer);
    }
    setMergeProposalGeneration((current) => ({
      ...current,
      [targetThreadId]: { status: "ready", showFloating: true },
    }));
    mergeProposalStatusTimersRef.current[targetThreadId] = window.setTimeout(() => {
      setMergeProposalGeneration((current) => {
        if (!current[targetThreadId] || current[targetThreadId].status !== "ready") {
          return current;
        }
        const next = { ...current };
        delete next[targetThreadId];
        return next;
      });
      delete mergeProposalStatusTimersRef.current[targetThreadId];
    }, 2600);
  }

  function markMergeProposalFailed(targetThreadId: string, error: string) {
    if (!targetThreadId) return;
    const existingTimer = mergeProposalStatusTimersRef.current[targetThreadId];
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer);
      delete mergeProposalStatusTimersRef.current[targetThreadId];
    }
    setMergeProposalGeneration((current) => ({
      ...current,
      [targetThreadId]: { status: "failed", error, showFloating: true },
    }));
    mergeProposalStatusTimersRef.current[targetThreadId] = window.setTimeout(() => {
      setMergeProposalGeneration((current) => {
        const existing = current[targetThreadId];
        if (!existing || existing.status !== "failed" || !existing.showFloating) {
          return current;
        }
        return {
          ...current,
          [targetThreadId]: { ...existing, showFloating: false },
        };
      });
      delete mergeProposalStatusTimersRef.current[targetThreadId];
    }, 2600);
  }

  function isMergeProposalPreparing(targetThreadId: string) {
    return mergeProposalGeneration[targetThreadId]?.status === "preparing";
  }

  function getMergeProposalError(targetThreadId: string) {
    return mergeProposalGeneration[targetThreadId]?.error ?? null;
  }

  return {
    mergeProposalGeneration,
    markMergeProposalPreparing,
    markMergeProposalReady,
    markMergeProposalFailed,
    isMergeProposalPreparing,
    getMergeProposalError,
  };
}
