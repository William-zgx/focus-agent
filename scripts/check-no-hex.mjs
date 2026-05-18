#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const result = spawnSync(
	"node",
	[resolve(root, "apps/web/scripts/check-no-hex.mjs"), ...process.argv.slice(2)],
	{ stdio: "inherit" },
);
process.exit(result.status ?? 1);
