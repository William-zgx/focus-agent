import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const appRoot = resolve(import.meta.dirname, "..");
const defaultBaseUrl = "http://127.0.0.1:5173/app";
const defaultOutputDir = "reports/a11y-baseline";
const defaultRoutes = [
	"/",
	"/c/demo-conversation/t/demo-thread",
	"/agent-team",
	"/observability/overview",
	"/observability/trajectory",
];

function parseArgs(argv) {
	const config = {
		baseUrl: defaultBaseUrl,
		failOnViolations: false,
		loadDelayMs: 1200,
		outDir: defaultOutputDir,
		routes: defaultRoutes,
	};

	for (let index = 0; index < argv.length; index += 1) {
		const arg = argv[index];

		if (arg === "--") {
			continue;
		}

		if (arg === "--help" || arg === "-h") {
			printHelp();
			process.exit(0);
		}

		if (arg === "--fail-on-violations") {
			config.failOnViolations = true;
			continue;
		}

		if (arg === "--base-url") {
			config.baseUrl = readValue("--base-url", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--base-url=")) {
			config.baseUrl = readValue("--base-url", arg.slice("--base-url=".length));
			continue;
		}

		if (arg === "--out-dir") {
			config.outDir = readValue("--out-dir", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--out-dir=")) {
			config.outDir = readValue("--out-dir", arg.slice("--out-dir=".length));
			continue;
		}

		if (arg === "--routes") {
			config.routes = readList("--routes", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--routes=")) {
			config.routes = readList("--routes", arg.slice("--routes=".length));
			continue;
		}

		if (arg === "--load-delay-ms") {
			config.loadDelayMs = readNumber("--load-delay-ms", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--load-delay-ms=")) {
			config.loadDelayMs = readNumber(
				"--load-delay-ms",
				arg.slice("--load-delay-ms=".length),
			);
			continue;
		}

		throw new Error(`Unknown argument: ${arg}`);
	}

	return config;
}

function printHelp() {
	console.log(`Usage: node ./scripts/a11y-baseline.mjs [options]

Captures axe-core baseline reports through @axe-core/cli.

Options:
  --base-url <url>          App base URL. Default: ${defaultBaseUrl}
  --out-dir <path>          Output path relative to apps/web. Default: ${defaultOutputDir}
  --routes <routes>         Comma-separated app routes. Default: first-tier routes
  --load-delay-ms <ms>      Wait after page load before axe runs. Default: 1200
  --fail-on-violations      Exit non-zero when axe finds violations
  -h, --help                Show this help message`);
}

function readValue(name, value) {
	if (!value) {
		throw new Error(`${name} requires a value.`);
	}
	return value;
}

function readNumber(name, value) {
	const parsed = Number(value);
	if (!Number.isInteger(parsed) || parsed < 0) {
		throw new Error(`${name} must be a non-negative integer.`);
	}
	return parsed;
}

function readList(name, value) {
	const items = readValue(name, value)
		.split(",")
		.map((item) => item.trim())
		.filter(Boolean);
	if (!items.length) {
		throw new Error(`${name} must include at least one item.`);
	}
	return items;
}

function buildUrl(baseUrl, route) {
	const normalizedBase = baseUrl.replace(/\/$/, "");
	const normalizedRoute = route.startsWith("/") ? route : `/${route}`;
	return `${normalizedBase}${normalizedRoute}`;
}

function fileNameFor(route) {
	if (route === "/") return "home.json";
	return `${route
		.replace(/^\//, "")
		.replace(/[^a-zA-Z0-9]+/g, "-")
		.replace(/^-|-$/g, "")}.json`;
}

function runAxe({ config, outputDir, route }) {
	const url = buildUrl(config.baseUrl, route);
	const outputFile = fileNameFor(route);
	const args = [
		"dlx",
		"@axe-core/cli",
		url,
		"--browser",
		"chrome",
		"--load-delay",
		String(config.loadDelayMs),
		"--save",
		outputFile,
		"--dir",
		outputDir,
	];
	if (config.failOnViolations) {
		args.push("--exit");
	}

	const result = spawnSync("pnpm", args, {
		cwd: appRoot,
		encoding: "utf8",
		stdio: "pipe",
	});

	if (result.status !== 0) {
		throw new Error(
			[`Failed to audit ${route}`, result.stdout, result.stderr]
				.filter(Boolean)
				.join("\n"),
		);
	}

	return {
		file: resolve(outputDir, outputFile),
		route,
		url,
	};
}

function main() {
	const config = parseArgs(process.argv.slice(2));
	const outputDir = resolve(appRoot, config.outDir);
	mkdirSync(outputDir, { recursive: true });

	const reports = [];
	for (const route of config.routes) {
		const report = runAxe({ config, outputDir, route });
		reports.push(report);
		console.log(`Audited ${route} -> ${report.file}`);
	}

	const manifest = {
		baseUrl: config.baseUrl,
		capturedAt: new Date().toISOString(),
		failOnViolations: config.failOnViolations,
		loadDelayMs: config.loadDelayMs,
		routes: config.routes,
		reports,
	};
	writeFileSync(
		resolve(outputDir, "manifest.json"),
		`${JSON.stringify(manifest, null, 2)}\n`,
	);
	console.log(`\nAccessibility baseline written to ${outputDir}`);
}

try {
	main();
} catch (error) {
	console.error(error instanceof Error ? error.message : error);
	process.exitCode = 1;
}
