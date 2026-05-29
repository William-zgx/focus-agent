import { readdirSync, readFileSync, statSync } from "node:fs";
import { relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const defaultRoots = ["src/shared/styles", "src"];
const defaultMaxLines = 19005;
const defaultMaxModules = 64;

function parseArgs(argv) {
	const config = {
		maxLines: defaultMaxLines,
		maxModules: defaultMaxModules,
		roots: defaultRoots,
	};

	for (let index = 0; index < argv.length; index += 1) {
		const arg = argv[index];

		if (arg === "--help" || arg === "-h") {
			printHelp();
			process.exit(0);
		}

		if (arg === "--max-lines") {
			config.maxLines = readNumberArg("--max-lines", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--max-lines=")) {
			config.maxLines = readNumberArg(
				"--max-lines",
				arg.slice("--max-lines=".length),
			);
			continue;
		}

		if (arg === "--max-modules") {
			config.maxModules = readNumberArg("--max-modules", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--max-modules=")) {
			config.maxModules = readNumberArg(
				"--max-modules",
				arg.slice("--max-modules=".length),
			);
			continue;
		}

		if (arg === "--paths") {
			config.roots = readPathsArg(argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--paths=")) {
			config.roots = readPathsArg(arg.slice("--paths=".length));
			continue;
		}

		throw new Error(`Unknown argument: ${arg}`);
	}

	return config;
}

function printHelp() {
	console.log(`Usage: node ./scripts/css-loc-budget.mjs [options]

Checks CSS line and module budgets.

Options:
  --max-lines <count>     Maximum allowed total CSS lines. Default: ${defaultMaxLines}
  --max-modules <count>   Maximum allowed CSS module files under src/shared/styles/modules. Default: ${defaultMaxModules}
  --paths <paths>         Comma-separated paths relative to apps/web. Default: ${defaultRoots.join(",")}
  -h, --help              Show this help message`);
}

function readNumberArg(name, value) {
	const parsed = Number(value);
	if (!Number.isInteger(parsed) || parsed < 0) {
		throw new Error(`${name} must be a non-negative integer.`);
	}
	return parsed;
}

function readPathsArg(value) {
	const paths = value
		?.split(",")
		.map((path) => path.trim())
		.filter(Boolean);

	if (!paths?.length) {
		throw new Error("--paths must include at least one path.");
	}

	return paths;
}

function collectCssFiles(paths) {
	const files = new Map();

	for (const path of paths) {
		const absolutePath = resolve(root, path);
		collectPath(absolutePath, files);
	}

	return [...files.values()].sort((left, right) => left.localeCompare(right));
}

function collectPath(path, files) {
	const stats = statSync(path, { throwIfNoEntry: false });
	if (!stats) {
		return;
	}

	if (stats.isDirectory()) {
		for (const entry of readdirSync(path)) {
			if (entry === "dist" || entry === "node_modules") {
				continue;
			}
			collectPath(resolve(path, entry), files);
		}
		return;
	}

	if (stats.isFile() && path.endsWith(".css")) {
		files.set(path, path);
	}
}

function countLines(filePath) {
	const source = readFileSync(filePath, "utf8");
	if (source.length === 0) {
		return 0;
	}
	return source.split(/\r?\n/).length;
}

function isStyleModule(filePath) {
	return relative(root, filePath).startsWith("src/shared/styles/modules/");
}

function main() {
	const config = parseArgs(process.argv.slice(2));
	const files = collectCssFiles(config.roots);
	const fileReports = files.map((file) => ({
		file: relative(root, file),
		lines: countLines(file),
		isModule: isStyleModule(file),
	}));
	const totalLines = fileReports.reduce((sum, file) => sum + file.lines, 0);
	const moduleCount = fileReports.filter((file) => file.isModule).length;
	const failedLines = totalLines > config.maxLines;
	const failedModules = moduleCount > config.maxModules;

	console.log("CSS governance: LOC budget");
	console.log(`CSS files: ${fileReports.length}`);
	console.log(`CSS modules: ${moduleCount}`);
	console.log(`CSS module budget: ${config.maxModules}`);
	console.log(`Total CSS lines: ${totalLines}`);
	console.log(`CSS line budget: ${config.maxLines}`);

	if (fileReports.length) {
		console.log("\nLargest CSS files:");
		for (const file of [...fileReports]
			.sort((left, right) => right.lines - left.lines)
			.slice(0, 10)) {
			console.log(`- ${file.file}: ${file.lines}`);
		}
	}

	if (failedLines || failedModules) {
		if (failedLines) {
			console.error(
				`\nFailed: CSS lines (${totalLines}) exceed budget (${config.maxLines}).`,
			);
		}
		if (failedModules) {
			console.error(
				`\nFailed: CSS modules (${moduleCount}) exceed budget (${config.maxModules}).`,
			);
		}
		process.exitCode = 1;
	} else {
		console.log("\nPassed: CSS LOC and module counts are within budget.");
	}
}

try {
	main();
} catch (error) {
	console.error(error instanceof Error ? error.message : error);
	process.exitCode = 1;
}
