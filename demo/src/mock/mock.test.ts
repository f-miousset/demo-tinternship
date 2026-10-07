/**
 * The mock's contract with the app, and the paths that would fail quietly.
 *
 * Quietly is the operative word: a missing route renders as a page that says
 * "not found" where a list should be, a canned document without its static
 * file renders as a blank preview, and an auto-fill whose placeholder the app
 * renamed simply stops filling. None of those throws in a browser.
 */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { RULES } from "../demo/autofill";
import { setPace } from "./http";
import { handle, routeTable, searchFor } from "./routes";
import { __resetModule, initialState, setRealFetch, shiftDates } from "./store";
import type { Seed } from "./types";

const ROOT = join(__dirname, "..", "..", "..");
const STATIC = join(ROOT, "demo", "static");
const APP_SRC = join(ROOT, "app", "frontend", "src");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "test" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

/** Serve `/demo-data/*.json` from disk, as the dev server and nginx do. */
function serveStatic(): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://demo.test").pathname;
    const name = path.replace("/demo-data/", "");
    return new Response(readFileSync(join(STATIC, "seed", name)), { headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
}

async function call(method: string, path: string, body?: unknown) {
  const url = new URL(path, "http://demo.test");
  return handle({ method, path: url.pathname, query: url.searchParams, body });
}

async function readStream(response: Response): Promise<{ event: string; data: any }[]> {
  const raw = await response.text();
  return raw
    .split("\n\n")
    .filter(Boolean)
    .map((chunk) => {
      const event = /event: (.*)/.exec(chunk)?.[1] ?? "message";
      return { event, data: JSON.parse(/data: (.*)/.exec(chunk)?.[1] ?? "null") };
    });
}

beforeEach(() => {
  localStorage.clear();
  __resetModule();
  setRealFetch(serveStatic());
  setPace(0);
});

afterEach(() => setPace(900));

describe("the contract with the app's frontend", () => {
  it("has a route for every /api path the frontend mentions", () => {
    const paths = new Set<string>();
    for (const file of sourceFiles(APP_SRC)) {
      for (const match of readFileSync(file, "utf8").matchAll(/["`](\/api\/[^"`?\s]*)/g)) {
        // Placeholders — `${id}` in code, `{kind}` in a comment — become one
        // marker, filled below with every value a real call could carry.
        paths.add(match[1].replace(/\$?\{[^}]+\}/g, "·").replace(/\/$/, ""));
      }
    }
    expect(paths.size).toBeGreaterThan(30);
    // Previews and downloads are iframes and links, served as static files.
    const staticOnly = /\/artifacts\/·\/(preview|export)$|\/sources\/·\/file$/;
    const values = ["1", "resume", "cover_letter", "en", "fr", "search_brief", "playbook"];
    const expand = (path: string): string[] =>
      path.includes("·") ? values.flatMap((value) => expand(path.replace("·", value))) : [path];
    const missing = [...paths].filter(
      (path) =>
        !staticOnly.test(path) &&
        !expand(path).some((candidate) => routeTable.some((route) => route.pattern.test(candidate))),
    );
    expect(missing).toEqual([]);
  });

  it("auto-fills boxes the app still renders, by the attributes it still uses", () => {
    const source = sourceFiles(APP_SRC).map((file) => readFileSync(file, "utf8")).join("\n");
    for (const needle of [
      'placeholder="A company, a kind of role',
      'placeholder="Paste a job posting link"',
      'placeholder="Paste the whole posting',
      '"Describe the internship you want',
      'aria-label="What you know about this employer"',
    ]) {
      expect(source, needle).toContain(needle);
    }
    expect(RULES).toHaveLength(5);
  });
});

describe("the seed", () => {
  it("has a preview and a download for every document a run can write", () => {
    const canned = JSON.parse(readFileSync(join(STATIC, "seed", "canned.json"), "utf8"));
    const names = JSON.parse(readFileSync(join(STATIC, "export-names.json"), "utf8"));
    const ids = Object.values(canned).flatMap((entry: any) => Object.values(entry.documents).map((doc: any) => doc.id));
    expect(ids.length).toBeGreaterThan(80);
    for (const id of ids) {
      expect(existsSync(join(STATIC, "artifacts", `${id}.html`)), `${id}.html`).toBe(true);
      expect(existsSync(join(STATIC, "artifacts", `${id}.docx`)), `${id}.docx`).toBe(true);
      expect(names[String(id)]).toMatch(/\.docx$/);
    }
  });

  it("opens on a finished setup, so the gate lets a visitor straight in", async () => {
    const config = await (await call("GET", "/api/config")).json();
    expect(config.progress.complete).toBe(true);
    expect(config.warnings).toEqual([]);
  });

  it("moves every timestamp to today's frame, dates included", () => {
    const shifted = shiftDates(
      { at: "2026-10-08T09:00:00+00:00", posted_on: "2026-10-01", text: "2026-10-01" },
      10 * 86_400_000,
    );
    expect(shifted.at).toBe("2026-10-18T09:00:00.000Z");
    expect(shifted.posted_on).toBe("2026-10-11");
    expect(shifted.text).toBe("2026-10-01");
  });

  it("puts every new id between the seeded rows and the canned documents", () => {
    const seed = JSON.parse(readFileSync(join(STATIC, "seed", "seed.json"), "utf8")) as Seed;
    const state = initialState(seed);
    expect(state.nextId).toBeLessThan(500);
  });
});

describe("the runs, replayed", () => {
  it("reveals a canned search once, and finds the same postings again after", async () => {
    expect(searchFor("Energy and climate teams in Lyon, hybrid")).toBe("energy");
    const before = (await (await call("GET", "/api/jobs?view=deck")).json()).jobs.length;
    const first = await readStream(await call("POST", "/api/jobs/search?target_results=15", { focus: "energy in Lyon" }));
    const result = first.find((event) => event.event === "result")!.data;
    expect(result.saved.created).toBe(3);
    expect((await (await call("GET", "/api/jobs?view=deck")).json()).jobs.length).toBe(before + 3);
    const again = await readStream(await call("POST", "/api/jobs/search?target_results=15", { focus: "energy in Lyon" }));
    expect(again.find((event) => event.event === "result")!.data.saved.created).toBe(0);
  });

  it("orders a run's progress lines as the pipeline runs them", async () => {
    const events = await readStream(await call("POST", "/api/jobs/search", {}));
    const phases = events.filter((event) => event.event === "phase").map((event) => event.data.phase);
    expect(phases.indexOf("query_planner")).toBeLessThan(phases.indexOf("matcher"));
  });

  it("imports the suggested link straight onto the Tracker, and refuses any other", async () => {
    const seed = JSON.parse(readFileSync(join(STATIC, "seed", "seed.json"), "utf8")) as Seed;
    const ok = await readStream(await call("POST", "/api/jobs/import", { url: seed.link_import }));
    const result = ok.find((event) => event.event === "result")!.data;
    expect(result.tracked).toBe(true);
    expect(result.application_id).toBeGreaterThan(0);
    const other = await readStream(await call("POST", "/api/jobs/import", { url: "https://elsewhere.example.org/job" }));
    expect(other.at(-1)!.event).toBe("error");
  });

  it("writes a résumé and a letter whose previews exist, and logs the run", async () => {
    const before = (await (await call("GET", "/api/traces/stats")).json()).runs;
    const events = await readStream(
      await call("POST", "/api/applications/1/generate", { language: "fr", resume: true, cover_letter: true }),
    );
    const { artifacts, run_id } = events.find((event) => event.event === "result")!.data;
    for (const kind of ["resume", "cover_letter"]) {
      expect(existsSync(join(STATIC, "artifacts", `${artifacts[kind].id}.html`))).toBe(true);
    }
    const list = (await (await call("GET", "/api/applications/1/artifacts")).json()).artifacts;
    expect(list.find((artifact: any) => artifact.id === artifacts.resume.id).audit.overall).toBeGreaterThan(7);
    expect((await (await call("GET", "/api/traces/stats")).json()).runs).toBe(before + 1);
    expect((await call("GET", `/api/traces/runs/${run_id}`)).status).toBe(200);
  });

  it("keeps a visitor's changes in their browser and nowhere else, until they reset", async () => {
    await call("POST", "/api/applications/1/trash");
    expect(localStorage.getItem("demo-tinternship:state")).toContain('"trashed_at"');
    __resetModule();
    const board = (await (await call("GET", "/api/applications")).json()).applications;
    expect(board.some((application: any) => application.id === 1)).toBe(false);
    const reset = await call("POST", "/api/settings/reset", { confirm: "DELETE" });
    expect(reset.status).toBe(200);
    const after = (await (await call("GET", "/api/applications")).json()).applications;
    expect(after.some((application: any) => application.id === 1)).toBe(true);
  });
});
