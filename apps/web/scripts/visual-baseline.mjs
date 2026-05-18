import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const appRoot = resolve(import.meta.dirname, "..");
const defaultBaseUrl = "http://127.0.0.1:5173/app";
const defaultOutputDir = "reports/visual-baseline";
const defaultRoutes = [
	"/",
	"/c/demo-conversation/t/demo-thread",
	"/c/demo-conversation/t/demo-thread/review",
	"/agent-team",
	"/agent-team/demo-session",
	"/observability/overview",
	"/observability/trajectory",
	"/agent/roles",
	"/agent/governance",
	"/agent/memory",
	"/productivity/notes",
	"/productivity/tasks",
	"/admin/users",
	"/admin/users/demo-user",
	"/admin/audit-events",
	"/auth",
	"/auth/login",
	"/auth/register",
	"/account/profile",
	"/account/security",
	"/account/sessions",
];

function parseArgs(argv) {
	const config = {
		baseUrl: defaultBaseUrl,
		outDir: defaultOutputDir,
		routes: defaultRoutes,
		schemes: ["dark", "light"],
		waitMs: 1200,
		viewport: "1440,1000",
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

		if (arg === "--schemes") {
			config.schemes = readList("--schemes", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--schemes=")) {
			config.schemes = readList("--schemes", arg.slice("--schemes=".length));
			continue;
		}

		if (arg === "--viewport") {
			config.viewport = readValue("--viewport", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--viewport=")) {
			config.viewport = readValue(
				"--viewport",
				arg.slice("--viewport=".length),
			);
			continue;
		}

		if (arg === "--wait-ms") {
			config.waitMs = readNumber("--wait-ms", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--wait-ms=")) {
			config.waitMs = readNumber("--wait-ms", arg.slice("--wait-ms=".length));
			continue;
		}

		throw new Error(`Unknown argument: ${arg}`);
	}

	return config;
}

function printHelp() {
	console.log(`Usage: node ./scripts/visual-baseline.mjs [options]

Captures route screenshots through the Playwright CLI.

Options:
  --base-url <url>      App base URL. Default: ${defaultBaseUrl}
  --out-dir <path>      Output path relative to apps/web. Default: ${defaultOutputDir}
  --routes <routes>     Comma-separated app routes. Default: current router catalog
  --schemes <schemes>   Comma-separated color schemes. Default: dark,light
  --viewport <size>     Browser viewport size. Default: 1440,1000
  --wait-ms <ms>        Wait before screenshot. Default: 1200
  -h, --help            Show this help message`);
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

function fileNameFor(route, scheme) {
	const label =
		route === "/"
			? "home"
			: route
					.replace(/^\//, "")
					.replace(/[^a-zA-Z0-9]+/g, "-")
					.replace(/^-|-$/g, "");
	return `${scheme}-${label}.png`;
}

function captureScreenshot({ config, outputDir, route, scheme }) {
	const url = buildUrl(config.baseUrl, route);
	const outputFile = resolve(outputDir, fileNameFor(route, scheme));
	const args = [
		"dlx",
		"playwright",
		"screenshot",
		"--browser",
		"chromium",
		"--color-scheme",
		scheme,
		"--full-page",
		"--viewport-size",
		config.viewport,
		"--wait-for-timeout",
		String(config.waitMs),
		url,
		outputFile,
	];
	const result = spawnSync("pnpm", args, {
		cwd: appRoot,
		encoding: "utf8",
		stdio: "pipe",
	});

	if (result.status !== 0) {
		throw new Error(
			[`Failed to capture ${scheme} ${route}`, result.stdout, result.stderr]
				.filter(Boolean)
				.join("\n"),
		);
	}

	return {
		file: outputFile,
		route,
		scheme,
		url,
	};
}

function main() {
	const config = parseArgs(process.argv.slice(2));
	const outputDir = resolve(appRoot, config.outDir);
	mkdirSync(outputDir, { recursive: true });

	const captures = [];
	for (const scheme of config.schemes) {
		for (const route of config.routes) {
			const capture = captureScreenshot({ config, outputDir, route, scheme });
			captures.push(capture);
			console.log(`Captured ${scheme} ${route} -> ${capture.file}`);
		}
	}

	const manifest = {
		baseUrl: config.baseUrl,
		capturedAt: new Date().toISOString(),
		routes: config.routes,
		schemes: config.schemes,
		viewport: config.viewport,
		waitMs: config.waitMs,
		captures,
	};
	writeFileSync(
		resolve(outputDir, "manifest.json"),
		`${JSON.stringify(manifest, null, 2)}\n`,
	);
	console.log(`\nVisual baseline written to ${outputDir}`);
}

try {
	main();
} catch (error) {
	console.error(error instanceof Error ? error.message : error);
	process.exitCode = 1;
}
