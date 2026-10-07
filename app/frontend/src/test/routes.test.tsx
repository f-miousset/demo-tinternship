/**
 * Every route mounts.
 *
 * Thin on assertions and deliberately so: what it proves is that the real route
 * table, the real Layout and each real page render under React, React Router
 * and TanStack Query without throwing — and `src/test/setup.ts` fails the test
 * on any `console.error`, which is where React reports a render it had to
 * abandon. `npm run build` and `tsc --noEmit` cannot see any of that: a major
 * bump in one of those three typechecks, builds, and then paints nothing.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { renderApp, stubApi } from "./harness";

describe("the route table", () => {
  beforeEach(() => {
    stubApi();
  });

  // By role, not by text: "Tracker", "Account" and "Settings" are also nav
  // links in the shell, and a query that matched those would pass on a page
  // that never rendered.
  it.each([
    ["/jobs", "Job postings"],
    ["/tracker", "Tracker"],
    ["/account", "Account"],
    ["/settings", "Settings"],
    ["/traces", "Traces & audit"],
  ])("%s renders its page", async (path, heading) => {
    renderApp(path);
    expect(await screen.findByRole("heading", { name: heading })).toBeTruthy();
  });

  // Nothing is stubbed for either id, so both land on the state a real missing
  // row produces rather than on a blank screen.
  it.each([
    ["/traces/1", "Run not found"],
    ["/applications/1", "Application not found"],
  ])("%s says so rather than rendering nothing", async (path, message) => {
    renderApp(path);
    expect(await screen.findByText(message)).toBeTruthy();
  });

  it("sends the root to Jobs", async () => {
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Job postings" })).toBeTruthy();
  });

  it.each(["/profile", "/interview", "/strategy"])(
    "keeps the old %s bookmark working by redirecting to Account",
    async (path) => {
      renderApp(path);
      expect(await screen.findByRole("heading", { name: "Account" })).toBeTruthy();
    },
  );
});
