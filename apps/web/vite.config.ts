import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@focus-agent/web-sdk": path.resolve(__dirname, "../../frontend-sdk/src/index.ts"),
    },
  },
  build: {
    target: "es2022",
    sourcemap: false,
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react") || id.includes("node_modules/react-dom")) {
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
          if (id.includes("zustand")) {
            return "state";
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
      "/v1": "http://127.0.0.1:8000",
      "/healthz": "http://127.0.0.1:8000",
      "/readyz": "http://127.0.0.1:8000",
      "/metrics": "http://127.0.0.1:8000",
    },
  },
});
