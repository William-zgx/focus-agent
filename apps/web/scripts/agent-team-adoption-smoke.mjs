import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const appRoot = resolve(import.meta.dirname, "..");
const repoRoot = resolve(appRoot, "../..");
const reportPath = resolve(repoRoot, "reports/ui-smoke/agent-team-adoption.json");

function readCssModule(filePath, seen = new Set()) {
  if (seen.has(filePath)) return "";
  seen.add(filePath);
  const content = readFileSync(filePath, "utf8");
  const imports = Array.from(content.matchAll(/@import\s+["'](.+)["'];/g));
  return [
    content,
    ...imports.map((match) =>
      readCssModule(resolve(dirname(filePath), match[1]), seen),
    ),
  ].join("\n");
}

const files = {
  agentTeamWorkbench: readFileSync(
    resolve(appRoot, "src/features/agent-team/agent-team-workbench.tsx"),
    "utf8",
  ),
  adoption: readFileSync(
    resolve(appRoot, "src/features/agent-team/agent-team-workbench-adoption.tsx"),
    "utf8",
  ),
  useAgentTeam: readFileSync(
    resolve(appRoot, "src/features/agent-team/use-agent-team.ts"),
    "utf8",
  ),
  governancePage: readFileSync(
    resolve(appRoot, "src/pages/agents/agent-role-console-page.tsx"),
    "utf8",
  ),
  operationsPanels: readFileSync(
    resolve(appRoot, "src/pages/agents/agent-role-console-operations-panels.tsx"),
    "utf8",
  ),
  agentTeamCss: readCssModule(
    resolve(appRoot, "src/shared/styles/modules/agent-team.css"),
  ),
  baseCss: readCssModule(resolve(appRoot, "src/shared/styles/modules/base.css")),
};

const expectations = [
  {
    name: "agent team workbench renders adoption surface",
    pass:
      files.agentTeamWorkbench.includes("AgentTeamAdoptionWorkbench") &&
      files.adoption.includes('data-smoke="agent-team-adoption"'),
  },
  {
    name: "task selection and fake placeholder labels are present",
    pass:
      files.adoption.includes("selectedTaskIds") &&
      files.adoption.includes("placeholder") &&
      files.adoption.includes("fake"),
  },
  {
    name: "merge review API hooks cover lifecycle",
    pass:
      files.useAgentTeam.includes("useCreateAgentTeamMergeReview") &&
      files.useAgentTeam.includes("usePreviewAgentTeamMergeReview") &&
      files.useAgentTeam.includes("useApplyAgentTeamMergeReview") &&
      files.useAgentTeam.includes("useRejectAgentTeamMergeReview") &&
      files.useAgentTeam.includes("useCaptureAgentTeamMergeReview"),
  },
  {
    name: "context skill feedback governance panels are mounted",
    pass:
      files.governancePage.includes("OperationsGovernancePanels") &&
      files.operationsPanels.includes("Why this context?") &&
      files.operationsPanels.includes("Skill selection operations") &&
      files.operationsPanels.includes("Long-running feedback loop"),
  },
  {
    name: "dense workbench styles exist",
    pass:
      files.agentTeamCss.includes(".fa-agent-team-adoption-grid") &&
      files.agentTeamCss.includes(".fa-agent-team-adoption-task") &&
      files.baseCss.includes(".fa-agent-role-ops-metrics"),
  },
];

const failed = expectations.filter((item) => !item.pass);
const report = {
  name: "agent-team-adoption-ui-smoke",
  generated_at: new Date().toISOString(),
  status: failed.length ? "failed" : "passed",
  route: "/app/agent-team/:sessionId",
  api_scaffold: {
    create_review: "POST /v1/agent-team/sessions/{session_id}/merge-review",
    preview_review:
      "POST /v1/agent-team/sessions/{session_id}/merge-review/{review_id}/preview",
    apply_review:
      "POST /v1/agent-team/sessions/{session_id}/merge-review/{review_id}/apply",
    capture_review:
      "POST /v1/agent-team/sessions/{session_id}/merge-review/{review_id}/capture",
    context_evidence: "GET /v1/agent/context/evidence",
    skill_selections: "GET /v1/agent/skills/selections",
  },
  expectations,
};

mkdirSync(dirname(reportPath), { recursive: true });
writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);

for (const item of expectations) {
  console.log(`${item.pass ? "ok" : "not ok"} - ${item.name}`);
}
console.log(`report: ${reportPath}`);

if (failed.length) {
  console.error(`\n${failed.length} agent team adoption smoke expectation(s) failed.`);
  process.exit(1);
}
