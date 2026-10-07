/**
 * One visitor's demo, kept in their own browser and nowhere else.
 *
 * The seed is fetched from this origin once, shifted so its dates are relative
 * to *today* rather than to the day it was built, and saved to localStorage.
 * Every change a visitor makes is written back there — which is the whole of
 * "two people can use the demo at once without seeing each other's data": the
 * server has no write path at all (nginx answers every POST with 405), so the
 * only copy of a visitor's state is theirs.
 *
 * localStorage can be missing or full (a private window, blocked site data);
 * the demo then runs from memory and forgets on reload, which is still correct.
 */
import type { Canned, Seed, State, StoredApplication, StoredArtifact } from "./types";

const KEY = "demo-tinternship:state";
// Promises, not values: the app's first render fires several queries at once,
// and caching only the result would start one download per query.
let seed: Promise<Seed> | null = null;
let state: Promise<State> | null = null;
let current: State | null = null;
let canned: Promise<Record<string, Canned>> | null = null;

async function loadJson<T>(name: string): Promise<T> {
  // `realFetch` is the browser's own fetch, saved before the mock replaced it:
  // this file lives on the same origin and is not an API call.
  const response = await realFetch(`/demo-data/${name}`);
  if (!response.ok) throw new Error(`The demo's ${name} did not load (${response.status}).`);
  return (await response.json()) as T;
}

export let realFetch: typeof fetch = (...args) => fetch(...args);
export function setRealFetch(original: typeof fetch): void {
  realFetch = original;
}

const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;
const DATE_ONLY_KEYS = new Set(["posted_on", "next_action_date"]);

/**
 * Move every timestamp in the seed by the time since it was built.
 *
 * The world is written as "posted 3 days ago", "applied 18 days ago"; built on
 * one day and opened months later, it would otherwise read as a deck of stale
 * postings and a Tracker of applications nobody has touched since autumn.
 */
export function shiftDates<T>(value: T, deltaMs: number): T {
  const days = Math.round(deltaMs / 86_400_000);
  const walk = (node: unknown, key = ""): unknown => {
    if (typeof node === "string") {
      if (ISO_DATETIME.test(node)) return new Date(Date.parse(node) + deltaMs).toISOString();
      if (DATE_ONLY_KEYS.has(key) && /^\d{4}-\d{2}-\d{2}$/.test(node)) {
        return new Date(Date.parse(`${node}T00:00:00Z`) + days * 86_400_000).toISOString().slice(0, 10);
      }
      return node;
    }
    if (Array.isArray(node)) return node.map((item) => walk(item, key));
    if (node && typeof node === "object") {
      return Object.fromEntries(Object.entries(node).map(([k, v]) => [k, walk(v, k)]));
    }
    return node;
  };
  return walk(value) as T;
}

/** The demo as it is on first visit — or after "Reset demo". */
export function initialState(source: Seed, now = Date.now()): State {
  const shifted = shiftDates(source, now - Date.parse(source.epoch));
  const applications: StoredApplication[] = [];
  const artifacts: StoredArtifact[] = [];
  for (const application of shifted.applications) {
    const { job: _job, artifacts: _summaries, timeline, silence: _silence, artifacts_full, ...row } = application;
    applications.push({ ...row, events: timeline ?? [] });
    for (const artifact of artifacts_full) artifacts.push({ ...artifact, application_id: application.id });
  }
  const ids = [
    ...shifted.jobs.map((job) => job.id),
    ...applications.map((application) => application.id),
    ...shifted.runs.map((run) => run.run.id),
    ...shifted.audits.map((audit) => audit.id),
    ...shifted.prompts.map((prompt) => prompt.id),
  ];
  return {
    version: source.version,
    // Above every seeded id, and below the canned documents' ids (1000+), so a
    // new row never collides with a document a run has yet to "write".
    nextId: Math.max(...ids) + 1,
    jobs: shifted.jobs,
    hidden: shifted.hidden_jobs,
    applications,
    artifacts,
    profile: shifted.profile,
    lists: shifted.lists.lists,
    prompts: shifted.prompts,
    runs: shifted.runs,
    audits: shifted.audits,
    history: [],
    interview: shifted.interview,
    settings: shifted.settings_config,
    searched: [],
  };
}

function read(): State | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as State) : null;
  } catch {
    return null;
  }
}

/** Persist after every change. Losing a write only loses this visitor's own edit. */
export function save(): void {
  if (!current) return;
  try {
    localStorage.setItem(KEY, JSON.stringify(current));
  } catch {
    /* private mode or quota: the demo carries on from memory */
  }
}

export function loadSeed(): Promise<Seed> {
  seed ??= loadJson<Seed>("seed.json");
  return seed;
}

/** This visitor's state, seeded on first use. */
export function store(): Promise<State> {
  state ??= loadSeed().then((source) => {
    const stored = read();
    // A rebuilt seed is a different world: ids and postings no longer line up
    // with what was saved, so start the visitor over rather than mixing the two.
    current = stored && stored.version === source.version ? stored : initialState(source);
    save();
    return current;
  });
  return state;
}

export async function cannedFor(key: string): Promise<Canned> {
  canned ??= loadJson<Record<string, Canned>>("canned.json");
  const all = await canned;
  const entry = all[key];
  if (!entry) throw new Error(`No pre-written answer for ${key}.`);
  return entry;
}

/** Back to the seed. Clears only this demo's key — nothing else on the origin. */
export async function reset(): Promise<void> {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* nothing stored */
  }
  current = initialState(await loadSeed());
  state = Promise.resolve(current);
  save();
}

export function newId(current: State): number {
  const id = current.nextId;
  current.nextId += 1;
  return id;
}

/** For tests: forget what this module holds in memory. */
export function __resetModule(): void {
  seed = null;
  state = null;
  current = null;
  canned = null;
}
