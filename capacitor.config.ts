import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
	appId: "ai.focusagent.app",
	appName: "Focus Agent",
	plugins: {
		CapacitorHttp: {
			enabled: true,
		},
	},
	webDir: "apps/web/dist",
	server: {
		androidScheme: "http",
	},
};

export default config;
