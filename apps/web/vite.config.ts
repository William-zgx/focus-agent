import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

const apiHost = process.env.API_HOST || "127.0.0.1";
const apiPort = process.env.API_PORT || "8000";
const apiTarget = `http://${apiHost}:${apiPort}`;
const appBase = process.env.VITE_FOCUS_AGENT_APP_BASE || "/app/";

export default defineConfig({
	base: appBase,
	plugins: [react(), tailwindcss()],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "./src"),
			"@focus-agent/web-sdk": path.resolve(
				__dirname,
				"../../frontend-sdk/src/index.ts",
			),
		},
	},
	build: {
		target: "es2022",
		sourcemap: false,
		chunkSizeWarningLimit: 800,
		rollupOptions: {
			output: {
				manualChunks(id) {
					if (
						id.includes("node_modules/react") ||
						id.includes("node_modules/react-dom")
					) {
						return "react-vendor";
					}
					if (id.includes("@tanstack/react-router")) {
						return "router";
					}
					if (
						id.includes("@tanstack/react-query") ||
						id.includes("@tanstack/react-query-devtools")
					) {
						return "query";
					}
					return undefined;
				},
			},
		},
	},
	server: {
		host: "127.0.0.1",
		port: 5173,
		proxy: {
			"/v1": apiTarget,
			"/v2": apiTarget,
			"/healthz": apiTarget,
			"/readyz": apiTarget,
			"/metrics": apiTarget,
		},
	},
});
