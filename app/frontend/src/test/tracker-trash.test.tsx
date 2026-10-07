/**
 * The Tracker's trash: applications you gave up on, and everything they kept.
 *
 * The board and this pile are two views of one endpoint, and the thing worth
 * testing is that they cannot be confused — a trashed application is off the
 * board and out of the three counters, and the pile still shows what it is
 * carrying, because "nothing was deleted" is the only reason throwing one away
 * is safe enough to do.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { renderApp, stubApi } from "./harness";
import type { Application, Job } from "../lib/types";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 4,
    title: "Machine Learning Intern",
    company: "Nimbus Labs",
    location: "Lyon, France",
    remote: "hybrid",
    url: "https://nimbus.test/jobs/4",
    apply_url: "https://nimbus.test/jobs/4/apply",
    source: "google_search",
    description: "Six months on the training platform team.",
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
    keywords: [],
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

function application(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    job_posting_id: 4,
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

/** Answer `/api/applications` differently per view, as the real API does. */
function views(board: Application[], trashed: Application[]) {
  return (url: string) =>
    new Response(
      JSON.stringify({ applications: url.includes("view=trashed") ? trashed : board }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
}

describe("the Tracker's trash", () => {
  beforeEach(() => {
    stubApi({ "/api/applications": views([], []) });
  });

  it("counts what is in it on the button", async () => {
    stubApi({
      "/api/applications": views(
        [],
        [application({ trashed_at: "2026-09-08T09:00:00+00:00" })],
      ),
    });
    renderApp("/tracker");

    expect(await screen.findByRole("button", { name: "Trash (1)" })).toBeTruthy();
  });

  it("keeps a trashed application off the board and out of the counters", async () => {
    // Two calls, two answers. The board asks for `view=board`, so an
    // application in the trash is not in the list the columns and the three
    // tallies are built from.
    stubApi({
      "/api/applications": views(
        [],
        [application({ trashed_at: "2026-09-08T09:00:00+00:00" })],
      ),
    });
    renderApp("/tracker");

    expect(await screen.findByText("No applications yet")).toBeTruthy();
    expect(screen.queryByText("Nimbus Labs")).toBeNull();
  });

  it("shows what each one kept, and puts it back", async () => {
    const urls: string[] = [];
    stubApi({
      "/api/applications": views(
        [],
        [
          application({
            status: "hr_interview",
            trashed_at: "2026-09-08T09:00:00+00:00",
            artifacts: [
              {
                id: 7,
                kind: "resume",
                version: 2,
                revisions: 1,
                rendered_path: "resume.docx",
                created_at: "2026-08-27T09:00:00+00:00",
              },
            ],
          }),
        ],
      ),
      "/api/applications/1/trash": (url: string) => {
        urls.push(url);
        return new Response(JSON.stringify(application()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    });
    renderApp("/tracker");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));

    // The status is the column it goes back to, and the artifact badge is the
    // whole reason this pile is not a delete: a package that took two model
    // runs to write is still on the row.
    expect(await screen.findByText("Nimbus Labs")).toBeTruthy();
    expect(screen.getByText("HR interview")).toBeTruthy();
    expect(screen.getByText("resume")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Put back on the board" }));

    await waitFor(() => expect(urls.length).toBe(1));
    expect(urls[0]).toContain("trashed=false");
  });

  it("deletes one forever only on a second tap", async () => {
    const deletes: string[] = [];
    stubApi({
      "/api/applications": views(
        [],
        [application({ trashed_at: "2026-09-08T09:00:00+00:00" })],
      ),
      "/api/applications/1": (url: string, init?: RequestInit) => {
        if (init?.method === "DELETE") deletes.push(url);
        return new Response(JSON.stringify({ deleted: 1, files: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    });
    renderApp("/tracker");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete forever" }));

    // Armed, not fired: the one irreversible button in the pile asks first,
    // in place.
    expect(deletes).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Tap again to delete" }));

    await waitFor(() => expect(deletes.length).toBe(1));
  });

  it("empties the whole pile", async () => {
    const deletes: string[] = [];
    stubApi({
      "/api/applications": views(
        [],
        [application({ trashed_at: "2026-09-08T09:00:00+00:00" })],
      ),
      "/api/applications/trash": (url: string, init?: RequestInit) => {
        if (init?.method === "DELETE") deletes.push(url);
        return new Response(JSON.stringify({ deleted: 1, files: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    });
    renderApp("/tracker");

    fireEvent.click(await screen.findByRole("button", { name: "Trash (1)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Empty the trash (1)" }));
    fireEvent.click(screen.getByRole("button", { name: "Tap again to delete all 1" }));

    await waitFor(() => expect(deletes.length).toBe(1));
  });

  it("says the pile is empty rather than showing nothing", async () => {
    renderApp("/tracker");

    fireEvent.click(await screen.findByRole("button", { name: "Trash" }));

    expect(await screen.findByText("Nothing thrown away yet")).toBeTruthy();
  });
});
