import { FocusAgentClient } from "../src/index";

async function main() {
  const client = new FocusAgentClient({
    baseUrl: "http://127.0.0.1:8000",
  });

  const token = await client.createDemoToken({
    user_id: "researcher-1",
    tenant_id: "demo-tenant",
  });
  client.setToken(token.access_token);

  const stream = await client.streamTurn({
    thread_id: "main-1",
    message: "Explore two approaches and show your best answer.",
  });

  const finalState = await client.collectStream(stream, {
    onVisibleTextDelta(event) {
      process.stdout.write(event.data.delta);
    },
    onToolEvent(event) {
      console.log("\n[tool]", event.event, event.data.tool_name ?? event.data.name ?? "unknown");
    },
  });

  console.log("\n--- final ---\n", finalState.latestTurnState);
}

void main();
