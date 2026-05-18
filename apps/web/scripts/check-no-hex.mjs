import { readdirSync, readFileSync, statSync } from "node:fs";
import { relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const defaultRoots = ["src/shared/styles", "src"];
const allowedExtensions = new Set([".css", ".ts", ".tsx"]);
const defaultMaxHex = 197;

function parseArgs(argv) {
	const config = {
		max: defaultMaxHex,
		roots: defaultRoots,
		showAll: false,
	};

	for (let index = 0; index < argv.length; index += 1) {
		const arg = argv[index];

		if (arg === "--help" || arg === "-h") {
			printHelp();
			process.exit(0);
		}

		if (arg === "--all") {
			config.showAll = true;
			continue;
		}

		if (arg === "--max") {
			config.max = readNumberArg("--max", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--max=")) {
			config.max = readNumberArg("--max", arg.slice("--max=".length));
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
	console.log(`Usage: node ./scripts/check-no-hex.mjs [options]

Checks CSS governance for hard-coded hex colors.

Options:
  --max <count>       Maximum allowed hex color occurrences. Default: ${defaultMaxHex}
  --paths <paths>     Comma-separated paths relative to apps/web. Default: ${defaultRoots.join(",")}
  --all               Print every match instead of the first 50
  -h, --help          Show this help message`);
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

function extensionOf(filePath) {
	const match = /\.[^.]+$/.exec(filePath);
	return match?.[0] ?? "";
}

function collectFiles(paths) {
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

	if (stats.isFile() && allowedExtensions.has(extensionOf(path))) {
		files.set(path, path);
	}
}

function findMatches(filePath) {
	const source = readFileSync(filePath, "utf8");
	const matches = [];

	source.split(/\r?\n/).forEach((line, lineIndex) => {
		const hexPattern = /#[0-9a-fA-F]{3,8}\b/g;
		let match = hexPattern.exec(line);
		while (match) {
			matches.push({
				file: relative(root, filePath),
				line: lineIndex + 1,
				column: match.index + 1,
				value: match[0],
				text: line.trim(),
			});
			match = hexPattern.exec(line);
		}
	});

	return matches;
}

function groupByFile(matches) {
	const counts = new Map();
	for (const match of matches) {
		counts.set(match.file, (counts.get(match.file) ?? 0) + 1);
	}
	return [...counts.entries()].sort((left, right) => right[1] - left[1]);
}

function main() {
	const config = parseArgs(process.argv.slice(2));
	const files = collectFiles(config.roots);
	const matches = files.flatMap(findMatches);
	const overBudget = matches.length > config.max;
	const shownMatches = config.showAll ? matches : matches.slice(0, 50);

	console.log("CSS governance: no hard-coded hex colors");
	console.log(`Scanned files: ${files.length}`);
	console.log(`Occurrences: ${matches.length}`);
	console.log(`Budget: ${config.max}`);

	if (matches.length && (overBudget || config.showAll)) {
		console.log("\nMatches:");
		for (const match of shownMatches) {
			console.log(
				`- ${match.file}:${match.line}:${match.column} ${match.value} ${match.text}`,
			);
		}

		if (shownMatches.length < matches.length) {
			console.log(
				`... ${matches.length - shownMatches.length} more match(es). Use --all to print all.`,
			);
		}
	}

	if (matches.length) {
		console.log("\nTop files:");
		for (const [file, count] of groupByFile(matches).slice(0, 10)) {
			console.log(`- ${file}: ${count}`);
		}
	}

	if (overBudget) {
		console.error(
			`\nFailed: hex color occurrences (${matches.length}) exceed budget (${config.max}).`,
		);
		process.exitCode = 1;
	} else {
		console.log("\nPassed: hex color usage is within budget.");
	}
}

try {
	main();
} catch (error) {
	console.error(error instanceof Error ? error.message : error);
	process.exitCode = 1;
}
