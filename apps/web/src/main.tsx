import React from "react";
import ReactDOM from "react-dom/client";

import { AppProviders } from "@/app/providers/app-providers";
import { AppRouter } from "@/app/router";
import "@/shared/styles/app.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppProviders>
      <AppRouter />
    </AppProviders>
  </React.StrictMode>,
);
