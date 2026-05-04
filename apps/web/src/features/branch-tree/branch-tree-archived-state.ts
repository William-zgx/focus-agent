import { useEffect, useState } from "react";

export function useBranchTreeArchivedSections({
  archivedConversationsCount,
  archivedBranchesCount,
}: {
  archivedConversationsCount: number;
  archivedBranchesCount: number;
}) {
  const [archivedConversationsExpanded, setArchivedConversationsExpanded] =
    useState(archivedConversationsCount > 0);
  const [archivedBranchesExpanded, setArchivedBranchesExpanded] = useState(
    archivedBranchesCount > 0,
  );

  useEffect(() => {
    if (!archivedConversationsCount) {
      setArchivedConversationsExpanded(false);
      return;
    }
    setArchivedConversationsExpanded(
      (current) => current || archivedConversationsCount > 0,
    );
  }, [archivedConversationsCount]);

  useEffect(() => {
    if (!archivedBranchesCount) {
      setArchivedBranchesExpanded(false);
      return;
    }
    setArchivedBranchesExpanded((current) => current || archivedBranchesCount > 0);
  }, [archivedBranchesCount]);

  return {
    archivedConversationsExpanded,
    setArchivedConversationsExpanded,
    archivedBranchesExpanded,
    setArchivedBranchesExpanded,
  };
}
