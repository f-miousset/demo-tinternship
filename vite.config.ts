// The demo is the real app's frontend (app/frontend/src, unmodified) built from
// a different entry: demo/src/main.demo.tsx installs the in-browser mock of the
// API, then imports the app's own main.tsx. Everything the app's Vite config
// does for the app — React, Tailwind, the PWA files in public/ — happens here
// the same way, so the demo cannot look different from the real thing.
//
// `vitest/config` rather than `vite`, for the reason the app's config gives:
// one set of plugins for the dev server, the build and the tests.
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

import { demoFiles } from "./demo/vite-demo-files.ts";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  // The repository root, not demo/: Tailwind generates only the utilities it
  // finds under the root, and the app's components — every class the UI uses —
  // live in app/frontend/src. With root at demo/ the build shipped 17 kB of CSS
  // and an unstyled app (found 2026-10-08).
  root,
  // The app's icons, manifest, service worker and theme boot script, as they are.
  publicDir: "app/frontend/public",
  plugins: [react(), tailwindcss(), demoFiles()],
  // One copy of each, whichever directory imports it. app/frontend has its own
  // package.json, and a local `npm install` there would otherwise give the app's
  // files a second React that the demo's providers cannot see.
  resolve: { dedupe: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"] },
  build: { outDir: "dist", emptyOutDir: true },
  server: { port: 5174, fs: { allow: [root] } },
  test: {
    root,
    environment: "jsdom",
    include: ["demo/src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    testTimeout: 20000,
  },
});
