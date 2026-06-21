#!/usr/bin/env node
import { execFileSync, spawnSync } from "node:child_process";
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

function biomeDependencyFile(packageName, relativePath) {
  const biomePackageJson = packageFile("@biomejs/biome", "package.json");
  if (!biomePackageJson) {
    return null;
  }
  const biomeRequire = createRequire(biomePackageJson);
  try {
    return join(dirname(biomeRequire.resolve(`${packageName}/package.json`)), relativePath);
  } catch {
    return null;
  }
}

function glibcVersion() {
  let output = "";
  try {
    output = execFileSync("ldd", ["--version"], {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    output = String(error.stderr ?? error.stdout ?? "");
  }
  if (output.toLowerCase().includes("musl")) {
    return null;
  }
  const match = output.match(/(?:GLIBC|GNU libc\))\s*(\d+)\.(\d+)/i);
  if (!match) {
    return null;
  }
  return { major: Number(match[1]), minor: Number(match[2]) };
}

function needsMuslBiomeBinary() {
  if (process.platform !== "linux" || process.arch !== "x64") {
    return false;
  }
  const version = glibcVersion();
  if (!version) {
    return false;
  }
  return version.major < 2 || (version.major === 2 && version.minor < 29);
}

const biomeBinary = packageFile("@biomejs/biome", "bin/biome");

if (!biomeBinary) {
  console.error("Unable to locate a Biome CLI binary. Run pnpm install first.");
  process.exit(1);
}

const env = { ...process.env };
const muslBiomeBinary = needsMuslBiomeBinary()
  ? (packageFile("@biomejs/cli-linux-x64-musl", "biome") ??
    biomeDependencyFile("@biomejs/cli-linux-x64-musl", "biome"))
  : null;

if (muslBiomeBinary && !env.BIOME_BINARY) {
  env.BIOME_BINARY = muslBiomeBinary;
}

const result = spawnSync(biomeBinary, process.argv.slice(2), {
  env,
  stdio: "inherit",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
