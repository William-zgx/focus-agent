import { AgentTeamWorkbench } from "@/features/agent-team/agent-team-workbench";
import { useLastRouteParam } from "@/pages/use-last-route-param";

export function AgentTeamWorkbenchPage() {
  const sessionId = useLastRouteParam("sessionId");

  return <AgentTeamWorkbench sessionId={sessionId} />;
}
