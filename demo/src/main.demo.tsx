/**
 * The demo's entry: install the mock API, mount the notice, then start the real app.
 *
 * Order matters and is the reason this file exists. The mock replaces `fetch`
 * before a single module of the app runs, so the app's first request — the
 * config the setup gate reads — is already answered in the browser. The app
 * itself is `app/frontend/src/main.tsx`, imported unchanged.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./demo.css";
import { DemoNotice } from "./demo/DemoNotice";
import { installMock } from "./mock/install";

installMock();

const host = document.createElement("div");
host.id = "demo-root";
document.body.appendChild(host);

// Dynamic, so it is evaluated after `installMock()` above rather than hoisted
// before it as a static import would be.
void import("../../app/frontend/src/main").then(() => {
  createRoot(host).render(
    <StrictMode>
      <DemoNotice />
    </StrictMode>,
  );
});
