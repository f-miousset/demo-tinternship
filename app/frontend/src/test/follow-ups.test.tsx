/**
 * The Tracker's nudge, and the two honest ways to answer it.
 *
 * Sending the email is the expected one. The other is a posting with nobody
 * behind it — an agency listing, a portal that answers nothing, a form with no
 * name — where the candidate has nowhere to send anything. That case must not
 * be answered with "Mark as sent": the note it writes lands in the timeline
 * `follow_up.draft_context` hands the writer, so the next chase would be
 * written as a second one to somebody who never got a first. See
 * `documentation/follow-up.md`.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FollowUp } from "../lib/types";
import { renderApp, stubApi } from "./harness";

const SILENT: FollowUp = {
  application_id: 7,
  job_posting_id: 3,
  status: "applied",
  language: "en",
  days_silent: 21,
  last_activity: "2026-08-01T09:00:00Z",
  job: {
    title: "Data Engineering Intern",
    company: "Datadog",
    apply_url: "https://example.test/job",
  },
  draft: null,
  draft_stale: false,
};

/**
 * The due list, answering as the real API does: the nudge is gone once the
 * application has an event on it, whichever of the two buttons wrote one.
 */
function trackerWithOneNudge() {
  const posted: string[] = [];
  stubApi({
    "/api/applications/follow-ups": () =>
      new Response(
        JSON.stringify({ after_days: 14, follow_ups: posted.length ? [] : [SILENT] }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    "/api/applications/7/follow-up/no-contact": (url: string) => {
      posted.push(url);
      return new Response(JSON.stringify({ id: 7 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
  });
  return posted;
}

describe("the follow-up panel", () => {
  it("records that there was nobody to contact, and clears the nudge", async () => {
    const posted = trackerWithOneNudge();
    renderApp("/tracker");

    fireEvent.click(await screen.findByRole("button", { name: "Failed to contact anyone" }));

    await waitFor(() => expect(posted.length).toBe(1));
    expect(posted[0]).toContain("/api/applications/7/follow-up/no-contact");
    await waitFor(() =>
      expect(screen.queryByText("One application is waiting on a reply")).toBeNull(),
    );
  });
});
