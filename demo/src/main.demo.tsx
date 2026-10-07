/**
 * The demo's entry: install the mock API, start the real app, mount the notice.
 *
 * Order matters and is the reason this file exists. `./mock/boot` replaces
 * `fetch` when it is evaluated, and it is imported before the app, so the app's
 * first request — the config the setup gate reads — is already answered in the
 * browser. The app itself is `app/frontend/src/main.tsx`, imported unchanged,
 * statically, so it runs during the page load as it does in production (its
 * service worker registers on `load`).
 */
import "./mock/boot";
import "../../app/frontend/src/main";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./demo.css";
import { DemoNotice } from "./demo/DemoNotice";

const host = document.createElement("div");
host.id = "demo-root";
document.body.appendChild(host);

createRoot(host).render(
  <StrictMode>
    <DemoNotice />
  </StrictMode>,
);
