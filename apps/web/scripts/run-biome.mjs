#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);

function packageFile(packageName, relativePath) {
  try {
    return join(dirname(require.resolve(`${packageName}/package.json`)), relativePath);
  } catch {
    return null;
  }
}

const candidates = [];

if (process.platform === "linux" && process.arch === "x64") {
  candidates.push(packageFile("@biomejs/cli-linux-x64-musl", "biome"));
}

candidates.push(packageFile("@biomejs/biome", "bin/biome"));

const biomeBinary = candidates.find(Boolean);

if (!biomeBinary) {
  console.error("Unable to locate a Biome CLI binary. Run pnpm install first.");
  process.exit(1);
}

const result = spawnSync(biomeBinary, process.argv.slice(2), {
  stdio: "inherit",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
