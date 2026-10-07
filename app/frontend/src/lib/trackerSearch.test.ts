/**
 * What the Tracker's search field will and will not find.
 *
 * Four of these fail quietly rather than loudly: an accent that stops "donnees"
 * from finding "Données", a second word that widens the result instead of
 * narrowing it, an underscore that hides `google_search` from "google search",
 * and the posting's full text leaking into the haystack — which does not throw
 * anywhere, it just hands back the whole board for every common word and makes
 * the field look broken for a reason nobody can see.
 */
import { describe, expect, it } from "vitest";

import { searchApplications } from "./trackerSearch";
import type { Application, Job } from "./types";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 1,
    title: "Machine Learning Intern",
    company: "Nimbus Labs",
    location: "Lyon, France",
    remote: "hybrid",
    url: "",
    apply_url: "",
    source: "google_search",
    description: "A six-month internship on the training platform team.",
    summary: "Build and maintain the training pipelines.",
    requirements: [],
    nice_to_have: [],
    contract_type: "internship",
    start_date: "",
    duration: "",
    compensation: "",
    language: "en",
    posted_at: "",
    posted_on: "",
    posted_days_ago: null,
    deadline: "",
    fit_score: 8.2,
    fit_rationale: "",
    strengths: [],
    risks: [],
    keywords: ["pytorch"],
    confidence: "high",
    url_status: "ok",
    url_http_status: 200,
    dismissed: false,
    deferred_at: null,
    run_id: null,
    invocation_id: "",
    discovered_at: "2026-08-25T09:00:00+00:00",
    application_id: 1,
    ...overrides,
  };
}

function application(id: number, overrides: Partial<Application> = {}): Application {
  return {
    id,
    job_posting_id: id,
    status: "applied",
    pinned: false,
    language: "en",
    personalisation: "",
    notes: "",
    next_action: "",
    next_action_date: "",
    applied_at: null,
    trashed_at: null,
    created_at: "2026-08-26T09:00:00+00:00",
    updated_at: "2026-08-26T09:00:00+00:00",
    job: job(),
    artifacts: [],
    timeline: [],
    ...overrides,
  };
}

const NIMBUS = application(1);
const ORBITAL = application(2, {
  status: "technical_test",
  job: job({
    id: 2,
    title: "Data Engineering Intern",
    company: "Orbital SA",
    location: "Paris, France",
    source: "adzuna",
    summary: "Ingestion pipelines for the analytics team.",
    keywords: ["spark"],
  }),
});
const BOARD = [NIMBUS, ORBITAL];

/** The ids a query returns, so an assertion reads as a result set. */
function found(query: string, board: Application[] = BOARD): number[] {
  return searchApplications(board, query).map((a) => a.id);
}

describe("searchApplications", () => {
  it("hands the board back untouched when nothing is typed", () => {
    expect(searchApplications(BOARD, "")).toBe(BOARD);
    expect(searchApplications(BOARD, "   ")).toBe(BOARD);
  });

  it("finds a posting by its title and by its company", () => {
    expect(found("machine learning")).toEqual([1]);
    expect(found("orbital")).toEqual([2]);
  });

  it("ignores case", () => {
    expect(found("NIMBUS")).toEqual([1]);
  });

  it("searches the fields the card never prints", () => {
    // The city, the platform it came from and the keywords are all things you
    // would type and none of them is on a board card.
    expect(found("paris")).toEqual([2]);
    expect(found("adzuna")).toEqual([2]);
    expect(found("pytorch")).toEqual([1]);
    expect(found("internship")).toEqual([1, 2]);
  });

  it("searches the status, so a column header is also a search", () => {
    expect(found("technical")).toEqual([2]);
    // Every round is an interview, whatever its own name says.
    expect(found("interview")).toEqual([2]);
  });

  it("searches what you wrote yourself", () => {
    const board = [
      application(3, { notes: "Claire mentioned the ingest rewrite." }),
      application(4, { next_action: "Send the portfolio link" }),
      application(5, { personalisation: "Met them at the Forum INSA." }),
    ];
    expect(found("claire", board)).toEqual([3]);
    expect(found("portfolio", board)).toEqual([4]);
    expect(found("forum insa", board)).toEqual([5]);
  });

  it("never reads the posting's full description", () => {
    // "six-month" is in `description` and nowhere else. If it matched, every
    // word of every posting would, and the field would stop narrowing anything.
    expect(found("six-month")).toEqual([]);
  });

  it("narrows with each extra word rather than widening", () => {
    expect(found("intern")).toEqual([1, 2]);
    expect(found("intern nimbus")).toEqual([1]);
    // Both words exist on the board, but not on the same row.
    expect(found("nimbus orbital")).toEqual([]);
  });

  it("matches words sitting in different fields, in any order", () => {
    expect(found("lyon machine")).toEqual([1]);
    expect(found("machine lyon")).toEqual([1]);
  });

  it("ignores accents in both directions", () => {
    const board = [application(6, { notes: "Équipe données, très bon accueil." })];
    expect(found("donnees", board)).toEqual([6]);
    expect(found("équipe", board)).toEqual([6]);
    expect(found("TRES", board)).toEqual([6]);
  });

  it("treats punctuation as a space on both sides", () => {
    // `google_search` is machine-written; "Lyon, France" is not. Both have to
    // answer to the words in them.
    expect(found("google search")).toEqual([1]);
    expect(found("google_search")).toEqual([1]);
    expect(found("lyon, france")).toEqual([1]);
  });

  it("survives an application whose posting is missing", () => {
    const board = [application(7, { job: null, notes: "Applied by email." })];
    expect(found("email", board)).toEqual([7]);
    expect(found("nimbus", board)).toEqual([]);
  });
});
