import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");

const files = {
  page: readFileSync(resolve(root, "src/pages/observability/trajectory-page.tsx"), "utf8"),
  trajectoryWorkbenchHeader: readFileSync(
    resolve(root, "src/features/trajectory-observability/trajectory-workbench-header.tsx"),
    "utf8",
  ),
  trajectoryWorkbenchState: readFileSync(
    resolve(root, "src/pages/observability/use-trajectory-workbench-state.ts"),
    "utf8",
  ),
  trajectoryPageActions: readFileSync(
    resolve(root, "src/pages/observability/use-trajectory-page-actions.ts"),
    "utf8",
  ),
  router: readFileSync(resolve(root, "src/app/router.tsx"), "utf8"),
  shell: readFileSync(resolve(root, "src/app/shell/app-shell.tsx"), "utf8"),
  shellRouteState: readFileSync(
    resolve(root, "src/app/shell/hooks/use-shell-route-state.ts"),
    "utf8",
  ),
  css: readFileSync(resolve(root, "src/shared/styles/app.css"), "utf8"),
  shellCss: readFileSync(resolve(root, "src/shared/styles/modules/shell.css"), "utf8"),
  overviewHook: readFileSync(
    resolve(root, "src/features/trajectory-observability/use-observability-overview.ts"),
    "utf8",
  ),
  sdkClient: readFileSync(resolve(root, "../../frontend-sdk/src/client.ts"), "utf8"),
};

const applyPresetStart = files.trajectoryWorkbenchState.indexOf(
  "function applyPreset(preset: PresetMode)",
);
const resetFiltersStart = files.trajectoryWorkbenchState.indexOf(
  "\n  function resetFilters",
  applyPresetStart,
);
const applyPresetBlock =
  applyPresetStart >= 0 && resetFiltersStart > applyPresetStart
    ? files.trajectoryWorkbenchState.slice(applyPresetStart, resetFiltersStart)
    : "";

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
    pass:
      files.shellRouteState.includes('pathname === "/observability/overview"') &&
      files.shellRouteState.includes('pathname === "/observability/trajectory"'),
  },
  {
    name: "request filter is initialized from query params",
    pass: files.trajectoryWorkbenchState.includes('readInitialSearchParam("request")'),
  },
  {
    name: "trace filter is initialized from query params",
    pass: files.trajectoryWorkbenchState.includes('readInitialSearchParam("trace")'),
  },
  {
    name: "request filter is wired into API filters",
    pass: files.trajectoryWorkbenchState.includes(
      "request_id: requestFilter.trim() || undefined",
    ),
  },
  {
    name: "trace filter is wired into API filters",
    pass: files.trajectoryWorkbenchState.includes("trace_id: traceFilter.trim() || undefined"),
  },
  {
    name: "all preset preserves scoped trajectory filters",
    pass:
      applyPresetBlock.includes("resetPresetFilters();") &&
      !/\bresetFilters\(\);/.test(applyPresetBlock),
  },
  {
    name: "production pivots are visible",
    pass:
      files.trajectoryPageActions.includes("Production pivots") &&
      files.trajectoryPageActions.includes("focusRequest"),
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
    pass:
      files.trajectoryWorkbenchHeader.includes("fa-observability-route-tabs") &&
      files.shellCss.includes(".fa-observability-route-tab"),
  },
  {
    name: "mobile layout collapses observability controls",
    pass:
      files.shellCss.includes("@media (max-width: 900px)") &&
      files.shellCss.includes(".fa-observability-route-tabs"),
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
