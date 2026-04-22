import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");

const files = {
  page: readFileSync(resolve(root, "src/pages/observability/trajectory-page.tsx"), "utf8"),
  router: readFileSync(resolve(root, "src/app/router.tsx"), "utf8"),
  shell: readFileSync(resolve(root, "src/app/shell/app-shell.tsx"), "utf8"),
  css: readFileSync(resolve(root, "src/shared/styles/app.css"), "utf8"),
  overviewHook: readFileSync(
    resolve(root, "src/features/trajectory-observability/use-observability-overview.ts"),
    "utf8",
  ),
  sdkClient: readFileSync(resolve(root, "../../frontend-sdk/src/client.ts"), "utf8"),
};

const expectations = [
  {
    name: "overview route is registered",
    pass: files.router.includes('path: "/observability/overview"'),
  },
  {
    name: "trajectory route is registered",
    pass: files.router.includes('path: "/observability/trajectory"'),
  },
  {
    name: "diagnostics shell covers all observability routes",
    pass: files.shell.includes('includes("/observability/")'),
  },
  {
    name: "request filter is wired into query params and API filters",
    pass:
      files.page.includes('readInitialSearchParam("request")') &&
      files.page.includes("request_id: requestFilter.trim() || undefined"),
  },
  {
    name: "trace filter is wired into query params and API filters",
    pass:
      files.page.includes('readInitialSearchParam("trace")') &&
      files.page.includes("trace_id: traceFilter.trim() || undefined"),
  },
  {
    name: "production pivots are visible",
    pass: files.page.includes("Production pivots") && files.page.includes("focusRequest"),
  },
  {
    name: "overview page consumes the observability overview endpoint",
    pass:
      files.page.includes("useObservabilityOverview") &&
      files.overviewHook.includes("getObservabilityOverview") &&
      files.sdkClient.includes("async getObservabilityOverview"),
  },
  {
    name: "route tabs are styled for overview/workbench switching",
    pass: files.page.includes("fa-observability-route-tabs") && files.css.includes(".fa-observability-route-tab"),
  },
  {
    name: "mobile layout collapses observability controls",
    pass:
      files.css.includes("@media (max-width: 900px)") &&
      files.css.includes(".fa-observability-route-tabs"),
  },
];

const failed = expectations.filter((item) => !item.pass);

for (const item of expectations) {
  console.log(`${item.pass ? "ok" : "not ok"} - ${item.name}`);
}

if (failed.length) {
  console.error(`\n${failed.length} observability smoke expectation(s) failed.`);
  process.exit(1);
}
