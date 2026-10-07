/**
 * The Tracker's search field, mounted on the real page.
 *
 * The board shows one status at a time, so most cases open on
 * `?status=applied`, where Nimbus Labs is; a search that empties the chosen
 * status falls through to the first one it left, which is how Orbital SA
 * (an interview) still shows after searching "orbital".
 *
 * `lib/trackerSearch.test.ts` already proves what matches what. What is worth
 * mounting the page for is the scoping, which is the part a reader can get
 * wrong: the columns narrow, the charts above the field do not, a
 * search that finds nothing says so instead of leaving a blank page, and the
 * query lives in the URL so that opening an application and coming back does
 * not throw the search away.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { application, job, renderApp, stubApi } from "./harness";
import type { Application } from "../lib/types";

const BOARD = [
  application(1, job(1, "Machine Learning Intern", "Nimbus Labs")),
  application(2, job(2, "Data Engineering Intern", "Orbital SA", { location: "Paris, France" }), {
    status: "hr_pre_call",
  }),
  application(3, job(3, "Backend Intern", "Vela Systems"), { status: "saved" }),
];

/** Answer `/api/applications` differently per view, as the real API does. */
function views(board: Application[], trashed: Application[] = []) {
  return (url: string) =>
    new Response(
      JSON.stringify({ applications: url.includes("view=trashed") ? trashed : board }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
}

function searchField(): HTMLInputElement {
  return screen.getByLabelText("Search applications") as HTMLInputElement;
}

describe("the Tracker's search field", () => {
  beforeEach(() => {
    stubApi({ "/api/applications": views(BOARD) });
  });

  it("is not offered on an empty board", async () => {
    stubApi({ "/api/applications": views([]) });
    renderApp("/tracker");

    expect(await screen.findByText("No applications yet")).toBeTruthy();
    expect(screen.queryByLabelText("Search applications")).toBeNull();
  });

  it("narrows the board to what matches", async () => {
    renderApp("/tracker?status=applied");
    expect(await screen.findByText("Nimbus Labs")).toBeTruthy();

    fireEvent.change(searchField(), { target: { value: "orbital" } });

    await waitFor(() => expect(screen.queryByText("Nimbus Labs")).toBeNull());
    expect(screen.getByText("Orbital SA")).toBeTruthy();
    expect(screen.queryByText("Vela Systems")).toBeNull();
    expect(screen.getByText("1 of 3 shown")).toBeTruthy();
  });

  it("leaves the charts reading the whole board", async () => {
    renderApp("/tracker?status=applied");
    expect(await screen.findByText("Nimbus Labs")).toBeTruthy();

    fireEvent.change(searchField(), { target: { value: "orbital" } });
    await waitFor(() => expect(screen.queryByText("Nimbus Labs")).toBeNull());

    // Tracked is still 3 and Sent still 2: a response rate computed over
    // whatever happens to match a search is not a response rate.
    // The field sits above the charts now, so they say what they count.
    expect(screen.getByText("All 3 applications — the search narrows the board only.")).toBeTruthy();
    expect(screen.getByRole("img", { name: "Tracked: 3" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Sent: 2, 67%" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Got a response: 1, 50% of sent" })).toBeTruthy();
    expect(
      screen.getByRole("img", {
        name: "By status — Saved: 1 (33%), Applied: 1 (33%), HR pre-call: 1 (33%)",
      }),
    ).toBeTruthy();
    // No ghosted application and no later round yet, so no entry for them —
    // but offer and rejected keep theirs at 0.
    expect(
      screen.getByRole("img", {
        name: "Outcomes — HR pre-call: 1 (100%), Offer: 0 (0%), Rejected: 0 (0%)",
      }),
    ).toBeTruthy();
  });

  it("counts a rejection as a response, and a ghosting as an outcome only", async () => {
    stubApi({
      "/api/applications": views([
        ...BOARD,
        application(4, job(4, "Research Intern", "Helio"), { status: "rejected" }),
        application(5, job(5, "Platform Intern", "Kite"), { status: "ghosted" }),
      ]),
    });
    renderApp("/tracker?status=rejected");
    expect(await screen.findByText("Helio")).toBeTruthy();

    // Sent is applied + HR pre-call + rejected + ghosted = 4; the interview and
    // the rejection are both answers, the ghosting is not.
    expect(screen.getByRole("img", { name: "Sent: 4, 80%" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Got a response: 2, 50% of sent" })).toBeTruthy();
    // …but it is how one of them ended, so it is a segment of the one
    // outcomes bar, and the four shares are of the four together.
    expect(
      screen.getByRole("img", {
        name: "Outcomes — HR pre-call: 1 (33%), Offer: 0 (0%), Rejected: 1 (33%), Ghosted: 1 (33%)",
      }),
    ).toBeTruthy();
  });

  it("matches the city and the note, not only the title and the company", async () => {
    stubApi({
      "/api/applications": views([
        ...BOARD,
        application(4, job(4, "Research Intern", "Helio"), {
          notes: "Claire mentioned the ingest rewrite.",
        }),
      ]),
    });
    renderApp("/tracker?status=applied");
    expect(await screen.findByText("Nimbus Labs")).toBeTruthy();

    fireEvent.change(searchField(), { target: { value: "paris" } });
    await waitFor(() => expect(screen.queryByText("Nimbus Labs")).toBeNull());
    expect(screen.getByText("Orbital SA")).toBeTruthy();

    fireEvent.change(searchField(), { target: { value: "claire" } });
    await waitFor(() => expect(screen.queryByText("Orbital SA")).toBeNull());
    expect(screen.getByText("Helio")).toBeTruthy();
  });

  it("says so when nothing matches, and clears back to the whole board", async () => {
    renderApp("/tracker?status=applied");
    expect(await screen.findByText("Nimbus Labs")).toBeTruthy();

    fireEvent.change(searchField(), { target: { value: "zzz" } });

    expect(await screen.findByText("Nothing matches “zzz”")).toBeTruthy();
    expect(screen.getByText("0 of 3 shown")).toBeTruthy();
    // Not the day-one empty state — there are applications, they just do not
    // match, and telling the user to go and swipe some cards would be wrong.
    expect(screen.queryByText("No applications yet")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Clear the search" }));

    expect(await screen.findByText("Nimbus Labs")).toBeTruthy();
    expect(searchField().value).toBe("");
  });

  it("points at the trash when there is one and the search came up empty", async () => {
    stubApi({
      "/api/applications": views(BOARD, [
        application(9, job(9, "Ops Intern", "Castor"), {
          trashed_at: "2026-09-08T09:00:00+00:00",
        }),
      ]),
    });
    renderApp("/tracker?status=applied");
    expect(await screen.findByText("Nimbus Labs")).toBeTruthy();

    fireEvent.change(searchField(), { target: { value: "castor" } });

    expect(await screen.findByText(/This searches the board only/)).toBeTruthy();
  });

  it("reads its query from the URL, so coming back keeps the search", async () => {
    renderApp("/tracker?q=vela");

    expect(await screen.findByText("Vela Systems")).toBeTruthy();
    expect(searchField().value).toBe("vela");
    expect(screen.queryByText("Nimbus Labs")).toBeNull();
  });

  describe("bringing the results into view", () => {
    let scrollBy: ReturnType<typeof vi.fn>;

    /** Lay the page out as a phone would, with the results `resultsTop` px down. */
    function layout(resultsTop: number) {
      vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (
        this: Element,
      ) {
        if (this.classList.contains("header-dock")) return new DOMRect(0, 0, 375, 80);
        if (this.classList.contains("space-y-5") && this.querySelector("[role=tabpanel]")) {
          return new DOMRect(0, resultsTop, 375, 400);
        }
        return new DOMRect(0, 0, 0, 0);
      });
    }

    beforeEach(() => {
      scrollBy = vi.fn();
      window.scrollBy = scrollBy as unknown as typeof window.scrollBy;
    });
    afterEach(() => vi.restoreAllMocks());

    it("scrolls to them once the typing pauses, when the emails push them off screen", async () => {
      renderApp("/tracker?status=applied");
      expect(await screen.findByText("Nimbus Labs")).toBeTruthy();
      layout(1400);

      fireEvent.change(searchField(), { target: { value: "orbital" } });

      expect(scrollBy).not.toHaveBeenCalled();
      // Stops 12px under the 80px header: 1400 - 80 - 12.
      await waitFor(() => expect(scrollBy).toHaveBeenCalledWith({ top: 1308, behavior: "smooth" }), {
        timeout: 2000,
      });
    });

    it("leaves the page alone when the results already show", async () => {
      renderApp("/tracker?status=applied");
      expect(await screen.findByText("Nimbus Labs")).toBeTruthy();
      layout(300);

      fireEvent.change(searchField(), { target: { value: "orbital" } });

      await waitFor(() => expect(screen.getByText("1 of 3 shown")).toBeTruthy());
      await new Promise((resolve) => setTimeout(resolve, 800));
      expect(scrollBy).not.toHaveBeenCalled();
    });

    it("does not scroll on arriving with a search already in the URL", async () => {
      layout(1400);
      renderApp("/tracker?q=vela");
      expect(await screen.findByText("Vela Systems")).toBeTruthy();

      await new Promise((resolve) => setTimeout(resolve, 800));
      expect(scrollBy).not.toHaveBeenCalled();
    });
  });
});
