import React from "react";
import ReactDOM from "react-dom/client";

import { AppProviders } from "@/app/providers/app-providers";
import { AppRouter } from "@/app/router";
import "@/shared/styles/app.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
	throw new Error("Root element #root was not found.");
}

ReactDOM.createRoot(rootElement).render(
	<React.StrictMode>
		<AppProviders>
			<AppRouter />
		</AppProviders>
	</React.StrictMode>,
);
