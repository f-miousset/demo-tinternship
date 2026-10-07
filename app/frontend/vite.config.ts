// `vitest/config` rather than `vite`: it is the same `defineConfig` with the
// `test` block typed, so the dev server and the test runner share one set of
// plugins. Two configs would let the tests pass under a Vite setup the build
// does not use — which is the one thing a dependency-bump gate must not allow.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Proxying keeps the frontend origin-relative, so SSE and file downloads
    // work without CORS preflights or absolute URLs baked into the build.
    //
    // `BACKEND_PORT` is the same variable the Makefile passes to uvicorn. Until
    // 2026-08-27 this was the literal 8000, so `BACKEND_PORT=8010 make dev`
    // started the backend on 8010 and left the frontend proxying to a port
    // nothing was listening on — every request 500ing with no clue why.
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${process.env.BACKEND_PORT || 8000}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    // The suite renders real components, so it needs a DOM. `globals` stays off
    // — every test imports what it uses, which keeps `tsc --noEmit` honest
    // without adding a second ambient type package to the typecheck.
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    // Three times the 5 s `findBy*` ceiling set in `src/test/setup.ts`, so a
    // test waiting on several elements on a busy CI runner can still finish.
    testTimeout: 15000,
  },
});
