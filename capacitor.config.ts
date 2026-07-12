import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
	appId: "ai.focusagent.app",
	appName: "Focus Agent",
	android: {
		loggingBehavior: "none",
	},
	plugins: {
		CapacitorHttp: {
			enabled: true,
		},
	},
	webDir: "apps/web/dist-android",
	server: {
		androidScheme: "http",
	},
};

export default config;
