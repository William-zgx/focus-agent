import { readdirSync, statSync } from "node:fs";
import { extname, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "..");
const assetsRoot = resolve(root, "dist/assets");

export const defaultBudget = Object.freeze({
	maxCssBytes: 575_000,
	maxJsBytes: 1_250_000,
	maxCssAssetBytes: 575_000,
	maxJsAssetBytes: 550_000,
});

function parseArgs(argv) {
	const config = { budget: { ...defaultBudget }, printBudget: false };

	for (let index = 0; index < argv.length; index += 1) {
		const arg = argv[index];

		if (arg === "--help" || arg === "-h") {
			printHelp();
			process.exit(0);
		}

		if (arg === "--print-budget") {
			config.printBudget = true;
			continue;
		}

		if (arg === "--max-css") {
			config.budget.maxCssBytes = readNumberArg("--max-css", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--max-css=")) {
			config.budget.maxCssBytes = readNumberArg(
				"--max-css",
				arg.slice("--max-css=".length),
			);
			continue;
		}

		if (arg === "--max-js") {
			config.budget.maxJsBytes = readNumberArg("--max-js", argv[index + 1]);
			index += 1;
			continue;
		}

		if (arg.startsWith("--max-js=")) {
			config.budget.maxJsBytes = readNumberArg(
				"--max-js",
				arg.slice("--max-js=".length),
			);
			continue;
		}

		if (arg === "--max-css-asset") {
			config.budget.maxCssAssetBytes = readNumberArg(
				"--max-css-asset",
				argv[index + 1],
			);
			index += 1;
			continue;
		}

		if (arg.startsWith("--max-css-asset=")) {
			config.budget.maxCssAssetBytes = readNumberArg(
				"--max-css-asset",
				arg.slice("--max-css-asset=".length),
			);
			continue;
		}

		if (arg === "--max-js-asset") {
			config.budget.maxJsAssetBytes = readNumberArg(
				"--max-js-asset",
				argv[index + 1],
			);
			index += 1;
			continue;
		}

		if (arg.startsWith("--max-js-asset=")) {
			config.budget.maxJsAssetBytes = readNumberArg(
				"--max-js-asset",
				arg.slice("--max-js-asset=".length),
			);
			continue;
		}

		throw new Error(`Unknown argument: ${arg}`);
	}

	return config;
}

function printHelp() {
	console.log(`Usage: node ./scripts/bundle-budget.mjs [options]

Checks Vite build asset byte budgets under dist/assets.

Options:
  --max-css <bytes>        Maximum allowed total CSS bytes. Default: ${defaultBudget.maxCssBytes}
  --max-js <bytes>         Maximum allowed total JS bytes. Default: ${defaultBudget.maxJsBytes}
  --max-css-asset <bytes>  Maximum allowed single CSS asset bytes. Default: ${defaultBudget.maxCssAssetBytes}
  --max-js-asset <bytes>   Maximum allowed single JS asset bytes. Default: ${defaultBudget.maxJsAssetBytes}
  --print-budget           Print the default budget as JSON.
  -h, --help               Show this help message`);
}

function readNumberArg(name, value) {
	const parsed = Number(value);
	if (!Number.isInteger(parsed) || parsed < 0) {
		throw new Error(`${name} must be a non-negative integer.`);
	}
	return parsed;
}

function readAssets() {
	const stats = statSync(assetsRoot, { throwIfNoEntry: false });
	if (!stats?.isDirectory()) {
		throw new Error(
			`Missing web build assets at ${relative(root, assetsRoot)}. Run \`pnpm --filter @focus-agent/web-app build\` or \`pnpm web:build\` first.`,
		);
	}

	return readdirSync(assetsRoot)
		.map((file) => {
			const path = resolve(assetsRoot, file);
			const stats = statSync(path);
			return {
				file: relative(root, path),
				bytes: stats.size,
				extension: extname(file),
				isFile: stats.isFile(),
			};
		})
		.filter((asset) =>
			asset.isFile && [".css", ".js", ".mjs"].includes(asset.extension),
		)
		.sort((left, right) => left.file.localeCompare(right.file));
}

function sumBytes(assets) {
	return assets.reduce((sum, asset) => sum + asset.bytes, 0);
}

function largestAssets(assets, count = 8) {
	return [...assets].sort((left, right) => right.bytes - left.bytes).slice(0, count);
}

function formatBytes(bytes) {
	return `${bytes} B`;
}

function reportAssetGroup(label, assets, totalBudget, assetBudget) {
	const totalBytes = sumBytes(assets);
	const largest = largestAssets(assets);

	console.log(`${label} assets: ${assets.length}`);
	console.log(`${label} total bytes: ${formatBytes(totalBytes)}`);
	console.log(`${label} total budget: ${formatBytes(totalBudget)}`);
	console.log(`${label} single-file budget: ${formatBytes(assetBudget)}`);

	if (largest.length) {
		console.log(`Largest ${label} assets:`);
		for (const asset of largest) {
			console.log(`- ${asset.file}: ${formatBytes(asset.bytes)}`);
		}
	}

	return {
		totalBytes,
		totalFailed: totalBytes > totalBudget,
		oversizedAssets: assets.filter((asset) => asset.bytes > assetBudget),
	};
}

function main() {
	const config = parseArgs(process.argv.slice(2));
	if (config.printBudget) {
		console.log(JSON.stringify(defaultBudget, null, 2));
		return;
	}

	const assets = readAssets();
	const cssAssets = assets.filter((asset) => asset.extension === ".css");
	const jsAssets = assets.filter(
		(asset) => asset.extension === ".js" || asset.extension === ".mjs",
	);

	console.log("Web bundle budget");
	console.log(`Asset root: ${relative(root, assetsRoot)}`);
	console.log("");

	const cssReport = reportAssetGroup(
		"CSS",
		cssAssets,
		config.budget.maxCssBytes,
		config.budget.maxCssAssetBytes,
	);
	console.log("");
	const jsReport = reportAssetGroup(
		"JS",
		jsAssets,
		config.budget.maxJsBytes,
		config.budget.maxJsAssetBytes,
	);

	const failures = [];
	if (cssReport.totalFailed) {
		failures.push(
			`CSS total bytes (${cssReport.totalBytes}) exceed budget (${config.budget.maxCssBytes}).`,
		);
	}
	if (jsReport.totalFailed) {
		failures.push(
			`JS total bytes (${jsReport.totalBytes}) exceed budget (${config.budget.maxJsBytes}).`,
		);
	}
	for (const asset of cssReport.oversizedAssets) {
		failures.push(
			`${asset.file} (${asset.bytes}) exceeds CSS single-file budget (${config.budget.maxCssAssetBytes}).`,
		);
	}
	for (const asset of jsReport.oversizedAssets) {
		failures.push(
			`${asset.file} (${asset.bytes}) exceeds JS single-file budget (${config.budget.maxJsAssetBytes}).`,
		);
	}

	if (failures.length) {
		console.error("\nFailed bundle budget:");
		for (const failure of failures) {
			console.error(`- ${failure}`);
		}
		process.exitCode = 1;
	} else {
		console.log("\nPassed: JS and CSS assets are within bundle budgets.");
	}
}

const isCli = process.argv[1]
	? import.meta.url === pathToFileURL(process.argv[1]).href
	: false;

if (isCli) {
	try {
		main();
	} catch (error) {
		console.error(error instanceof Error ? error.message : error);
		process.exitCode = 1;
	}
}
