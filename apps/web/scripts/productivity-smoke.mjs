import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const appRoot = resolve(import.meta.dirname, "..");
const repoRoot = resolve(appRoot, "../..");
const reportPath = resolve(repoRoot, "reports/ui-smoke/productivity.json");

const files = {
  router: readFileSync(resolve(appRoot, "src/app/router.tsx"), "utf8"),
  shellConfig: readFileSync(resolve(appRoot, "src/app/shell/app-shell-config.ts"), "utf8"),
  shellGlobalNav: readFileSync(
    resolve(appRoot, "src/app/shell/app-shell-global-navigation.tsx"),
    "utf8",
  ),
  shellSidebar: readFileSync(
    resolve(appRoot, "src/app/shell/app-shell-workspace-sidebar.tsx"),
    "utf8",
  ),
  productivityPage: readFileSync(
    resolve(appRoot, "src/pages/productivity/productivity-page.tsx"),
    "utf8",
  ),
  appCss: readFileSync(resolve(appRoot, "src/shared/styles/app.css"), "utf8"),
  productivityCss: readFileSync(
    resolve(appRoot, "src/shared/styles/modules/productivity.css"),
    "utf8",
  ),
};

const expectations = [
  {
    name: "notes route is registered",
    pass: files.router.includes('path: "/productivity/notes"'),
  },
  {
    name: "tasks route is registered",
    pass: files.router.includes('path: "/productivity/tasks"'),
  },
  {
    name: "routes render productivity page modes",
    pass:
      files.router.includes('<ProductivityPage mode="notes" />') &&
      files.router.includes('<ProductivityPage mode="tasks" />'),
  },
  {
    name: "productivity participates in workspace shell",
    pass:
      files.shellConfig.includes("isProductivityPath") &&
      files.shellConfig.includes('pathname === "/productivity/notes"') &&
      files.shellConfig.includes('pathname === "/productivity/tasks"'),
  },
  {
    name: "global nav exposes productivity",
    pass:
      files.shellGlobalNav.includes("ProductivityIcon") &&
      files.shellGlobalNav.includes('to="/productivity/tasks"'),
  },
  {
    name: "workspace sidebar does not duplicate productivity tabs",
    pass:
      !files.shellSidebar.includes('to="/productivity/tasks"') &&
      !files.shellSidebar.includes('to="/productivity/notes"') &&
      files.productivityPage.includes('to="/productivity/tasks"') &&
      files.productivityPage.includes('to="/productivity/notes"'),
  },
  {
    name: "productivity page has dense notes and tasks surfaces",
    pass:
      files.productivityPage.includes("fa-productivity-note-list") &&
      files.productivityPage.includes("fa-productivity-task-list") &&
      files.productivityPage.includes("fa-productivity-source-filter") &&
      !files.productivityPage.includes("hero"),
  },
  {
    name: "productivity source view is wired",
    pass:
      files.productivityPage.includes("source_kind") &&
      files.productivityPage.includes("SourceAffordance") &&
      files.productivityPage.includes('to="/c/$conversationId/t/$threadId"'),
  },
  {
    name: "productivity styles are imported",
    pass:
      files.appCss.includes('@import "./modules/productivity.css";') &&
      files.productivityCss.includes(".fa-productivity-layout") &&
      files.productivityCss.includes(".fa-productivity-source-link"),
  },
];

const failed = expectations.filter((item) => !item.pass);
const report = {
  name: "productivity-ui-smoke",
  generated_at: new Date().toISOString(),
  status: failed.length ? "failed" : "passed",
  routes: ["/app/productivity/notes", "/app/productivity/tasks"],
  api_scaffold: {
    notes: "GET /v1/notes?source_kind=...",
    tasks: "GET /v1/tasks?source_kind=...",
    capture_note: "POST /v1/productivity/capture/note",
    capture_task: "POST /v1/productivity/capture/task",
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
  console.error(`\n${failed.length} productivity smoke expectation(s) failed.`);
  process.exit(1);
}
