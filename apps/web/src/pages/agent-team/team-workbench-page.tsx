import { useRouterState } from "@tanstack/react-router";

import { AgentTeamWorkbench } from "@/features/agent-team/agent-team-workbench";

export function AgentTeamWorkbenchPage() {
  const sessionId = useRouterState({
    select: (state) => {
      const routeParams = (state.matches.at(-1)?.params ?? {}) as Partial<Record<"sessionId", string>>;
      return routeParams.sessionId ? String(routeParams.sessionId) : null;
    },
  });

  return <AgentTeamWorkbench sessionId={sessionId} />;
}
